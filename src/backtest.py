"""
backtest.py — the EV backtest harness (WP-4, US-5, ADR-0005/0009).

Replays stored Kalshi history through the fee-aware, Kelly-capped directional
strategy and the paper Engine, producing hold-to-resolution realized PnL:

    per as_of step, per candidate outcome:
        price = last candlestick close strictly before as_of   (store PIT reader)
        p     = prob_fn(MarketRef, as_of)                      (ADR-0009 contract)
        sig   = ev_detector.find_signal(..., prob_fn=lambda _tok: p, ...)
        engine.execute_signal(sig, category=...)               (paper, all gates)
    at resolution:
        engine.settle(realized_pnl); store.write_backtest_result(...)

Point-in-time discipline (binding, US-5/US-7): every price this module trades
on comes through `store.candles_before`, which enforces `ts < as_of` in SQL —
the one place the guarantee lives (ADR-0009). `resolved_value` is read up
front but used ONLY at settlement, never passed to `prob_fn` or
`find_signal`, and no entry condition branches on it. `resolves_at` IS passed
to `prob_fn`, embedded in every `MarketRef` (a market's own scheduled close
time is legitimately knowable in advance — not a PIT violation).

Deliberate MVP simplifications (each recorded in backtest_run.params):

  * Synthesized one-level book. Kalshi's public API has no historical
    orderbook depth (ADR-0006), so each entry prices against a single ask
    level `(last close, book_depth)`. Depth-aware sizing therefore reduces
    to the Kelly + notional caps; `book_depth` is an explicit, recorded
    assumption, not a hidden one.
  * One open position per outcome per run, held to resolution — no re-entry
    while open, no early exit / mark-to-market (CONTEXT.md).
  * Only outcomes with a known `resolves_at` AND a stored `resolved_value`
    are replayed: hold-to-resolution PnL is unknowable without both. This
    conditions the *universe* on eventual resolution (standard backtest
    practice — you can only score resolved markets); it never leaks the
    resolution's value into any entry decision. Skips are counted.
  * Engine day-roll bookkeeping (daily loss limit / kill switch) runs on
    wall-clock UTC days, not replay time: an entire replay normally falls in
    one wall "day", so `daily_loss_limit` effectively bounds cumulative loss
    across the whole run — conservative (trips earlier), never permissive.
  * Exposure release at settlement is done here (`open_exposure -= notional`)
    because `Engine.settle` predates directional positions and only does
    PnL/kill accounting; modifying it is outside WP-4's boundary ("only add
    execute_signal").

Fee note (architect ruling 2026-07-18, plan.md WP-4): every Kalshi fee uses
KALSHI_COEF_DEFAULT (0.07) — `find_signal`/`ev_per_share` have no
`index_market` seam and this module must not add one. 0.07 is the higher
coefficient, so edge is understated: the safe direction for a GO/KILL call.

Demo: `python3 src/backtest.py` needs a real Postgres reachable via
$DATABASE_URL (see README -> "Database setup") — it seeds a tiny synthetic
market and replays it. Prints a clear message and exits 0 if none is
reachable, matching store.py's convention. Network is never touched.
"""
from __future__ import annotations
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from psycopg import Connection

import store
from ev_detector import find_signal
from fees import Leg
from prob_fn import MarketRef, NoPriorDataError
from risk_execution import Engine, RiskLimits


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SettledPosition:
    """One hold-to-resolution position, realized. Mirrors a backtest_result
    row so the acceptance reconciliation (summary total == DB sum) is a
    straight comparison."""
    token_id: str
    entry_as_of: datetime
    entry_price: float
    size: float
    resolved_value: float
    fee_paid: float
    realized_pnl: float


@dataclass(frozen=True)
class BacktestSummary:
    run_id: str
    prob_fn_name: str
    category: str
    window_start: datetime
    window_end: datetime
    step: timedelta
    steps_run: int
    outcomes_considered: int      # tradable candidates that entered the replay
    entries_filled: int
    entries_rejected: int         # engine gate rejections (caps / kill switch)
    skipped: dict[str, int]       # reason -> count (see run_backtest body)
    settled: tuple[SettledPosition, ...]
    total_fee_paid: float
    total_realized_pnl: float     # == sum(p.realized_pnl for p in settled)
    kill_tripped: bool            # kill switch state when the run finished


# ---------------------------------------------------------------------------
# internal replay records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Candidate:
    ref: MarketRef                # what prob_fn may see — nothing time-forward
    resolves_at: datetime         # settlement anchor (market.resolves_at)
    resolved_value: float         # used ONLY at settlement, never at entry


