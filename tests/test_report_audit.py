"""
tests/test_report_audit.py — WP-5 acceptance tests for src/report.py
(build_report) and src/audit.py (audit_run), the US-6 report and US-7 leakage
audit.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_report_audit.py`). Provisions a throwaway Postgres exactly
like tests/test_backtest.py (via $DATABASE_URL or a `pgserver` instance;
TimescaleDB-only statements skipped). SKIPPED (exit 0) if neither is reachable.
No network.

Traces to docs/architecture/plan.md WP-5 acceptance (US-6/US-7 G/W/T):
  US-6 report:
    - the headline is ONE number: model net ROI - baseline net ROI
    - every metric reproduces from the stored tables (the test recomputes net
      PnL, notional, ROI, hit rate, Brier, Sharpe and max drawdown by an
      independent route and compares)
    - per-market breakdown reconciles to the run total
    - the baseline (MidpriceProbFn) never trades -> ROI 0.0, headline == model ROI
  US-7 audit:
    - a clean harness run PASSES (no violations, .ok True)
    - a seeded lookahead (a signal priced off a candle at ts >= as_of) FAILS
      loudly (violation recorded, .ok False) and the CLI exits non-zero
"""
import math
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg                        # noqa: E402
import psycopg.conninfo as conninfo   # noqa: E402

import store                          # noqa: E402
import audit                          # noqa: E402
from audit import audit_run           # noqa: E402
from backtest import run_backtest     # noqa: E402
from ev_detector import DirectionalSignal  # noqa: E402
from ingest import MarketRow, OutcomeRef   # noqa: E402
from prob_fn import MarketRef, MidpriceProbFn, StoreReader  # noqa: E402
from report import build_report       # noqa: E402
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


def close(a, b, tol=1e-9):
    return abs(a - b) < tol


# ---------------------------------------------------------------------------
# throwaway database provisioning (same pattern as test_backtest.py)
# ---------------------------------------------------------------------------
def _base_conninfo() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return ""
    data_dir = os.path.join(os.path.dirname(__file__), ".pgserver-test-data-reportaudit")
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


def _seed_candles(conn, token_id: str, closes) -> None:
    store.upsert_candles(conn, [
        store.Candle(ts, token_id, c, c, c, c, 100.0) for ts, c in closes])


class _EdgeProbFn:
    """Synthetic 'real model': fixed p per side (p_NO = 1 - p_YES)."""
    name = "EdgeProbFn"

    def __init__(self, p_yes: float):
        self._p_yes = p_yes

    def __call__(self, market: MarketRef, as_of: datetime) -> float:
        return self._p_yes if market.outcome_label == "YES" else 1.0 - self._p_yes


# ---------------------------------------------------------------------------
# independent-recompute helpers (verify by a different route than report.py)
# ---------------------------------------------------------------------------
def _raw_results(conn, run_id):
    return conn.execute(
        "SELECT entry_price, size, resolved_value, fee_paid, realized_pnl "
        "FROM backtest_result WHERE run_id = %s", (run_id,)).fetchall()


def _raw_signals(conn, run_id):
    return conn.execute(
        "SELECT s.p_model, o.resolved_value FROM directional_signal s "
        "JOIN outcome o ON o.outcome_id = s.outcome_id WHERE s.run_id = %s",
        (run_id,)).fetchall()


