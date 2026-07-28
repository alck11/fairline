# ADR-0019 — FLB-1's own gate, run on our data: a real, rock-solid, too-small edge — NO-GO, and it resolves ADR-0017's crux

- **Status:** Accepted — **data premise corrected 2026-07-28 by [ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md)**: this study ran on 68 days / 2,411 live-tier markets. `KXHIGHNY` alone has 8,896 markets across 5 years via `/historical/markets`, with real traded prices confirmed. The methodology and the +0.88%-vs-1.5% NO-GO stand as a measurement on the sample used; re-running against the full historical population would sharpen it and is now possible without forward-paper.
- **Date:** 2026-07-28
- **Resolves:** [ADR-0017](0017-flb1-gate-bias-is-real-but-not-in-reachable-markets.md)'s
  open crux — does Kalshi weather ladders behave like Bürgi-Deng-Whelan's
  "Exclusive Numerical" cut (break-even 116.9c, unprofitable everywhere) or
  their "Climate & Weather" cut (break-even 32.2c, favourable)? — and the last
  open item from both ADR-0016 and ADR-0017.
- **Tool:** `scripts/flb1_ladder_decile_study.py`.

## Decision

**NO-GO on FLB-1's own pre-registered gate. But not for the reason either
prior document guessed.** The bias is real on our own weather-ladder data,
survives fees, and is statistically overwhelming — not underpowered, not
noise. It is simply **too small**: **+0.88% net-of-fee ROI** in the
[0.90, 0.99] price band against a **+1.5%** pre-registered bar, with a
family-clustered **t = 9.41** on 402 independent dates. The magnitude, not the
existence, of the edge is what kills it.

This resolves ADR-0017's crux in favour of **Climate & Weather**, not
**Exclusive Numerical**: our data shows a real positive edge, which the
Exclusive-Numerical cut (break-even 116.9c, i.e. loses money at every price)
could not produce. It is smaller than Table 8's implied Climate & Weather
figure (+2.09% pre-fee at this price, vs. our measured +0.95% pre-fee) — a
real, moderate gap, discussed below — but the *sign* and *statistical
robustness* land decisively on the favourable side.

## Method — how the ladder trap was avoided, concretely

Per ADR-0016's warning and Bürgi-Deng-Whelan's own methodology (their eq. 1,
and their event-level clustering): every observation is one **(market, side)
contract at its own traded price** — never a family-wide NO-sweep. Both the
YES contract (price P, win = result==yes) and its mirrored NO contract
(price 1−P, win = result==no) are included per market, exactly mirroring the
paper's Table 2 (313,972 = 2 × 156,986). Before testing, observations in the
target price band are **collapsed to one mean net-ROI per family**
(`event_ticker` — one date's full ladder) and the t-test runs across those
402 family-means, not the underlying 2,407 (market, side) observations.

**The correction was measured, not assumed.** Recomputed both ways on the
identical bucket: naive pooled t (pseudo-replicated, ignoring that ~6
observations per family come from the same date) was **11.97**; the correct
family-clustered t was **9.41** — a real but modest 1.27× inflation. Small
here because within-family variance happens to be low, not because clustering
didn't matter; the point was to check, not to assert.

## Population and result

Six daily-ladder series confirmed reachable and traded in
[ADR-0016](0016-wp0-history-ceiling-is-a-venue-property.md):
KXHIGHNY/LAX/CHI/MIA/DEN, KXLOWTBOS. ~402 resolved+traded markets each (2,411
markets, 4,822 YES+NO observations), pulled live via the RSA-PSS-authenticated
`KalshiSource` from [ADR-0018](0018-authenticated-access-confirms-the-history-ceiling.md)
(doesn't matter which — ADR-0018 already showed auth changes nothing, used it
for convenience/consistency).

**Full weather decile table** (pre-fee, before clustering — context only, the
gate test below is the actual verdict):

| price range | n | mean price | win rate | pre-fee ROI |
|---|---|---|---|---|
| [0.00, 0.10) | 2,406 | 0.011 | 0.001 | −88.25% |
| [0.10, 0.30) | 6 | ~0.13 | 0.00 | −100% |
| [0.70, 0.90) | 5 | ~0.85 | 1.00 | +14–33% (n too small to trust) |
| **[0.90, 1.00)** | **2,407** | **0.989** | **0.999** | **+0.95%** |

**The pre-registered gate**, family-clustered, taker fee (100-contract fill,
`fees.py`, ADR-0015):

| | n obs | n families | net ROI | t-stat | verdict |
|---|---|---|---|---|---|
| **FLB-1 gate [0.90, 0.99]** | 2,407 | 402 | **+0.88%** | **9.41** | **NO-GO** (< 1.5% bar) |
| Mirror check [0.01, 0.10] | 2,407 | 402 | **−90.31%** | −11.31 | (expected direction, confirms the data isn't broken) |

The mirror check is a sanity check, not a second gate: longshots losing ~90%
of their value is the textbook favorite-longshot pattern and matches the
paper's own qualitative finding (*"average loss rates for contracts costing
10c and under are over 60%"* — ours is more extreme, consistent with WP-7's
finding that this specific market is unusually well-calibrated).

**Per-series breakdown — the result is not one series carrying the average:**

| series | n families | mean price | net ROI | t (clustered) |
|---|---|---|---|---|
| KXHIGHNY | 67 | 0.990 | +0.96% | 63.5 |
| KXHIGHLAX | 67 | 0.990 | +0.95% | 177.5 |
| KXHIGHCHI | 67 | 0.990 | +0.96% | 53.4 |
| KXHIGHMIA | 67 | 0.990 | +0.97% | 44.5 |
| KXHIGHDEN | 67 | 0.989 | +1.01% | 22.6 |
| KXLOWTBOS | 67 | 0.988 | +0.43% | 0.77 |

Five of six cities converge tightly on **~0.95–1.0%**, each individually
significant at t≥22. `KXLOWTBOS` is the outlier — smaller edge, not
significant on its own (t=0.77) — consistent with it being the thinnest
market in this set (2026-07-25 doc: 6/12 strikes quoted vs 8–11/12
elsewhere). **The combined estimate's t=9.41 is lower than any individual
city's t** because pooling six series adds genuine between-series
heterogeneity (KXLOWTBOS pulling the mean down) on top of within-series
noise — exactly what family-clustering is supposed to capture, and a second
confirmation the statistics aren't being gamed upward.

**Econ ladders are inconclusive, not negative.** KXCPIYOY/KXPAYROLLS/
KXJOBLESSCLAIMS/KXFEDDECISION gave only **14 resolved families** at the gate
price band (t = −0.47, indistinguishable from zero) and 14 at the mirror
(t = 0.62, wrong sign but equally indistinguishable from zero). This is a
small-sample null, not evidence the bias is absent in econ — WP-0 already
established these series have far fewer retrievable resolved markets than
weather (184 vs 2,411 total). Do not read "econ is different from weather"
into this; the honest read is "econ cannot be tested with what's
retrievable."

## Why the gap to the paper's implied number, and why it doesn't change the verdict

Evaluating Table 8's Climate & Weather regression (α=−0.997, ψ=0.031) at our
population's mean price (0.989) gives a pre-fee profit of **+2.07%** — our
measured **+0.95%** pre-fee is real but roughly half that. Two honest
readings, not resolved here: the paper's Climate & Weather category (29,924
observations, all Kalshi weather products since 2021) is broader than six
daily-temperature series measured over ~68 days in 2026, so a different mix
of stations/products/eras could produce a different average; or the market
has become more efficient since the paper's April 2025 cutoff, consistent
with Table 9's own by-year coefficient weakening into 2025. Either way, **our
own directly-measured number is the one that should drive the GO/NO-GO
decision, not the paper's**, and it says NO-GO regardless of which reading is
right.