@dataclass(frozen=True)
class _OpenPosition:
    token_id: str
    entry_as_of: datetime
    entry_price: float
    size: float
    fee_paid: float
    notional: float
    resolves_at: datetime
    resolved_value: float


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None:
        raise ValueError(
            f"{name} must be timezone-aware, got naive datetime {dt!r} — a "
            f"naive value silently shifts the PIT boundary (ADR-0009)")


def _require_finite_positive(value: float, name: str) -> None:
    """A NaN silently defeats every numeric guard downstream (NaN comparisons
    are always False in Python: `nan <= 0` and `nan > cap` both read as "no
    problem here"), so `size_step`/`max_size` alone were not enough — the
    identical path is reachable via `book_depth`, `bankroll`, or
    `kelly_fraction` (QA/reviewer round 2). `not (value > 0)` catches NaN
    (which fails every comparison) in the same branch as `<= 0`, so one
    check covers both."""
    if not (value > 0) or math.isinf(value):
        raise ValueError(f"{name} must be a finite number > 0, got {value!r}")


def _require_finite(value: float, name: str) -> None:
    """`min_ev` legitimately may be zero or negative (e.g. a deliberate
    stress test of the EV cutoff), so it gets a finiteness-only check, not
    the positivity `_require_finite_positive` enforces elsewhere."""
    if value != value or math.isinf(value):     # value != value catches NaN
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def _load_candidates(conn: Connection, *, venue: str,
                     category: str) -> list[tuple[MarketRef, datetime | None, float | None]]:
    """Every outcome of every market in (venue, category), with the two
    settlement fields. Dimension data only — no prices, no orderbooks."""
    rows = conn.execute(
        """
        SELECT m.external_id, m.resolves_at, o.label, o.resolved_value, ot.token_id
        FROM market m
        JOIN outcome o        ON o.market_id  = m.market_id
        JOIN outcome_token ot ON ot.outcome_id = o.outcome_id
        WHERE m.venue = %s AND m.category = %s
        ORDER BY m.external_id, o.idx
        """,
        (venue, category),
    ).fetchall()
    out = []
    for external_id, resolves_at, label, resolved_value, token_id in rows:
        ref = MarketRef(
            external_id=external_id, venue=venue, category=category,
            outcome_token_id=token_id, outcome_label=label,
            resolves_at=resolves_at,
            params={})   # structured resolution params are WP-8's concern
        out.append((ref, resolves_at,
                    float(resolved_value) if resolved_value is not None else None))
    return out