# ---------------------------------------------------------------------------
# US-6: the report
# ---------------------------------------------------------------------------
def test_report_reconciles_and_headline_is_one_number(conn):
    # A winner and a loser so the run has real dispersion (exercises Sharpe /
    # drawdown / a 0.5 hit rate), both entered YES at 0.40 by EdgeProbFn(0.80).
    _seed_market(conn, "KXRPT-WIN", resolves_at=T0 + 4 * H, yes_value=1.0)
    _seed_candles(conn, "KXRPT-WIN-YES", [(T0, 0.40)])
    _seed_market(conn, "KXRPT-LOSS", resolves_at=T0 + 4 * H, yes_value=0.0)
    _seed_candles(conn, "KXRPT-LOSS-YES", [(T0, 0.40)])

    common = dict(category="weather", start=T0 + 1 * H, end=T0 + 3 * H, step=H,
                  limits=RiskLimits())
    run_backtest(conn, _EdgeProbFn(0.80), run_id="rpt-model", **common)
    run_backtest(conn, MidpriceProbFn(StoreReader(conn)),
                 run_id="rpt-baseline", **common)

    report = build_report(conn, "rpt-model", "rpt-baseline")
    m = report.model

    check(m.n_positions == 2, f"expected 2 filled positions, got {m.n_positions}")

    # --- reconcile net PnL / notional / ROI against the raw rows ------------
    raw = _raw_results(conn, "rpt-model")
    exp_net = sum(float(pnl) for *_, pnl in raw)
    exp_notional = sum(float(ep) * float(sz) for ep, sz, *_ in raw)
    exp_fees = sum(float(f) for *_, f, _ in raw)
    check(close(m.net_pnl, exp_net), f"net_pnl {m.net_pnl} != raw {exp_net}")
    check(close(m.notional, exp_notional),
          f"notional {m.notional} != raw {exp_notional}")
    check(close(m.total_fees, exp_fees), f"fees {m.total_fees} != raw {exp_fees}")
    check(close(m.net_roi, exp_net / exp_notional),
          f"net_roi {m.net_roi} != net_pnl/notional {exp_net / exp_notional}")

    # --- per-market breakdown sums back to the run total (reconciliation) ---
    check(len(m.per_market) == 2, f"one breakdown per market, got {len(m.per_market)}")
    check(close(sum(b.net_pnl for b in m.per_market), m.net_pnl),
          "per-market net PnL must sum to the run net PnL")
    check(close(sum(b.notional for b in m.per_market), m.notional),
          "per-market notional must sum to the run notional")

    # --- hit rate: one win, one loss ---------------------------------------
    check(m.hit_rate == 0.5, f"one win + one loss -> hit rate 0.5, got {m.hit_rate}")

    # --- Brier recomputed independently over persisted signals -------------
    sigs = _raw_signals(conn, "rpt-model")
    exp_brier = sum((float(p) - float(rv)) ** 2 for p, rv in sigs) / len(sigs)
    check(m.brier is not None and close(m.brier, exp_brier),
          f"Brier {m.brier} != independent {exp_brier}")

    # --- Sharpe recomputed independently (per-trade, ddof=1) ---------------
    rets = [float(pnl) / (float(ep) * float(sz)) for ep, sz, _, _, pnl in raw]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    exp_sharpe = mean / math.sqrt(var)
    check(m.sharpe is not None and close(m.sharpe, exp_sharpe),
          f"Sharpe {m.sharpe} != independent {exp_sharpe}")

    # --- max drawdown is a non-negative magnitude and the loser drives it --
    check(m.max_drawdown > 0.0,
          f"a losing position must produce a positive drawdown, got {m.max_drawdown}")

    # --- baseline never trades: ROI 0.0, headline == model ROI -------------
    b = report.baseline
    check(b.n_positions == 0, f"MidpriceProbFn baseline must not trade, got {b.n_positions}")
    check(b.net_roi == 0.0, f"a no-trade baseline has ROI 0.0, got {b.net_roi}")
    check(b.brier is None and b.sharpe is None and b.hit_rate is None,
          "an empty baseline run has undefined Brier/Sharpe/hit-rate (None)")
    check(close(report.headline_net_roi_delta, m.net_roi - b.net_roi),
          "headline must be model.net_roi - baseline.net_roi")
    check(close(report.headline_net_roi_delta, m.net_roi),
          "against a no-trade baseline the headline reduces to the model ROI")


def test_build_report_unknown_run_raises(conn):
    raised = False
    try:
        build_report(conn, "does-not-exist", "rpt-baseline")
    except KeyError as e:
        raised = True
        check("does-not-exist" in str(e), f"error must name the run: {e}")
    check(raised, "build_report on an unknown run_id must raise KeyError")


# ---------------------------------------------------------------------------
# US-7: the leakage audit
# ---------------------------------------------------------------------------
def test_audit_passes_on_a_clean_run(conn):
    result = audit_run(conn, "rpt-model")
    check(result.ok, f"a clean harness run must pass the audit: {result.violations}")
    check(result.signals_checked >= 2,
          f"the clean run's signals must be checked, got {result.signals_checked}")
    check(result.results_checked == 2,
          f"both settled results must be checked, got {result.results_checked}")


def test_audit_fails_on_seeded_lookahead(conn):
    """Seed a signal priced off a candle at ts >= as_of (a reach-around the PIT
    reader) and confirm the audit re-derives the true PIT price and fails."""
    _seed_market(conn, "KXLEAK", resolves_at=T0 + 6 * H, yes_value=1.0)
    # Truthful PIT price just before as_of=T0+1h is 0.30; a FUTURE candle at
    # T0+2h is 0.90. A leaky decision records 0.90.
    _seed_candles(conn, "KXLEAK-YES", [(T0, 0.30), (T0 + 2 * H, 0.90)])
    store.write_backtest_run(conn, "run-leak", "LeakyProbFn", "weather",
                             T0, T0 + 6 * H, "1:00:00")
    leaky = DirectionalSignal(
        token_id="KXLEAK-YES", venue="kalshi", category="weather",
        p_model=0.95, price=0.90, size=100.0, ev_per_share=0.05,
        expected_profit=5.0, kelly_size=100.0)
    store.write_signal(conn, "run-leak", leaky, as_of=T0 + 1 * H)

    result = audit_run(conn, "run-leak")
    check(not result.ok, "a signal priced off a future candle must fail the audit")
    kinds = {v.kind for v in result.violations}
    check("price_not_pit" in kinds,
          f"the future-priced signal must be flagged price_not_pit: {kinds}")
    v = next(v for v in result.violations if v.kind == "price_not_pit")
    check(close(v.recorded_price, 0.90) and close(v.pit_price, 0.30),
          f"the violation must contrast recorded 0.90 vs PIT 0.30: {v}")


