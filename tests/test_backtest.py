"""
tests/test_backtest.py — WP-4 acceptance tests for src/backtest.py
(run_backtest, the EV backtest harness).

Standalone, no pytest dependency (repo convention:
`python3 tests/test_backtest.py`). Needs a real Postgres, reached the same
two ways as tests/test_store_persistence.py: $DATABASE_URL, or a throwaway
`pgserver` instance (TimescaleDB statements skipped — irrelevant here, see
that file's docstring). If neither is available, prints why and exits 0
(SKIPPED, not failed). A fresh uniquely-named database is created and
dropped, so no real dev/prod tables are touched. No network.

Traces to docs/architecture/plan.md WP-4 acceptance (US-5 G/W/T):
  - PIT: no decision at time T uses any price dated >= T (boundary test: a
    candle at exactly as_of must not set the entry price)
  - fees use the Kalshi formula (recomputed independently via fees.kalshi_fee)
  - the paper kill switch and exposure caps are active inside the replay
  - total PnL reconciles to the sum of per-signal realized PnL, in the
    summary AND against the backtest_result rows actually persisted
  - the harness runs identically against the placeholder (MidpriceProbFn)
    and a "real" model (a synthetic edge-holding ProbFn here)
  - re-running the same run_id is idempotent (row counts unchanged)
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg                        # noqa: E402
import psycopg.conninfo as conninfo   # noqa: E402

import store                          # noqa: E402
from backtest import run_backtest     # noqa: E402
from fees import kalshi_fee           # noqa: E402
from ingest import MarketRow, OutcomeRef       # noqa: E402
from prob_fn import MarketRef, MidpriceProbFn, StoreReader  # noqa: E402
from risk_execution import RiskLimits  # noqa: E402

SCHEMA_FILES = [
    os.path.join(os.path.dirname(__file__), "..", "schema", "001_schema.sql"),
    os.path.join(os.path.dirname(__file__), "..", "schema", "002_kalshi_ev.sql"),
]
TIMESCALE_MARKERS = ("timescaledb", "create_hypertable")

_state = {"server": None}

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# throwaway database provisioning (same pattern as test_store_persistence.py)
# ---------------------------------------------------------------------------
def _base_conninfo() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return ""
    data_dir = os.path.join(os.path.dirname(__file__), ".pgserver-test-data-backtest")
    srv = pgserver.get_server(data_dir)
    _state["server"] = srv
    return srv.get_uri()


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _apply_schema(conn) -> None:
    for path in SCHEMA_FILES:
        with open(path) as fh:
            sql = _strip_sql_comments(fh.read())
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except Exception as e:
                if any(m in stmt.lower() for m in TIMESCALE_MARKERS):
                    print(f"  (skip — no TimescaleDB extension here: {e})")
                    continue
                raise RuntimeError(f"schema statement failed:\n{stmt}\n-> {e}") from e


def _provision() -> str | None:
    base = _base_conninfo()
    if not base:
        return None
    info = conninfo.conninfo_to_dict(base)
    maint = dict(info)
    maint.setdefault("dbname", "postgres")
    try:
        conn = psycopg.connect(conninfo.make_conninfo(**maint), autocommit=True,
                                connect_timeout=5)
    except Exception as e:
        print(f"could not reach Postgres at {maint.get('host', 'default host')}: {e}")
        return None
    db_name = f"fairline_test_{uuid.uuid4().hex[:12]}"
    conn.execute(f'CREATE DATABASE "{db_name}"')
    conn.close()
    test_info = dict(info)
    test_info["dbname"] = db_name
    return conninfo.make_conninfo(**test_info)


def _teardown(dsn: str) -> None:
    try:
        info = conninfo.conninfo_to_dict(dsn)
        db_name = info.pop("dbname")
        conn = psycopg.connect(conninfo.make_conninfo(**info), autocommit=True)
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        conn.close()
    finally:
        if _state["server"] is not None:
            _state["server"].cleanup()


# ---------------------------------------------------------------------------
# seeding helpers
# ---------------------------------------------------------------------------
def _seed_market(conn, ticker: str, *, resolves_at: datetime,
                 yes_value: float) -> None:
    """One kalshi weather market with YES/NO outcomes and applied resolution
    (YES -> yes_value, NO -> 1-yes_value)."""
    market = MarketRow(
        venue="kalshi", external_id=ticker, question=f"synthetic {ticker}",
        category="weather", resolution_text="synthetic",
        resolves_at=resolves_at,
        outcomes=(OutcomeRef(f"{ticker}-YES", "YES", 0),
                  OutcomeRef(f"{ticker}-NO", "NO", 1)))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    store.apply_resolutions(conn, [
        store.ResolutionRow(ticker, f"{ticker}-YES", yes_value),
        store.ResolutionRow(ticker, f"{ticker}-NO", 1.0 - yes_value)])


def _seed_candles(conn, token_id: str, closes: list[tuple[datetime, float]]) -> None:
    store.upsert_candles(conn, [
        store.Candle(ts, token_id, c, c, c, c, 100.0) for ts, c in closes])


class _EdgeProbFn:
    """Synthetic 'real model': fixed p per side, consistent (p_NO = 1-p_YES).
    Reads no data, so the PIT guarantee holds trivially."""
    name = "EdgeProbFn"

    def __init__(self, p_yes: float):
        self._p_yes = p_yes

    def __call__(self, market: MarketRef, as_of: datetime) -> float:
        return self._p_yes if market.outcome_label == "YES" else 1.0 - self._p_yes


def _count(conn, table: str, run_id: str) -> int:
    return conn.execute(
        f"SELECT count(*) FROM {table} WHERE run_id = %s", (run_id,)).fetchone()[0]


# ---------------------------------------------------------------------------
# acceptance tests
# ---------------------------------------------------------------------------
def test_edge_model_end_to_end(conn):
    """Entry fires, PIT boundary holds, fee matches the Kalshi formula, PnL
    reconciles in the summary and against the persisted rows."""
    ticker = "KXBT-E2E"
    _seed_market(conn, ticker, resolves_at=T0 + 4 * H, yes_value=1.0)
    # YES trades at 0.40 up to T0; a poison 0.99 candle at EXACTLY the first
    # as_of must be excluded by the strict `< as_of` boundary.
    _seed_candles(conn, f"{ticker}-YES", [(T0, 0.40), (T0 + 1 * H, 0.99)])
    # (NO side gets no candles -> per-step no_candle skip, never a crash.)

    p, price, bankroll, kf, size_step = 0.80, 0.40, 1_000.0, 0.25, 10.0
    summary = run_backtest(
        conn, _EdgeProbFn(p), category="weather",
        start=T0 + 1 * H, end=T0 + 3 * H, step=H,
        limits=RiskLimits(), run_id="run-e2e",
        bankroll=bankroll, kelly_fraction=kf, size_step=size_step)

    check(summary.steps_run == 2, f"window [T0+1h, T0+3h) @1h = 2 steps, got {summary.steps_run}")
    check(summary.entries_filled == 1,
          f"exactly one YES entry expected (held to resolution), got {summary.entries_filled}")
    check(len(summary.settled) == 1, f"one settled position, got {len(summary.settled)}")
    pos = summary.settled[0]

    # PIT boundary: entry priced off T0's 0.40, not the 0.99 at ts == as_of.
    check(pos.entry_price == price,
          f"entry must use the last close STRICTLY before as_of (0.40), got {pos.entry_price}")
    check(pos.entry_as_of == T0 + 1 * H, f"entry at the first step, got {pos.entry_as_of}")

    # Size: quarter-Kelly stake floored to the sizing step (recomputed here
    # by a different route than ev_detector's loop).
    k_cap = bankroll * kf * (p - price) / (1.0 - price) / price
    expected_size = (k_cap // size_step) * size_step
    check(pos.size == expected_size,
          f"size must be kelly cap floored to step: {expected_size}, got {pos.size}")

    # Fee: the Kalshi formula, recomputed independently.
    expected_fee = kalshi_fee(pos.size, pos.entry_price)
    check(abs(pos.fee_paid - expected_fee) < 1e-9,
          f"fee must match kalshi_fee: {expected_fee}, got {pos.fee_paid}")

    # PnL: hold-to-resolution arithmetic, recomputed by hand.
    expected_pnl = pos.size * (1.0 - price) - expected_fee
    check(abs(pos.realized_pnl - expected_pnl) < 1e-9,
          f"pnl must be size*(rv-price)-fee = {expected_pnl}, got {pos.realized_pnl}")

    # Reconciliation: summary total == sum of parts == DB sum (US-5).
    check(abs(summary.total_realized_pnl -
              sum(s.realized_pnl for s in summary.settled)) < 1e-9,
          "summary total must equal the sum of its settled positions")
    db_sum = conn.execute(
        "SELECT coalesce(sum(realized_pnl), 0) FROM backtest_result "
        "WHERE run_id = %s", ("run-e2e",)).fetchone()[0]
    check(abs(summary.total_realized_pnl - float(db_sum)) < 1e-9,
          f"summary total {summary.total_realized_pnl} must reconcile to "
          f"backtest_result sum {db_sum}")

    check(summary.skipped.get("no_candle", 0) >= 1,
          f"the candle-less NO side must be counted as skipped: {summary.skipped}")
    check(_count(conn, "directional_signal", "run-e2e") == 1,
          "exactly one decision-time signal row expected")
    check(_count(conn, "backtest_result", "run-e2e") == 1,
          "exactly one result row expected")


def test_rerun_is_idempotent(conn):
    """Re-running the same run_id updates in place, never duplicates."""
    before = (_count(conn, "directional_signal", "run-e2e"),
              _count(conn, "backtest_result", "run-e2e"))
    run_backtest(
        conn, _EdgeProbFn(0.80), category="weather",
        start=T0 + 1 * H, end=T0 + 3 * H, step=H,
        limits=RiskLimits(), run_id="run-e2e")
    after = (_count(conn, "directional_signal", "run-e2e"),
             _count(conn, "backtest_result", "run-e2e"))
    check(before == after, f"re-run must not duplicate rows: {before} -> {after}")


def test_placeholder_baseline_runs_identically(conn):
    """MidpriceProbFn (the US-6 baseline) drops in with no harness change:
    p == price -> no post-fee edge -> zero entries, zero exceptions."""
    summary = run_backtest(
        conn, MidpriceProbFn(StoreReader(conn)), category="weather",
        start=T0 + 1 * H, end=T0 + 3 * H, step=H,
        limits=RiskLimits(), run_id="run-baseline")
    check(summary.prob_fn_name == "MidpriceProbFn",
          f"prob_fn_name must come from the ProbFn: {summary.prob_fn_name}")
    check(summary.entries_filled == 0,
          f"p=price has no post-fee edge; got {summary.entries_filled} entries")
    check(summary.skipped.get("no_edge", 0) >= 1,
          f"baseline steps must be counted as no_edge: {summary.skipped}")
    check(summary.total_realized_pnl == 0.0, "no entries -> no PnL")


def test_engine_caps_gate_the_replay(conn):
    """A tiny per-trade notional cap rejects the entry inside the replay; the
    decision-time signal is still persisted (audit trail), no result rows."""
    summary = run_backtest(
        conn, _EdgeProbFn(0.80), category="weather",
        start=T0 + 1 * H, end=T0 + 3 * H, step=H,
        limits=RiskLimits(max_trade_notional=10.0), run_id="run-capped")
    check(summary.entries_filled == 0 and summary.entries_rejected >= 1,
          f"cap 10 must reject the ~$164 entry: filled={summary.entries_filled} "
          f"rejected={summary.entries_rejected}")
    check(_count(conn, "directional_signal", "run-capped") >= 1,
          "rejected signals must still be persisted at decision time")
    check(_count(conn, "backtest_result", "run-capped") == 0,
          "a never-filled run must write no results")


def test_kill_switch_trips_and_gates(conn):
    """A settled loss past daily_loss_limit trips the kill switch mid-replay
    and gates every later entry."""
    # Loser: YES bought at 0.50, resolves 0.0 at T0+2h -> big loss.
    _seed_market(conn, "KXBT-LOSS", resolves_at=T0 + 2 * H, yes_value=0.0)
    _seed_candles(conn, "KXBT-LOSS-YES", [(T0, 0.50)])
    # Later market: candles only from T0+90m, so its first possible entry
    # (T0+2h) lands after the loss settles and the switch trips.
    _seed_market(conn, "KXBT-LATE", resolves_at=T0 + 6 * H, yes_value=1.0)
    _seed_candles(conn, "KXBT-LATE-YES", [(T0 + timedelta(minutes=90), 0.40)])

    summary = run_backtest(
        conn, _EdgeProbFn(0.80), category="weather",
        start=T0 + 1 * H, end=T0 + 4 * H, step=H,
        limits=RiskLimits(daily_loss_limit=50.0), run_id="run-kill")

    check(summary.kill_tripped is True,
          f"the loss must trip the kill switch: {summary}")
    check(summary.entries_rejected >= 1,
          f"post-trip entries must be gated: rejected={summary.entries_rejected}")
    loss_rows = [s for s in summary.settled if s.token_id == "KXBT-LOSS-YES"]
    check(len(loss_rows) == 1 and loss_rows[0].realized_pnl < -50.0,
          f"the loser must settle at a loss past the limit: {loss_rows}")
    late = conn.execute(
        "SELECT count(*) FROM backtest_result r JOIN outcome_token ot "
        "ON ot.outcome_id = r.outcome_id WHERE r.run_id = %s "
        "AND ot.token_id = %s", ("run-kill", "KXBT-LATE-YES")).fetchone()[0]
    check(late == 0, "the kill-gated market must never produce a result row")


def test_size_step_zero_raises(conn):
    """size_step=0.0 must fail validation up front, not hang forever inside
    find_signal's `while size <= ...: size += step` sizing loop."""
    raised = False
    try:
        run_backtest(
            conn, _EdgeProbFn(0.80), category="weather",
            start=T0 + 1 * H, end=T0 + 2 * H, step=H,
            limits=RiskLimits(), run_id="run-sizestep-zero", size_step=0.0)
    except ValueError as e:
        raised = True
        check("size_step" in str(e), f"error must name size_step: {e}")
    check(raised, "size_step=0.0 must raise ValueError, not hang")