# ---------------------------------------------------------------------------
# the harness
# ---------------------------------------------------------------------------
def run_backtest(conn: Connection, prob_fn, *, category: str,
                 start: datetime, end: datetime, step: timedelta,
                 limits: RiskLimits, run_id: str,
                 venue: str = "kalshi",
                 bankroll: float = 1_000.0,
                 min_ev: float = 0.02,
                 kelly_fraction: float = 0.25,
                 size_step: float = 10.0,
                 max_size: float = 5_000.0,
                 book_depth: float = 1_000.0,
                 git_sha: str | None = None) -> BacktestSummary:
    """Replay [start, end) in `step` increments against every tradable
    outcome in (venue, category), through the paper Engine under `limits`.

    `prob_fn` is an ADR-0009 ProbFn: `p = prob_fn(MarketRef, as_of)`, with a
    stable `.name`. It may raise `NoPriorDataError` to decline a step (no
    data strictly before as_of); that skips the outcome for the step rather
    than fabricating a probability. Any other exception propagates — a
    broken model must fail the run loudly, not be absorbed.

    Signals are persisted at decision time (directional_signal) whether or
    not the Engine accepts them — a rejection is part of the audit trail,
    recorded in the Engine blotter with its reason. Results
    (backtest_result) are written only for filled, settled positions.
    """
    _require_aware(start, "start")
    _require_aware(end, "end")
    if start >= end:
        raise ValueError(f"start {start!r} must be before end {end!r}")
    if step <= timedelta(0):
        raise ValueError(f"step must be a positive timedelta, got {step!r}")
    # Every numeric sizing/fee input gets the same finite+positive guard: a
    # NaN in ANY of these reaches ev_detector.find_signal or Engine._check
    # and silently defeats a comparison meant to reject it (reviewer round
    # 2 — book_depth=nan reproduces the exact same permanent
    # open_exposure-poisoning the size_step fix was written to close;
    # bankroll/kelly_fraction=nan separately defeats the Kelly cap because
    # min(max_size, nan) == max_size, not nan). min_ev is the one exception:
    # it may legitimately be <= 0, so it only needs finiteness.
    _require_finite_positive(book_depth, "book_depth")
    _require_finite_positive(bankroll, "bankroll")
    _require_finite_positive(kelly_fraction, "kelly_fraction")
    _require_finite_positive(size_step, "size_step")
    _require_finite_positive(max_size, "max_size")
    _require_finite(min_ev, "min_ev")

    prob_fn_name = getattr(prob_fn, "name", type(prob_fn).__name__)
    params = {"venue": venue, "bankroll": bankroll, "min_ev": min_ev,
              "kelly_fraction": kelly_fraction, "size_step": size_step,
              "max_size": max_size, "book_depth": book_depth,
              "limits": asdict(limits)}
    # The run row must exist before any write_signal: directional_signal
    # copies prob_fn_name from it (store.py contract).
    store.write_backtest_run(conn, run_id, prob_fn_name, category,
                             start, end, str(step), params=params,
                             git_sha=git_sha)

    engine = Engine(limits, mode="paper")
    skipped: dict[str, int] = {}

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    # Partition the universe once: replay only outcomes whose PnL is
    # realizable (known resolves_at + stored resolved_value) and whose
    # resolution falls after the window opens.
    candidates: list[_Candidate] = []
    for ref, resolves_at, resolved_value in _load_candidates(
            conn, venue=venue, category=category):
        if resolves_at is None or resolved_value is None:
            _skip("unresolvable")
            continue
        if resolves_at <= start:
            _skip("resolved_before_window")
            continue
        candidates.append(_Candidate(ref, resolves_at, resolved_value))

    open_positions: dict[str, _OpenPosition] = {}
    settled: list[SettledPosition] = []
    entries_filled = entries_rejected = steps_run = 0

    def _settle_due(as_of: datetime) -> None:
        """Settle every open position whose resolution time has arrived, in
        resolution order — before any same-step entries, so freed exposure
        and a freshly tripped kill switch are both current."""
        due = sorted((p for p in open_positions.values()
                      if p.resolves_at <= as_of),
                     key=lambda p: p.resolves_at)
        for pos in due:
            pnl = pos.size * (pos.resolved_value - pos.entry_price) - pos.fee_paid
            engine.settle(pnl)
            # Exposure release lives here, not in Engine.settle — see module
            # docstring (WP-4 boundary: settle() is unmodifiable).
            engine.state.open_exposure = max(
                0.0, engine.state.open_exposure - pos.notional)
            store.write_backtest_result(
                conn, run_id, pos.token_id, pos.entry_as_of, pos.entry_price,
                pos.size, pos.resolved_value, pos.fee_paid, pnl)
            settled.append(SettledPosition(
                pos.token_id, pos.entry_as_of, pos.entry_price, pos.size,
                pos.resolved_value, pos.fee_paid, pnl))
            del open_positions[pos.token_id]

    as_of = start
    while as_of < end:
        steps_run += 1
        _settle_due(as_of)

        for cand in candidates:
            token = cand.ref.outcome_token_id
            if token in open_positions:
                continue                        # hold-to-resolution: no re-entry
            if as_of >= cand.resolves_at:
                continue                        # no longer tradable at as_of

            candles = store.candles_before(conn, token, as_of)   # PIT in SQL
            if not candles:
                _skip("no_candle")
                continue
            price = max(candles, key=lambda c: c.ts).close
            if not 0.0 < price < 1.0:
                # A book pinned at 0/1 is untradable (and kelly_shares would
                # divide by zero at 0). Common right before resolution.
                _skip("boundary_price")
                continue

            try:
                p = prob_fn(cand.ref, as_of)
            except NoPriorDataError:
                _skip("no_prior_model_data")
                continue
            if p != p:  # NaN is the only float that is != itself
                raise ValueError(
                    f"prob_fn {prob_fn_name!r} returned NaN for "
                    f"{cand.ref.outcome_token_id!r} at as_of={as_of!r}")
            if not 0.0 <= p <= 1.0:
                raise ValueError(
                    f"prob_fn {prob_fn_name!r} returned p={p!r} outside [0,1] for "
                    f"{cand.ref.outcome_token_id!r} at as_of={as_of!r}")
            if not 0.0 < p < 1.0:
                # p is exactly 0.0 or 1.0 here (already range-checked above) -- a
                # clamped boundary output (e.g. MidpriceProbFn on a 0.00 close) is
                # "market decided", not a tradable edge or a bug.
                _skip("boundary_p")
                continue

            sig = find_signal(
                token, [(price, book_depth)], venue=venue, category=category,
                prob_fn=lambda _tok, _p=p: _p,     # ADR-0009 Option 2 binding
                bankroll=bankroll, min_ev=min_ev,
                kelly_fraction=kelly_fraction, step=size_step,
                max_size=max_size)
            if sig is None:
                _skip("no_edge")                 # the common, honest case
                continue

            store.write_signal(conn, run_id, sig, as_of)   # decision-time audit
            result = engine.execute_signal(sig, category=category)
            if result["status"] != "filled":
                entries_rejected += 1
                continue
            fee_paid = Leg(venue, sig.size, sig.price, category).fee()
            open_positions[token] = _OpenPosition(
                token_id=token, entry_as_of=as_of, entry_price=sig.price,
                size=sig.size, fee_paid=fee_paid,
                notional=sig.price * sig.size,
                resolves_at=cand.resolves_at,
                resolved_value=cand.resolved_value)
            entries_filled += 1

        as_of += step

    # Hold-to-resolution: positions still open at window end settle at their
    # own resolves_at (which every candidate has, by construction). This is
    # what makes total PnL reconcile to the per-signal sum (US-5 acceptance).
    if open_positions:
        _settle_due(max(p.resolves_at for p in open_positions.values()))
    if open_positions:
        raise RuntimeError(
            f"every entered position must settle by end of run_backtest; "
            f"still open: {sorted(open_positions)}")

    return BacktestSummary(
        run_id=run_id, prob_fn_name=prob_fn_name, category=category,
        window_start=start, window_end=end, step=step, steps_run=steps_run,
        outcomes_considered=len(candidates),
        entries_filled=entries_filled, entries_rejected=entries_rejected,
        skipped=skipped, settled=tuple(settled),
        total_fee_paid=sum(p.fee_paid for p in settled),
        total_realized_pnl=sum(p.realized_pnl for p in settled),
        kill_tripped=engine.state.kill)