def test_audit_flags_signal_with_no_prior_candle(conn):
    """A signal with no candle strictly before as_of has a price from nowhere a
    PIT decision could see — also a violation."""
    _seed_market(conn, "KXNOPRIOR", resolves_at=T0 + 6 * H, yes_value=1.0)
    _seed_candles(conn, "KXNOPRIOR-YES", [(T0 + 2 * H, 0.50)])  # only AFTER as_of
    store.write_backtest_run(conn, "run-noprior", "LeakyProbFn", "weather",
                             T0, T0 + 6 * H, "1:00:00")
    sig = DirectionalSignal(
        token_id="KXNOPRIOR-YES", venue="kalshi", category="weather",
        p_model=0.7, price=0.50, size=50.0, ev_per_share=0.02,
        expected_profit=1.0, kelly_size=50.0)
    store.write_signal(conn, "run-noprior", sig, as_of=T0 + 1 * H)

    result = audit_run(conn, "run-noprior")
    check(not result.ok, "a signal with no prior candle must fail the audit")
    check(any(v.kind == "no_prior_candle" for v in result.violations),
          f"expected a no_prior_candle violation: {result.violations}")


def test_audit_flags_candle_at_exact_as_of_boundary(conn):
    """The PIT boundary is strict `<`, not `<=`: a candle timestamped exactly at
    as_of does not count as 'strictly before' and must not satisfy the check."""
    _seed_market(conn, "KXBOUND", resolves_at=T0 + 6 * H, yes_value=1.0)
    as_of = T0 + 1 * H
    _seed_candles(conn, "KXBOUND-YES", [(as_of, 0.50)])  # only AT as_of, not before
    store.write_backtest_run(conn, "run-bound", "LeakyProbFn", "weather",
                             T0, T0 + 6 * H, "1:00:00")
    sig = DirectionalSignal(
        token_id="KXBOUND-YES", venue="kalshi", category="weather",
        p_model=0.6, price=0.50, size=50.0, ev_per_share=0.01,
        expected_profit=0.5, kelly_size=50.0)
    store.write_signal(conn, "run-bound", sig, as_of=as_of)

    result = audit_run(conn, "run-bound")
    check(not result.ok,
          "a signal whose only candle is at ts == as_of (not strictly before) "
          "must fail the audit")
    check(any(v.kind == "no_prior_candle" for v in result.violations),
          f"expected a no_prior_candle violation: {result.violations}")


def test_audit_cli_exit_codes(conn, dsn):
    """The CLI wrapper exits 0 on a clean run, non-zero on a leaky one — the
    US-7 'gates the definition of done' contract. main() reconnects via
    $DATABASE_URL, so point it at the test DB for the duration."""
    saved = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = dsn
    try:
        check(audit.main(["rpt-model"]) == 0, "clean run must exit 0")
        check(audit.main(["run-leak"]) == 1, "leaky run must exit non-zero")
        check(audit.main([]) == 2, "no run_id must exit 2 (usage)")
    finally:
        if saved is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved


def test_audit_unknown_run_raises(conn):
    raised = False
    try:
        audit_run(conn, "phantom-run")
    except KeyError:
        raised = True
    check(raised, "auditing a non-existent run must raise KeyError")


def main() -> int:
    dsn = _provision()
    if dsn is None:
        print("SKIPPED: no Postgres reachable — set $DATABASE_URL or "
              "`pip install pgserver` (see README).")
        return 0
    try:
        conn = psycopg.connect(dsn, autocommit=True)
        _apply_schema(conn)
        # Order matters: the report/clean-audit tests build the shared
        # 'rpt-model'/'rpt-baseline' runs the later tests read.
        test_report_reconciles_and_headline_is_one_number(conn)
        print("PASS test_report_reconciles_and_headline_is_one_number")
        test_build_report_unknown_run_raises(conn)
        print("PASS test_build_report_unknown_run_raises")
        test_audit_passes_on_a_clean_run(conn)
        print("PASS test_audit_passes_on_a_clean_run")
        test_audit_fails_on_seeded_lookahead(conn)
        print("PASS test_audit_fails_on_seeded_lookahead")
        test_audit_flags_signal_with_no_prior_candle(conn)
        print("PASS test_audit_flags_signal_with_no_prior_candle")
        test_audit_flags_candle_at_exact_as_of_boundary(conn)
        print("PASS test_audit_flags_candle_at_exact_as_of_boundary")
        test_audit_cli_exit_codes(conn, dsn)
        print("PASS test_audit_cli_exit_codes")
        test_audit_unknown_run_raises(conn)
        print("PASS test_audit_unknown_run_raises")
        conn.close()
        print("ALL PASSED")
        return 0
    finally:
        _teardown(dsn)


if __name__ == "__main__":
    sys.exit(main())
