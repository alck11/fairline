"""
scripts/flb1_ladder_decile_study.py — FLB-1's pre-registered gate, run on our
own reachable ladder population.

Resolves the crux ADR-0017 left open: Burgi-Deng-Whelan's regression by
contract structure finds the favorite-longshot bias ABSENT in "Exclusive
Numerical" contracts (mutually-exclusive strike ladders), break-even 116.9c —
but their regression by CATEGORY finds Climate & Weather FAVOURABLE,
break-even 32.2c. Kalshi weather ladders are both at once, and the paper
never reports the interaction. Only our own data can settle it.

This operationalizes the 2026-07-25 research doc's FLB-1 gate (Part 5, item
1) restricted to the population ADR-0016/0018 confirmed reachable (~68-day
settled window, confirmed identical authenticated): partition settled,
traded markets into price deciles by last traded price; for the [0.90, 0.99]
decile, compute post-fee ROI on buying the high-priced side; **GO iff net ROI
>= +1.5% with a family-clustered t-stat >= 2.**

THE LADDER TRAP (ADR-0016), and how this script avoids it. A 12-strike
mutually-exclusive ladder resolves exactly one bucket YES, so "buy NO on
every bucket in a family" nets a small guaranteed loss by construction (the
vig) that has nothing to do with mispricing -- and pseudo-replication (12
correlated buckets from one date counted as 12 independent observations)
inflates significance even when the mean is measured honestly. Two design
choices close both holes:

  1. Every observation is a single (market, side) contract at its own
     traded price -- never a family-wide sweep. This measures calibration
     (does a contract priced P win P-of-the-time?), exactly Burgi-Deng-
     Whelan's own methodology (their eq. 1), not a synthetic ladder-sweep
     strategy.
  2. Before testing, observations landing in the target price band are
     collapsed to ONE mean return per family (event_ticker) -- so 12
     correlated buckets from the same date contribute one data point, not
     twelve. The t-test then runs across family-means, which are the actual
     independent unit here (per Burgi-Deng-Whelan: "negative correlations
     within observations on the same event").

Both YES and NO sides of every market are included, mirroring Burgi-Deng-
Whelan's Table 2 (313,972 = 2 x 156,986): a market's NO price/outcome is
just (1 - P, 1 - result), so this doubles coverage without needing a second
API pull, at the cost the paper itself flags for regressions (pseudo-
doubling) -- irrelevant here since family-clustering already the two sides
of the SAME market are perfectly correlated (if YES wins, NO's mirror loses
by construction) and collapsing to one family-mean absorbs that too.

Two populations, pulled separately so the Exclusive-Numerical-vs-Climate-
and-Weather question can be read directly off the output:

  WEATHER  6 daily temperature ladders (ADR-0016 confirmed ~414 resolved,
           traded each): KXHIGHNY/LAX/CHI/MIA/DEN, KXLOWTBOS.
  ECON     4 numeric-threshold ladders WP-0 also confirmed reachable:
           KXCPIYOY, KXPAYROLLS, KXJOBLESSCLAIMS, KXFEDDECISION. Smaller
           (~184 total) but structurally the same "Exclusive Numerical" shape
           in a DIFFERENT paper category (Economics, break-even 28.8c per
           Table 8) -- if econ ladders test favourable while weather ladders
           don't, the story is "weather is unusually efficient" (consistent
           with WP-7/ADR-0014), not "ladders in general kill the bias."

Read-only, no database -- pulls directly from the live API via KalshiSource.
Reuses fees.py (ADR-0015, verified against Kalshi's primary schedule) for
post-fee ROI at a 100-contract taker fill, matching this project's and the
paper's own convention.

    python3 scripts/flb1_ladder_decile_study.py
    python3 scripts/flb1_ladder_decile_study.py --auth   # KalshiCredentials.from_env()
    python3 scripts/flb1_ladder_decile_study.py --json out.json

ADR-0023 update: this study originally pulled `/markets` (live tier), which
ADR-0016 mistakenly believed was Kalshi's full retrievable history. It is
not -- `/historical/markets` reaches back to Kalshi's 2021 inception (see
ADR-0023). `--historical` repoints `fetch_population` at that endpoint
instead, pulling every season the venue has, not the last ~68 days. Requires
`--auth` (the historical tier was only verified reachable authenticated).
The two endpoints share the same market JSON shape (checked live before
writing this: `last_price_dollars`, `volume_fp`, `result`, `event_ticker`
all present and identically named), so `fetch_population` is reused
unchanged -- only the path and the dropped `status="settled"` filter differ
(the historical tier only ever returns `status="finalized"` markets, checked
live: a 500-market sample of KXHIGHNY was 100% finalized/yes-or-no).

    python3 scripts/flb1_ladder_decile_study.py --auth --historical
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fees import kalshi_fee                               # noqa: E402
from ingest_kalshi import KalshiAPIError, KalshiCredentials, KalshiSource  # noqa: E402

WEATHER_SERIES = ["KXHIGHNY", "KXHIGHLAX", "KXHIGHCHI", "KXHIGHMIA", "KXHIGHDEN", "KXLOWTBOS"]
ECON_SERIES = ["KXCPIYOY", "KXPAYROLLS", "KXJOBLESSCLAIMS", "KXFEDDECISION"]

ORDER_SIZE = 100          # contracts per fill, matching Part 2 / the paper's convention
# gate_test's bucket comparison is half-open [lo, hi) like decile_table's, so
# the upper bound here is set one cent past the pre-registered inclusive edge
# -- prices are whole cents (0.01 steps), so hi=1.00/0.11 include exactly
# 0.99/0.10 without also admitting a price that can't occur (1.00 itself is
# excluded upstream in fetch_population).
GATE_LO, GATE_HI = 0.90, 1.00     # pre-registered inclusive decile [0.90, 0.99]
MIRROR_LO, MIRROR_HI = 0.01, 0.11  # sanity-check range [0.01, 0.10], the longshot side
GATE_ROI = 0.015          # +1.5% net ROI
GATE_T = 2.0
POLITE_SLEEP = 0.25


@dataclass
class Obs:
    family: str      # event_ticker -- the clustering unit
    series: str
    population: str  # 'weather' | 'econ'
    price: float      # this side's traded price, in [0,1]
    win: bool         # did THIS side win


def fetch_population(src: KalshiSource, series_list: list[str], population: str,
                      *, historical: bool = False) -> list[Obs]:
    # `/historical/markets` has no `status` filter (ADR-0023: it only ever
    # returns finalized markets -- checked live) and spans years rather than
    # ~68 days, so MAX_PAGES is raised well past what the live-tier path
    # needs (KXHIGHNY alone is ~8,896 markets / 1000-per-page = 9 pages;
    # 200 gives headroom for series this project hasn't sized yet without
    # looping unboundedly on a genuine pagination bug).
    path = "/historical/markets" if historical else "/markets"
    max_pages = 200 if historical else 40
    obs: list[Obs] = []
    for series in series_list:
        cursor, pages, seen = None, 0, set()
        n_series = 0
        while pages < max_pages:
            pages += 1
            kwargs = {"series_ticker": series, "limit": 1000, "cursor": cursor}
            if not historical:
                kwargs["status"] = "settled"
            page = src._get(path, **kwargs)
            markets = page.get("markets") or []
            for m in markets:
                if m.get("result") not in ("yes", "no"):
                    continue
                if float(m.get("volume_fp") or 0) <= 0:
                    continue          # untraded: no meaningful price (ADR-0016 Q1)
                p_yes = m.get("last_price_dollars")
                if p_yes is None:
                    continue
                p_yes = float(p_yes)
                if not (0.0 < p_yes < 1.0):
                    continue          # 0 or 1 exactly is a degenerate/settled-to-edge quote
                family = m.get("event_ticker") or m["ticker"]
                yes_win = (m["result"] == "yes")
                obs.append(Obs(family, series, population, p_yes, yes_win))
                obs.append(Obs(family, series, population, 1.0 - p_yes, not yes_win))
                n_series += 1
            nxt = page.get("cursor")
            if not nxt or not markets or nxt in seen:
                break
            seen.add(nxt)
            cursor = nxt
            time.sleep(POLITE_SLEEP)
        print(f"  {series:<16} {n_series} resolved+traded markets "
              f"({n_series * 2} YES+NO observations)")
    return obs


def decile_table(obs: list[Obs]) -> list[dict]:
    rows = []
    for lo in [i / 10 for i in range(10)]:
        hi = lo + 0.10
        # prices are strictly in (0,1) by construction (fetch_population
        # drops exact 0/1 quotes), so a half-open [lo, hi) bucket at every
        # step, including the last, never silently drops a 0.99-1.00 price.
        bucket = [o for o in obs if lo <= o.price < hi]
        if not bucket:
            rows.append({"range": f"[{lo:.2f},{hi:.2f})", "n": 0})
            continue
        win_rate = sum(o.win for o in bucket) / len(bucket)
        mean_price = sum(o.price for o in bucket) / len(bucket)
        rows.append({"range": f"[{lo:.2f},{hi:.2f})", "n": len(bucket),
                     "mean_price": mean_price, "win_rate": win_rate,
                     "pre_fee_roi": (win_rate - mean_price) / mean_price})
    return rows


def gate_test(obs: list[Obs], lo: float, hi: float, label: str) -> dict:
    """Family-clustered test on the [lo, hi) price band: collapse every
    family's observations in this band to one mean net-ROI, then t-test
    across family-means (the independence unit ADR-0016/the paper both
    require)."""
    bucket = [o for o in obs if lo <= o.price < hi]
    by_family: dict[str, list[float]] = {}
    for o in bucket:
        fee = kalshi_fee(ORDER_SIZE, o.price) / ORDER_SIZE   # per-contract, taker
        payoff = (1.0 if o.win else 0.0)
        net_roi = (payoff - o.price - fee) / (o.price + fee)
        by_family.setdefault(o.family, []).append(net_roi)

    family_means = [sum(v) / len(v) for v in by_family.values()]
    n_obs, n_fam = len(bucket), len(family_means)
    if n_fam < 2:
        return {"label": label, "n_obs": n_obs, "n_families": n_fam,
               "mean_net_roi": None, "t_stat": None, "verdict": "UNDERPOWERED"}

    mean = sum(family_means) / n_fam
    var = sum((x - mean) ** 2 for x in family_means) / (n_fam - 1)
    se = math.sqrt(var / n_fam) if var > 0 else 0.0
    t_stat = (mean / se) if se > 0 else (math.inf if mean != 0 else 0.0)

    if n_fam < 5:
        verdict = "UNDERPOWERED"
    elif mean >= GATE_ROI and t_stat >= GATE_T:
        verdict = "GO"
    else:
        verdict = "NO-GO"

    return {"label": label, "n_obs": n_obs, "n_families": n_fam,
           "mean_net_roi": mean, "se": se, "t_stat": t_stat, "verdict": verdict}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--historical", action="store_true",
                     help="pull /historical/markets (full venue history, ADR-0023) "
                          "instead of /markets (~68-day live-tier window). Requires --auth.")
    ap.add_argument("--json", help="write the raw result to this path")
    args = ap.parse_args()

    if args.historical and not args.auth:
        print("--historical requires --auth (verified reachable authenticated only)")
        return 1

    credentials = KalshiCredentials.from_env() if args.auth else None
    src = KalshiSource(credentials=credentials)

    tier = "/historical/markets (full history)" if args.historical else "/markets (~68-day live tier)"
    print(f"Population source: {tier}")
    print("Fetching WEATHER ladder population...")
    weather_obs = fetch_population(src, WEATHER_SERIES, "weather", historical=args.historical)
    print("\nFetching ECON ladder population...")
    econ_obs = fetch_population(src, ECON_SERIES, "econ", historical=args.historical)
    all_obs = weather_obs + econ_obs

    report: dict = {"populations": {}, "gates": []}

    for name, obs in (("weather", weather_obs), ("econ", econ_obs), ("combined", all_obs)):
        print(f"\n{'=' * 78}\n{name.upper()} — full price-decile table (pre-fee)\n{'=' * 78}")
        print(f"{'range':<14}{'n':>7}{'mean_px':>10}{'win_rate':>10}{'pre_fee_roi':>13}")
        table = decile_table(obs)
        for r in table:
            if r["n"] == 0:
                print(f"{r['range']:<14}{0:>7}")
                continue
            print(f"{r['range']:<14}{r['n']:>7}{r['mean_price']:>10.3f}"
                  f"{r['win_rate']:>10.3f}{r['pre_fee_roi']:>+13.2%}")
        report["populations"][name] = {"n_obs": len(obs), "decile_table": table}

        gate = gate_test(obs, GATE_LO, GATE_HI, f"{name}: FLB-1 gate [0.90,0.99)")
        mirror = gate_test(obs, MIRROR_LO, MIRROR_HI, f"{name}: mirror check [0.01,0.10)")
        for g in (gate, mirror):
            report["gates"].append(g)
            roi = f"{g['mean_net_roi']:+.2%}" if g["mean_net_roi"] is not None else "—"
            t = f"{g['t_stat']:.2f}" if g["t_stat"] not in (None, math.inf) else (
                "inf" if g["t_stat"] == math.inf else "—")
            print(f"\n{g['label']}")
            print(f"  obs={g['n_obs']}  families={g['n_families']}  "
                  f"net_roi={roi}  t={t}  -> {g['verdict']}")

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"\nraw result -> {args.json}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KalshiAPIError as e:
        print(f"Kalshi API failure: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"--auth failed to load credentials: {e}")
        sys.exit(1)
