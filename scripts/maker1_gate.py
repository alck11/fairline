"""
scripts/maker1_gate.py — runs MAKER-1's pre-registered gate and prints the report.

    python3 scripts/maker1_gate.py --notional 200 --threshold 0.15

The gate, pre-registered in `docs/research/2026-08-02-candidate-sourcing-
weather-longshots-and-crypto-updown.md` §7.1 before any data was collected:

  * **Statistic** — reward yield on a fixed slice of resting notional quoted
    at the best price, computed ex ante from observed book state and Kalshi's
    published scoring formula.
  * **Threshold** — GO iff mean annualised yield >= 15% with t >= 2. The 15%
    must clear Kalshi's ~3.25% APY on the same idle capital by enough to
    absorb an adverse-selection cost nobody can measure without trading.

  * **Clustering unit** — one PROGRAMME-DAY, not one snapshot. At a 60s
    cadence there are up to 1,440 snapshots per programme-day and they are one
    book state observed repeatedly; testing on them would inflate t by roughly
    sqrt(1440) ~ 38x. This is ADR-0029's ladder trap wearing a clock.
  * **Minimum clusters** — 20 EVENT-days across >= 5 distinct UTC days.
    Kalshi runs a separate programme on each of ~10 strikes per event, so
    clustering on the strike would report 50 clusters where there are 5,
    and one sampling pass would clear a 20-cluster bar outright.
  * **Third verdict** — UNDERPOWERED whenever the 95% CI still covers the
    threshold. ADR-0022 and ADR-0027 both produced nulls this project could
    not act on; ADR-0029 is the exemplar of saying so out loud.
  * **Pre-registered kill** — pools under $50/period stop the study outright.

**AMENDED 2026-08-02, before any outcome data was collected.** Two defects in
the pre-registered statistic became visible as soon as the books were measured,
and both inflated the yield. Recording the amendment rather than applying it
quietly, because retuning a pre-registration after seeing results is exactly
what ADR-0022/0027/0029 exist to prevent — the distinction that makes this
legitimate is that book *depth* had been observed and yield *outcomes* had not.

  1. **Notional $2,000 -> $200.** The incentivized KXTEMP strikes carry
     ~2,000-5,000 contracts of resting size and competing scores of 120-1,400.
     $2,000 at $0.44 buys 4,545 contracts, making the modelled position a
     majority of the reward auction (median share 67.9%) while the statistic
     still assumed price-taking. $200 is ~5% of observed depth.
  2. **Naive annualisation -> measured occupancy.** Multiplying a 58-minute
     window by 8,760 assumes capital rolls instantly from one programme into
     the next. The headline is now yield per *occupied* hour, scaled by the
     measured fraction of instants at which a qualifying programme existed.

Together these produced a live median of 37,099% annualised on the unamended
statistic — an absurdity that is itself the evidence the model was wrong.

Two numbers matter and they are not the same number: `n_samples` (every
scored instant, thousands) and `n_clusters` (distinct programme-days, dozens).
Only the second one carries statistical weight.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import store  # noqa: E402
from incentives import (  # noqa: E402
    CENTI_CENTS_PER_DOLLAR,
    DEFAULT_NOTIONAL,
    IncentiveProgram,
    SideBook,
    reward_yield,
    run_gate,
)

#: Below this the pre-registered kill fires: a <$10k bankroll cannot extract a
#: meaningful share of a pool this small at any yield.
MIN_POOL_USD = 50.0


def _day(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def load_samples(conn, *, start, end, series_prefix, notional, per_side_pool):
    """Join snapshots to their programmes and score each instant."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.program_id, p.market_ticker, p.incentive_type, p.start_at,
                   p.end_at, p.period_reward_centicents, p.discount_factor_bps,
                   p.target_size, p.description, p.paid_out,
                   b.ts, b.yes_best, b.yes_total_size, b.yes_score,
                   b.no_best, b.no_total_size, b.no_score
            FROM book_snapshot b
            JOIN incentive_program p USING (program_id)
            WHERE b.ts >= %s AND b.ts < %s
              AND p.market_ticker LIKE %s
            ORDER BY b.ts
            """,
            (start, end, f"{series_prefix}%"),
        )
        rows = cur.fetchall()

    samples, killed = [], []
    for r in rows:
        prog = IncentiveProgram(
            program_id=r[0], market_ticker=r[1], incentive_type=r[2],
            start=r[3], end=r[4], period_reward_centicents=int(r[5]),
            discount_factor_bps=r[6], target_size=float(r[7]) if r[7] is not None else None,
            description=r[8], paid_out=r[9])
        if prog.period_reward_usd < MIN_POOL_USD:
            killed.append(prog.market_ticker)
            continue
        yes = SideBook(best=float(r[11]) if r[11] is not None else None,
                       total_size=float(r[12]), score=float(r[13]))
        no = SideBook(best=float(r[14]) if r[14] is not None else None,
                      total_size=float(r[15]), score=float(r[16]))
        s = reward_yield(prog, yes=yes, no=no, ts=r[10],
                         resting_notional=notional, per_side_pool=per_side_pool)
        if s is not None:
            samples.append(s)
    return samples, killed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=_day, default=_day("2026-08-01"))
    ap.add_argument("--end", type=_day, default=_day("2027-01-01"))
    ap.add_argument("--series", default="KXTEMP")
    ap.add_argument("--notional", type=float, default=DEFAULT_NOTIONAL)
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--min-clusters", type=int, default=20)
    ap.add_argument("--min-days", type=int, default=5,
                    help="distinct UTC days required; concurrent "
                         "events at one instant are not independent")
    ap.add_argument("--interval", type=int, default=60,
                    help="collector cadence in seconds; sets the denominator "
                         "of the occupancy measurement")
    ap.add_argument("--per-side-pool", action="store_true",
                    help="assume Kalshi normalises each side's scores "
                         "separately (optimistic); default pools both sides")
    args = ap.parse_args(argv)

    conn = store.connect()
    samples, killed = load_samples(
        conn, start=args.start, end=args.end, series_prefix=args.series,
        notional=args.notional, per_side_pool=args.per_side_pool)
    conn.close()

    if killed:
        print(f"pre-registered kill: {len(killed)} programme(s) with pools "
              f"under ${MIN_POOL_USD:.0f} excluded")
    if not samples:
        print("no scorable snapshots — has the collector run?")
        return 1

    # Occupancy: the fraction of sampling instants at which a qualifying
    # programme actually existed to rest in. The collector writes nothing on a
    # pass that finds no programmes, so the denominator has to come from the
    # elapsed span and the known cadence rather than from the row count --
    # otherwise every sampled instant trivially has a programme and occupancy
    # is 1.0 by construction, which is the assumption being tested.
    instants = {s.ts for s in samples}
    span = max(instants) - min(instants)
    expected = span.total_seconds() / args.interval + 1
    occupancy = min(1.0, len(instants) / expected) if expected > 0 else 1.0

    res = run_gate(samples, threshold=args.threshold,
                   min_clusters=args.min_clusters, min_days=args.min_days,
                   occupancy=occupancy)

    pools = {s.program_id: s.payout_usd / s.score_share for s in samples
             if s.score_share > 0}
    print(f"\nn_samples          {res.n_samples}   (scored instants)")
    print(f"n_clusters         {res.n_clusters}   (EVENT-days, not strikes)")
    print(f"n_days             {res.n_days}   (distinct UTC days sampled)")
    print(f"programmes         {len({s.program_id for s in samples})}")
    if pools:
        print(f"mean pool          ${sum(pools.values())/len(pools):.2f} "
              f"({CENTI_CENTS_PER_DOLLAR} centi-cents = $1)")
    print(f"\nnotional               ${args.notional:,.0f} resting at best")
    print(f"mean yield / occupied hour  {res.mean_hourly:+.6f}")
    print(f"occupancy                   {res.occupancy:.3f}   "
          f"(fraction of instants with a live programme)")
    print(f"\nmean annualised yield   {res.mean:+.4f}   "
          f"(gate: >= {res.threshold:+.2f})")
    print(f"se                      {res.se:.4f}")
    print(f"t                       {res.t:+.3f}")
    print(f"95% CI                  [{res.ci_lo:+.4f}, {res.ci_hi:+.4f}]")
    print(f"GO-sized effect excluded?  "
          f"{'YES' if res.go_excluded else 'NO'}")
    print(f"\ntarget_size met both sides   {res.target_met_fraction:.1%} "
          f"of snapshots")
    print("  (a reward you cannot qualify for is not a reward)")

    per: dict[str, list[float]] = defaultdict(list)
    for s in samples:
        per[s.program_day].append(s.hourly_yield)
    print(f"\nper-cluster mean yield per occupied hour (worst 10 of {len(per)}):")
    for c, v in sorted(per.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))[:10]:
        print(f"  {c}  {sum(v)/len(v):+.6f}  n={len(v)}")

    print(f"\nVERDICT: {res.verdict}")
    if res.verdict == "UNDERPOWERED":
        if res.n_clusters < res.min_clusters or res.n_days < args.min_days:
            print(f"  {res.n_clusters}/{res.min_clusters} event-day clusters "
                  f"over {res.n_days}/{args.min_days} days — keep collecting")
        else:
            print("  the 95% CI still covers the GO threshold; this is not a "
                  "NO-GO and must not be written up as one (ADR-0022/0027)")
    print("\nNOTE: this yield is GROSS of adverse selection, which cannot be "
          "measured\nwithout resting real orders. The paper Engine assumes "
          "full fills and will\noverstate any maker strategy (2026-07-25 doc "
          "§3.4.5).")
    return 0 if res.verdict == "GO" else 2 if res.verdict == "NO-GO" else 3


if __name__ == "__main__":
    sys.exit(main())
