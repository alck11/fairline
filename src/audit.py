"""
audit.py — the point-in-time leakage audit (WP-5, US-7, ADR-0009/ADR-0003).

The MVP's verdict is only worth acting on if it is not a lookahead artifact.
This module is the mechanical proof. It re-checks, from the stored tables
alone, that every decision the harness recorded drew only on data timestamped
strictly before its own `as_of` — the binding guarantee of ADR-0009, inherited
from ADR-0003's "point-in-time features, no leakage" discipline. A model that
reached around store.py's PIT reader to read a future candle leaves a
directional_signal whose recorded price cannot be reproduced from `< as_of`
data; this audit catches exactly that.

Independence is the point. The audit **re-derives** the point-in-time price
with its own SQL rather than calling `store.candles_before` — the reader whose
correctness it is meant to police. If a bug in the reader ever let a `ts >=
as_of` row through, an audit that trusted the same reader would be blind to it.
So this module owns a second, from-scratch implementation of the `< as_of`
rule and compares the harness's recorded numbers against it (the "verify by a
different route" discipline).

What it checks (both from `directional_signal` / `backtest_result` +
`candlestick`, no re-ingest, no re-run):

  1. PRICE IS POINT-IN-TIME. For every `directional_signal` row, the recorded
     `price` must equal the last candlestick `close` with `ts < as_of`. A
     mismatch means the decision priced off a candle at or after `as_of`
     (lookahead). A signal with NO candle strictly before `as_of` is also a
     violation — its price came from nowhere a PIT decision could have seen.
  2. RESULTS TRACE TO AN AUDITED DECISION. Every `backtest_result` (a filled,
     settled position) must have a matching `directional_signal` at the same
     (run_id, outcome_id, entry_as_of) with an equal `entry_price`. A result
     with no audited decision price behind it is a hole in the trail.

Scope (honest): the harness synthesizes a single-level book `(last close,
book_depth)` (Kalshi exposes no historical depth — ADR-0006), so the VWAP fill
price equals that close and check (1) is exact. If a future harness introduces
multi-level historical books, `price` would be a VWAP over several `< as_of`
levels and this check must widen from "equals the last close" to "reconstructs
from the `< as_of` book". `p_model` leakage is NOT re-derived here — that needs
the model itself (out of WP-5's read-only scope); the price the signal actually
traded against is the mechanically checkable surface, and it is the one that
moves money.

`audit_run` returns an `AuditResult`; `main()` (and `python3 src/audit.py
<run_id>`) exits **non-zero** when any violation is found, so the audit can gate
a backtest's definition-of-done in CI. Reads only stored tables; no network.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

# Prices are stored NUMERIC and compared to a NUMERIC recomputed the same way;
# a tiny tolerance absorbs float<->Decimal round-tripping without masking a
# real (order-of-cents) lookahead divergence.
_PRICE_TOL = 1e-9


@dataclass(frozen=True)
class LeakageViolation:
    kind: str                       # 'price_not_pit' | 'no_prior_candle'
                                    # | 'result_without_signal'
                                    # | 'result_price_mismatch'
    run_id: str
    as_of: datetime
    outcome_token_id: str | None
    recorded_price: float
    pit_price: float | None         # last close < as_of, or None if none exists
    detail: str


@dataclass(frozen=True)
class AuditResult:
    run_id: str
    signals_checked: int
    results_checked: int
    violations: tuple[LeakageViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def _audit_signal_prices(conn: Connection, run_id: str) -> list[LeakageViolation]:
    """Check (1): every directional_signal price reproduces from `< as_of`
    candles. The `pit_close` correlated subquery is this module's own
    from-scratch `ts < as_of` implementation (see docstring) — deliberately not
    store.candles_before."""
    rows = conn.execute(
        """
        SELECT s.as_of, s.price,
               (SELECT ot.token_id
                  FROM outcome_token ot
                 WHERE ot.outcome_id = s.outcome_id
                 ORDER BY ot.token_id
                 LIMIT 1) AS token_id,
               (SELECT c.close
                  FROM candlestick c
                 WHERE c.outcome_id = s.outcome_id
                   AND c.ts < s.as_of
                 ORDER BY c.ts DESC
                 LIMIT 1) AS pit_close
        FROM directional_signal s
        WHERE s.run_id = %s
        ORDER BY s.as_of, s.outcome_id
        """,
        (run_id,),
    ).fetchall()

    violations: list[LeakageViolation] = []
    for as_of, price, token_id, pit_close in rows:
        price = float(price)
        if pit_close is None:
            violations.append(LeakageViolation(
                kind="no_prior_candle", run_id=run_id, as_of=as_of,
                outcome_token_id=token_id, recorded_price=price, pit_price=None,
                detail=(f"signal at as_of={as_of.isoformat()} has no candlestick "
                        f"strictly before as_of — its price {price!r} could not "
                        f"have been derived point-in-time")))
            continue
        pit_close = float(pit_close)
        if abs(price - pit_close) > _PRICE_TOL:
            violations.append(LeakageViolation(
                kind="price_not_pit", run_id=run_id, as_of=as_of,
                outcome_token_id=token_id, recorded_price=price,
                pit_price=pit_close,
                detail=(f"recorded price {price!r} != last close strictly before "
                        f"as_of={as_of.isoformat()} ({pit_close!r}) — the "
                        f"decision drew on a candle at or after as_of "
                        f"(lookahead)")))
    return violations


def _audit_result_traceability(conn: Connection,
                               run_id: str) -> list[LeakageViolation]:
    """Check (2): every settled result traces to a directional_signal at the
    same (outcome, entry_as_of) with an equal entry price."""
    rows = conn.execute(
        """
        SELECT r.entry_as_of, r.entry_price,
               (SELECT ot.token_id
                  FROM outcome_token ot
                 WHERE ot.outcome_id = r.outcome_id
                 ORDER BY ot.token_id
                 LIMIT 1) AS token_id,
               s.price
        FROM backtest_result r
        LEFT JOIN directional_signal s
               ON s.run_id = r.run_id
              AND s.outcome_id = r.outcome_id
              AND s.as_of = r.entry_as_of
        WHERE r.run_id = %s
        ORDER BY r.entry_as_of, r.outcome_id
        """,
        (run_id,),
    ).fetchall()

    violations: list[LeakageViolation] = []
    for entry_as_of, entry_price, token_id, signal_price in rows:
        entry_price = float(entry_price)
        if signal_price is None:
            violations.append(LeakageViolation(
                kind="result_without_signal", run_id=run_id, as_of=entry_as_of,
                outcome_token_id=token_id, recorded_price=entry_price,
                pit_price=None,
                detail=(f"settled result at entry_as_of={entry_as_of.isoformat()} "
                        f"has no matching directional_signal — its entry price "
                        f"was never audited at decision time")))
            continue
        signal_price = float(signal_price)
        if abs(entry_price - signal_price) > _PRICE_TOL:
            violations.append(LeakageViolation(
                kind="result_price_mismatch", run_id=run_id, as_of=entry_as_of,
                outcome_token_id=token_id, recorded_price=entry_price,
                pit_price=signal_price,
                detail=(f"result entry_price {entry_price!r} != its "
                        f"directional_signal price {signal_price!r} at the same "
                        f"as_of — filled price diverged from the audited "
                        f"decision")))
    return violations


def audit_run(conn: Connection, run_id: str) -> AuditResult:
    """Audit one backtest run for point-in-time honesty (US-7). Returns an
    AuditResult; `.ok` is True iff no violation was found. Raises KeyError if
    the run does not exist (auditing a phantom run is a caller error, distinct
    from a clean pass)."""
    exists = conn.execute(
        "SELECT 1 FROM backtest_run WHERE run_id = %s", (run_id,)).fetchone()
    if exists is None:
        raise KeyError(
            f"no backtest_run with run_id={run_id!r} — nothing to audit")

    n_signals = conn.execute(
        "SELECT count(*) FROM directional_signal WHERE run_id = %s",
        (run_id,)).fetchone()[0]
    n_results = conn.execute(
        "SELECT count(*) FROM backtest_result WHERE run_id = %s",
        (run_id,)).fetchone()[0]

    violations = (_audit_signal_prices(conn, run_id)
                  + _audit_result_traceability(conn, run_id))
    return AuditResult(
        run_id=run_id, signals_checked=n_signals, results_checked=n_results,
        violations=tuple(violations))


def format_audit(result: AuditResult) -> str:
    head = (f"audit run_id={result.run_id}: "
            f"{result.signals_checked} signals, {result.results_checked} results "
            f"checked -> {'PASS' if result.ok else 'FAIL'}")
    if result.ok:
        return head + " (no point-in-time violations)"
    lines = [head, f"  {len(result.violations)} violation(s):"]
    for v in result.violations:
        lines.append(f"    [{v.kind}] {v.outcome_token_id}: {v.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. `python3 src/audit.py <run_id>` audits a run and exits
    non-zero on any violation (US-7: the audit gates the backtest's
    definition-of-done). Needs a real Postgres via $DATABASE_URL."""
    import sys

    import store

    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: python3 src/audit.py <run_id>", file=sys.stderr)
        return 2

    run_id = args[0]
    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print("audit.py needs a real Postgres+TimescaleDB reachable via "
              "$DATABASE_URL (see README -> 'Database setup').")
        print(f"connect() failed: {type(e).__name__}: {e}")
        return 2

    try:
        result = audit_run(conn, run_id)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    finally:
        conn.close()

    print(format_audit(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