## A limitation that matters more than the gap above, flagged plainly

**This study uses each market's `last_price_dollars` — the last trade before
settlement, whenever that occurred — not a fixed-lead-time, point-in-time
snapshot.** Nothing enforces a minimum interval before `close_time`. If the
~1% edge is concentrated in the market's final minutes — after the day's
actual high temperature is essentially locked in and most uncertainty has
already resolved — then it may describe how *calibrated the closing quote is*
(a legitimate finding, and exactly what Bürgi-Deng-Whelan's own methodology
measures) without describing an edge a trader could actually **capture**,
for the same reason ADR-0014 found no tradeable window for a forecast-based
model: the market may absorb the information before there is room to trade on
it at size.

This is not a reason to distrust the sign or the statistical result — it is a
reason the **already-failing** economic magnitude (0.88% vs a 1.5% bar) should
be read as an **upper bound** on what's practically capturable, not a lower
bound. A stricter version of this study, using this project's existing
point-in-time infrastructure (`store.py`'s `< as_of` discipline, the same one
`audit.py` enforces on the backtest) with a snapshot fixed at some real lead
time (e.g. 6h or 24h before close), would very likely show an equal or
*smaller* edge, never a larger one. That version was not built here — this
ADR's verdict does not depend on it, since the already-measured number misses
the gate, but it is the honest next check if anyone revisits this later.

## What this settles

- **FLB-1 is finished on the currently reachable population.** Not
  underpowered (t=9.4, n=402, is about as unambiguous as a result gets in
  this project), not absent (the effect is real, consistently signed and
  sized across five of six cities), but too small against its own
  pre-registered bar, before even reaching the further frictions ADR-0017
  already flagged (adverse selection, non-fills, correlation within a
  weather season, and Kalshi's ~3.25% APY on the same idle capital).
- **ADR-0017's crux is resolved:** our data behaves like the paper's
  Climate & Weather cut (favourable, small positive edge), not its Exclusive
  Numerical cut (unprofitable everywhere) — the ladder structure alone does
  not kill the bias; weather-market efficiency dominates and caps it small.
- **This was the last open item.** Every backtest-shaped candidate from the
  2026-07-25 research doc is now resolved: HURSEAS-1/DROUGHT-1 dead (no
  data), MRAIN-1 underpowered (no data), FLB-1 tested directly and NO-GO (real
  but sub-gate edge). The fork ADR-0016 identified — forward paper (6–12
  months to a verdict) or stop — is the only decision left, and it is the
  user's to make, not a work package.
