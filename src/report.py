"""
report.py — the fee-aware backtest report + baseline comparison (WP-5, US-6,
ADR-0005/0009).

Answers the one question the MVP exists to answer: *does the model beat
Kalshi's price after fees?* — as a single headline number, model net ROI minus
baseline net ROI. Everything else (hit rate, Brier, Sharpe, drawdown, the
per-market breakdown) is diagnostic colour around that number.

Reads ONLY the stored tables WP-4 populated (`backtest_run`,
`backtest_result`, `directional_signal`, and the `market`/`outcome` dimensions)
— never re-ingests, never re-runs the harness (WP-5 boundary). A report is
therefore reproducible from a database snapshot alone.

Definitions (fixed here, load-bearing — CONTEXT.md is the authority):

  * net PnL   — Σ realized_pnl. `backtest_result.realized_pnl` is already
                post-fee (size*(resolved_value - entry_price) - fee_paid), so
                "net" needs no further fee subtraction.
  * notional  — Σ entry_price × size = cost-to-enter (CONTEXT.md "Notional":
                cost, not payout face value). The ROI denominator.
  * net ROI   — net PnL / notional. A run that never traded has zero notional
                and, by convention, **ROI = 0.0** (no capital deployed → no
                return) rather than NaN — so the headline stays one number.
                This is exactly the MidpriceProbFn baseline's situation: p_model
                = price is -EV after fees, so it never enters, and "beat the
                market" reduces to "the model made a positive net ROI".
  * hit rate  — fraction of settled positions with realized_pnl > 0.
  * Brier     — mean((p_model - resolved_value)²) over the run's persisted
                `directional_signal` rows. NOTE (honest limitation): the harness
                persists a signal only when find_signal returned a positive-EV
                bet, so this is the model's calibration *on the bets it chose to
                make*, a positively-biased subset — not an unconditional
                calibration over all decisions (the no-edge steps are not
                stored, by design). Undefined (None) when the run made no
                signals (e.g. the baseline).
  * Sharpe    — mean(rᵢ)/stdev(rᵢ) over per-position ROI rᵢ = realized_pnlᵢ /
                notionalᵢ, sample stdev (ddof=1). **Per-trade and unannualized**:
                hold-to-resolution bets have heterogeneous horizons, so there is
                no clean periods-per-year to annualize by without inventing one.
                None when < 2 positions or zero dispersion.
  * max drawdown — largest peak-to-trough decline of the cumulative realized-PnL
                curve, positions ordered by resolution time (resolves_at, then
                entry_as_of) — i.e. the order PnL is actually realized in.
                Returned as a non-negative dollar magnitude (0.0 if the curve
                never retraces).

Reconciliation (a report invariant, checked by the tests): the sum of the
per-market net PnL equals the run's net PnL, and net ROI recomputes from the
same net PnL / notional.

Demo: `python3 src/report.py` seeds a tiny model run and a baseline run through
the WP-4 harness (needs a real Postgres via $DATABASE_URL, like store.py /
backtest.py) and prints the report. Prints a message and exits 0 if no DB.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketBreakdown:
    external_id: str
    n_positions: int
    net_pnl: float
    notional: float
    net_roi: float
    hit_rate: float | None


@dataclass(frozen=True)
class RunMetrics:
    run_id: str
    prob_fn_name: str
    category: str
    n_positions: int
    net_pnl: float
    total_fees: float
    notional: float
    net_roi: float
    hit_rate: float | None
    brier: float | None
    sharpe: float | None
    max_drawdown: float
    per_market: tuple[MarketBreakdown, ...]


@dataclass(frozen=True)
class Report:
    model: RunMetrics
    baseline: RunMetrics
    # THE headline (US-6): one number the GO/KILL call reads.
    headline_net_roi_delta: float     # model.net_roi - baseline.net_roi


# ---------------------------------------------------------------------------
# internal: a settled position, dimension-joined, as the report sees it
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Position:
    external_id: str
    entry_as_of: datetime
    resolves_at: datetime | None
    entry_price: float
    size: float
    resolved_value: float
    fee_paid: float
    realized_pnl: float

    @property
    def notional(self) -> float:
        return self.entry_price * self.size


def _roi(net_pnl: float, notional: float) -> float:
    """ROI with the zero-notional convention (see module docstring): no capital
    deployed → 0.0, never a divide-by-zero / NaN. Keeps the headline a number."""
    return net_pnl / notional if notional > 0 else 0.0


def _load_positions(conn: Connection, run_id: str) -> list[_Position]:
    rows = conn.execute(
        """
        SELECT m.external_id, r.entry_as_of, m.resolves_at, r.entry_price,
               r.size, r.resolved_value, r.fee_paid, r.realized_pnl
        FROM backtest_result r
        JOIN outcome o ON o.outcome_id = r.outcome_id
        JOIN market  m ON m.market_id  = o.market_id
        WHERE r.run_id = %s
        ORDER BY r.entry_as_of, r.id
        """,
        (run_id,),
    ).fetchall()
    return [
        _Position(external_id, entry_as_of, resolves_at, float(entry_price),
                  float(size), float(resolved_value), float(fee_paid),
                  float(realized_pnl))
        for (external_id, entry_as_of, resolves_at, entry_price, size,
             resolved_value, fee_paid, realized_pnl) in rows
    ]


def _brier(conn: Connection, run_id: str) -> float | None:
    """mean((p_model - resolved_value)²) over persisted signals — see the
    docstring's honest-limitation note on the positive-EV bias."""
    rows = conn.execute(
        """
        SELECT s.p_model, o.resolved_value
        FROM directional_signal s
        JOIN outcome o ON o.outcome_id = s.outcome_id
        WHERE s.run_id = %s AND o.resolved_value IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    if not rows:
        return None
    return sum((float(p) - float(rv)) ** 2 for p, rv in rows) / len(rows)


def _sharpe(positions: list[_Position]) -> float | None:
    """Per-trade, unannualized Sharpe over per-position ROI. None for < 2
    positions or zero dispersion (a single point, or all-identical returns,
    has no meaningful risk-adjusted ratio)."""
    rets = [p.realized_pnl / p.notional for p in positions if p.notional > 0]
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)      # sample (ddof=1)
    if var <= 0.0:
        return None
    return mean / math.sqrt(var)


def _max_drawdown(positions: list[_Position]) -> float:
    """Largest peak-to-trough decline of the cumulative realized-PnL curve, in
    resolution order (the order PnL is realized). Non-negative magnitude."""
    ordered = sorted(
        positions,
        key=lambda p: (p.resolves_at or p.entry_as_of, p.entry_as_of))
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for p in ordered:
        cum += p.realized_pnl
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return max_dd


def _hit_rate(positions: list[_Position]) -> float | None:
    if not positions:
        return None
    wins = sum(1 for p in positions if p.realized_pnl > 0)
    return wins / len(positions)


def _per_market(positions: list[_Position]) -> tuple[MarketBreakdown, ...]:
    """Breakdown by market (external_id). schema/001 has no coarser 'market
    type'/series dimension, so the finest stored granularity — the market —
    is the breakdown key; the parts sum back to the run total (reconciliation).
    Ordered by external_id for a stable report."""
    groups: dict[str, list[_Position]] = {}
    for p in positions:
        groups.setdefault(p.external_id, []).append(p)
    out = []
    for external_id in sorted(groups):
        ps = groups[external_id]
        net_pnl = sum(p.realized_pnl for p in ps)
        notional = sum(p.notional for p in ps)
        out.append(MarketBreakdown(
            external_id=external_id, n_positions=len(ps),
            net_pnl=net_pnl, notional=notional,
            net_roi=_roi(net_pnl, notional), hit_rate=_hit_rate(ps)))
    return tuple(out)


def _run_metrics(conn: Connection, run_id: str) -> RunMetrics:
    row = conn.execute(
        "SELECT prob_fn_name, category FROM backtest_run WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(
            f"no backtest_run with run_id={run_id!r} — build_report reads only "
            f"stored runs; run the harness (WP-4) first")
    prob_fn_name, category = row

    positions = _load_positions(conn, run_id)
    # float(...): sum() over an empty generator returns int 0, which would
    # violate the `float` type hints below for a never-trading run (e.g. the
    # baseline) — positions is always non-empty for _per_market's groups, so
    # that helper's sums don't need the same guard.
    net_pnl = float(sum(p.realized_pnl for p in positions))
    total_fees = float(sum(p.fee_paid for p in positions))
    notional = float(sum(p.notional for p in positions))

    return RunMetrics(
        run_id=run_id, prob_fn_name=prob_fn_name, category=category,
        n_positions=len(positions), net_pnl=net_pnl, total_fees=total_fees,
        notional=notional, net_roi=_roi(net_pnl, notional),
        hit_rate=_hit_rate(positions), brier=_brier(conn, run_id),
        sharpe=_sharpe(positions), max_drawdown=_max_drawdown(positions),
        per_market=_per_market(positions))


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------
def build_report(conn: Connection, run_id: str,
                 baseline_run_id: str) -> Report:
    """Metrics for the model run and the baseline run over the same window,
    plus the headline model-minus-baseline net-ROI delta (US-6). Both runs must
    already exist in `backtest_run` (WP-4). Reproducible from stored tables
    alone — no re-ingest, no re-run.

    The plan writes the first argument as `store`; the codebase passes the
    open `psycopg` connection everywhere (store.py, backtest.py), so this does
    too — the "store" is that connection."""
    model = _run_metrics(conn, run_id)
    baseline = _run_metrics(conn, baseline_run_id)
    return Report(
        model=model, baseline=baseline,
        headline_net_roi_delta=model.net_roi - baseline.net_roi)


def format_report(report: Report) -> str:
    """A compact plain-text rendering for the CLI demo / logs (no UI — WP-5
    boundary)."""
    def _fmt(m: RunMetrics) -> list[str]:
        def opt(x, spec):
            return format(x, spec) if x is not None else "n/a"
        lines = [
            f"  run_id       : {m.run_id}",
            f"  prob_fn      : {m.prob_fn_name}   category: {m.category}",
            f"  positions    : {m.n_positions}",
            f"  net PnL      : ${m.net_pnl:+.2f}   fees: ${m.total_fees:.2f}",
            f"  notional     : ${m.notional:.2f}",
            f"  net ROI      : {m.net_roi:+.4f}",
            f"  hit rate     : {opt(m.hit_rate, '.3f')}",
            f"  Brier        : {opt(m.brier, '.4f')}",
            f"  Sharpe       : {opt(m.sharpe, '.3f')} (per-trade, unannualized)",
            f"  max drawdown : ${m.max_drawdown:.2f}",
        ]
        for b in m.per_market:
            lines.append(
                f"    - {b.external_id}: n={b.n_positions} "
                f"pnl=${b.net_pnl:+.2f} roi={b.net_roi:+.4f} "
                f"hit={opt(b.hit_rate, '.3f')}")
        return lines

    out = ["MODEL", *_fmt(report.model), "BASELINE", *_fmt(report.baseline),
           "",
           f"HEADLINE  model net ROI - baseline net ROI = "
           f"{report.headline_net_roi_delta:+.4f}"]
    return "\n".join(out)


if __name__ == "__main__":
    from datetime import timedelta, timezone

    import store
    from backtest import run_backtest
    from ingest import MarketRow, OutcomeRef
    from prob_fn import MarketRef, MidpriceProbFn, StoreReader
    from risk_execution import RiskLimits

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print("report.py demo needs a real Postgres+TimescaleDB reachable via "
              "$DATABASE_URL (see README -> 'Database setup').")
        print(f"connect() failed: {type(e).__name__}: {e}")
        raise SystemExit(0)

    # Seed one synthetic market that resolves YES; a model that "knows" p=0.35
    # finds edge at 0.20, the MidpriceProbFn baseline (p=price) finds none.
    t0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    market = MarketRow(
        venue="kalshi", external_id="KXREPORT-DEMO",
        question="report.py synthetic demo market", category="weather",
        resolution_text="synthetic",
        outcomes=(OutcomeRef("KXREPORT-DEMO-YES", "YES", 0),
                  OutcomeRef("KXREPORT-DEMO-NO", "NO", 1)),
        resolves_at=t0 + timedelta(hours=6))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    store.upsert_candles(conn, [
        store.Candle(t0 + timedelta(hours=h), "KXREPORT-DEMO-YES",
                     0.20, 0.22, 0.19, 0.20, 100.0) for h in range(6)])
    store.apply_resolutions(conn, [
        store.ResolutionRow("KXREPORT-DEMO", "KXREPORT-DEMO-YES", 1.0),
        store.ResolutionRow("KXREPORT-DEMO", "KXREPORT-DEMO-NO", 0.0)])

    class _DemoProbFn:
        name = "DemoConstantProbFn"
        def __call__(self, market: MarketRef, as_of: datetime) -> float:
            return 0.35 if market.outcome_label == "YES" else 0.65

    common = dict(category="weather", start=t0 + timedelta(hours=1),
                  end=t0 + timedelta(hours=5), step=timedelta(hours=1),
                  limits=RiskLimits())
    run_backtest(conn, _DemoProbFn(), run_id="report-demo-model", **common)
    run_backtest(conn, MidpriceProbFn(StoreReader(conn)),
                 run_id="report-demo-baseline", **common)

    report = build_report(conn, "report-demo-model", "report-demo-baseline")
    print(format_report(report))
    conn.close()