if __name__ == "__main__":
    from datetime import timezone
    from ingest import MarketRow, OutcomeRef

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print("backtest.py demo needs a real Postgres+TimescaleDB reachable "
              "via $DATABASE_URL (see README -> 'Database setup').")
        print(f"connect() failed: {type(e).__name__}: {e}")
        raise SystemExit(0)

    # seed one synthetic, clearly-demo-named market: YES asked cheap all
    # window, resolves YES -> a model that "knows" p=0.35 finds edge at 0.20.
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    market = MarketRow(
        venue="kalshi", external_id="KXBACKTEST-DEMO",
        question="backtest.py synthetic demo market",
        category="weather", resolution_text="synthetic",
        outcomes=(OutcomeRef("KXBACKTEST-DEMO-YES", "YES", 0),
                  OutcomeRef("KXBACKTEST-DEMO-NO", "NO", 1)),
        resolves_at=t0 + timedelta(hours=6),
    )
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    store.upsert_candles(conn, [
        store.Candle(t0 + timedelta(hours=h), "KXBACKTEST-DEMO-YES",
                     0.20, 0.22, 0.19, 0.20, 100.0)
        for h in range(6)])
    store.apply_resolutions(conn, [
        store.ResolutionRow("KXBACKTEST-DEMO", "KXBACKTEST-DEMO-YES", 1.0),
        store.ResolutionRow("KXBACKTEST-DEMO", "KXBACKTEST-DEMO-NO", 0.0)])

    class _DemoProbFn:
        name = "DemoConstantProbFn"
        def __call__(self, market: MarketRef, as_of: datetime) -> float:
            return 0.35 if market.outcome_label == "YES" else 0.65

    summary = run_backtest(
        conn, _DemoProbFn(), category="weather",
        start=t0 + timedelta(hours=1), end=t0 + timedelta(hours=5),
        step=timedelta(hours=1), limits=RiskLimits(), run_id="demo-run")
    print(f"run={summary.run_id} prob_fn={summary.prob_fn_name} "
          f"steps={summary.steps_run} candidates={summary.outcomes_considered}")
    print(f"filled={summary.entries_filled} rejected={summary.entries_rejected} "
          f"skipped={summary.skipped}")
    print(f"fees=${summary.total_fee_paid:.2f} "
          f"pnl=${summary.total_realized_pnl:+.2f} kill={summary.kill_tripped}")
    conn.close()