def test_size_step_negative_raises(conn):
    """size_step<0 must fail validation up front — otherwise vwap_fill returns
    NaN for a negative target and find_signal's guards silently pass a NaN
    signal through (NaN comparisons are always False)."""
    raised = False
    try:
        run_backtest(
            conn, _EdgeProbFn(0.80), category="weather",
            start=T0 + 1 * H, end=T0 + 2 * H, step=H,
            limits=RiskLimits(), run_id="run-sizestep-neg", size_step=-5.0)
    except ValueError as e:
        raised = True
        check("size_step" in str(e), f"error must name size_step: {e}")
    check(raised, "size_step=-5.0 must raise ValueError")


class _OutOfRangeProbFn:
    """Broken model: returns an out-of-[0,1] probability. Must fail the run
    loudly (per the module docstring), not be silently absorbed the way an
    exact-0/1 boundary is."""
    name = "OutOfRangeProbFn"

    def __call__(self, market: MarketRef, as_of: datetime) -> float:
        return 1.5


def test_prob_fn_out_of_range_raises(conn):
    ticker = "KXBT-BADP"
    _seed_market(conn, ticker, resolves_at=T0 + 4 * H, yes_value=1.0)
    _seed_candles(conn, f"{ticker}-YES", [(T0, 0.40)])
    _seed_candles(conn, f"{ticker}-NO", [(T0, 0.60)])

    raised = False
    try:
        run_backtest(
            conn, _OutOfRangeProbFn(), category="weather",
            start=T0 + 1 * H, end=T0 + 2 * H, step=H,
            limits=RiskLimits(), run_id="run-badp")
    except ValueError as e:
        raised = True
        check("outside [0,1]" in str(e), f"error must explain the range violation: {e}")
    check(raised,
          "a prob_fn returning 1.5 must raise ValueError from run_backtest, "
          "not be silently skipped as boundary_p")


class _ExactBoundaryProbFn:
    """A well-behaved model that legitimately clamps to the exact boundary
    (e.g. MidpriceProbFn on a 0.00/1.00 close) — "market decided", still a
    silent skip, never a raise."""
    name = "ExactBoundaryProbFn"

    def __call__(self, market: MarketRef, as_of: datetime) -> float:
        return 0.0 if market.outcome_label == "YES" else 1.0


def test_prob_fn_exact_boundary_still_skipped(conn):
    ticker = "KXBT-BOUND0"
    _seed_market(conn, ticker, resolves_at=T0 + 4 * H, yes_value=1.0)
    _seed_candles(conn, f"{ticker}-YES", [(T0, 0.40)])
    _seed_candles(conn, f"{ticker}-NO", [(T0, 0.60)])

    summary = run_backtest(
        conn, _ExactBoundaryProbFn(), category="weather",
        start=T0 + 1 * H, end=T0 + 2 * H, step=H,
        limits=RiskLimits(), run_id="run-bound0")
    check(summary.skipped.get("boundary_p", 0) >= 1,
          f"an exact 0.0/1.0 prob_fn output must still be a silent boundary_p "
          f"skip: {summary.skipped}")
    check(summary.entries_filled == 0, "a boundary p must never enter a trade")


def main() -> int:
    dsn = _provision()
    if dsn is None:
        print("SKIPPED: no Postgres reachable — set $DATABASE_URL or "
              "`pip install pgserver` (see README).")
        return 0
    tests = [
        test_edge_model_end_to_end,
        test_rerun_is_idempotent,
        test_placeholder_baseline_runs_identically,
        test_engine_caps_gate_the_replay,
        test_kill_switch_trips_and_gates,
        test_size_step_zero_raises,
        test_size_step_negative_raises,
        test_prob_fn_out_of_range_raises,
        test_prob_fn_exact_boundary_still_skipped,
    ]
    try:
        conn = psycopg.connect(dsn, autocommit=True)
        _apply_schema(conn)
        # Later tests reuse earlier tests' seeds deliberately (run-e2e's
        # market serves the baseline/cap tests); order matters.
        for t in tests:
            t(conn)
            print(f"PASS {t.__name__}")
        conn.close()
        print("ALL PASSED")
        return 0
    finally:
        _teardown(dsn)


if __name__ == "__main__":
    sys.exit(main())
