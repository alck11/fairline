# ADR-0029 — MRAIN-1 gate result: NO-GO, and this one is powered

- **Status:** Accepted
- **Date:** 2026-08-02
- **Implements the build scoped by** [ADR-0028](0028-mrain1-calibration-study-scoped.md).
  **Closes the candidate reopened by** [ADR-0024](0024-mrain1-power-objection-is-false-reopened.md).
  **Same decision procedure as** [ADR-0012](0012-calibration-edge-room-brier-skill-gate.md) /
  [ADR-0014](0014-wp7-gate-result-no-go-do-not-build-wp8.md).

## Decision

**MRAIN-1 stops. Do not build a monthly-precipitation model.**

Kalshi's monthly rain prices already beat a point-in-time climatological
benchmark, on 92 station-months across 10 cities, by a margin that is
statistically significant *in the wrong direction*. This is not "we failed to
find an edge" — the 95% confidence interval on the Brier gap excludes a
GO-sized effect outright.

MRAIN-1 was the last open research candidate. With this, every candidate this
project has generated is closed. See "What this means for the project" below.

## Result

Real Kalshi markets (both the `KXRAIN*M` and legacy `RAIN*M` prefixes), real
IEM daily precipitation, point-in-time throughout, `--step-hours 24`:

```
loaded 602 resolved rain market(s)

n_samples          16221
brier(price)       0.08048
brier(benchmark)   0.09241
skill              -0.1483   (gate: >= +0.05)

n_clusters         92   (station-months)
mean cluster gap   -0.00989   (brier_price - brier_benchmark)
se                 0.00477
t                  -2.073    two-sided p = 0.041
clusters won       39/92

VERDICT: NO-GO
```

The benchmark is 14.8% *worse* than the price in relative Brier skill.

### The power statement, which is the point of this ADR

ADR-0022 and ADR-0027 both ended in nulls this project could not act on,
because they could not distinguish "no effect" from "not enough data". This
one can:

```
95% CI on the cluster gap    [-0.01936, -0.00041]
gap needed for GO            +0.00402      (5% of brier_price)
GO-sized effect excluded?    YES
one-sided p(true gap >= GO threshold) = 0.0022
```

The interval lies entirely below zero and entirely below the GO threshold. A
benchmark edge large enough to matter is excluded at better than 99%.

For contrast, the same study run on NYC alone — which is where it stood before
the other nine cities were backfilled — was **not** powered:

| | NYC only | all 10 cities |
|---|---|---|
| clusters | 28 | 92 |
| mean gap | -0.00783 | -0.00989 |
| t | -0.696 | -2.073 |
| 95% CI upper | **+0.01526** | **-0.00041** |
| GO threshold | +0.00632 | +0.00402 |
| GO-sized effect excluded? | **no** | **yes** |

Same direction, same magnitude, but at k=28 the interval still covered a
GO-sized edge. Publishing the NYC-only NO-GO would have been a repeat of
ADR-0027's mistake dressed as a conclusion. The nine extra cities are what
turned an undetected effect into an excluded one.

## Why this is trustworthy

**The benchmark works.** A NO-GO produced by a broken benchmark says nothing,
so this was checked first. Against a constant base-rate forecast (Brier
0.23198 at a 0.3658 YES rate), the climatology scores **+60.2% relative
skill**. It is genuinely informative — it simply loses to the price, which
scores +65.3%. A mis-specified benchmark loses by far more than 5 points.

**Every station mapping reproduces Kalshi's own settlements.** This was the
single most expensive place to be wrong, because it fails silently: point a
series at the wrong airport and the benchmark scores against another city's
rain, producing a plausible-looking unearned NO-GO. `scripts/mrain1_settlement_check.py`
recomputes each market's month total from stored IEM data and checks
`total > strike` against what Kalshi actually settled — not a spot-check, every
resolved market in the archive:

```
station  series               reproduced
KAUS     KXRAINAUSM           46/46    100.0%
KDEN     KXRAINDENM           46/46    100.0%
KDFW     KXRAINDALM           50/50    100.0%
KHOU     KXRAINHOUM           46/46    100.0%
KLAX     KXRAINLAXM           50/50    100.0%
KMDW     KXRAINCHIM           50/50    100.0%
KMIA     KXRAINMIAM           46/46    100.0%
KNYC     KXRAINNYCM/RAINNYCM 172/172   100.0%
KSEA     KXRAINSEAM           43/43    100.0%
KSFO     KXRAINSFOM           46/46    100.0%
TOTAL                        595/595   100.0%
```

The three ambiguous ones are all confirmed: Chicago settles on **Midway**, not
O'Hare; Houston on **Hobby**, not Bush; Dallas on **DFW**. Each was a coin-flip
that would not have raised an error if guessed wrong.

**Six sensitivity variants, all NO-GO**, and one is informative rather than
merely confirmatory:

| variant | n_samples | skill | t | verdict |
|---|---|---|---|---|
| baseline (24h) | 16,221 | -0.148 | -2.07 | NO-GO |
| `--step-hours 6` | 66,595 | -0.150 | -2.12 | NO-GO |
| `--step-hours 72` | 5,164 | -0.144 | -2.01 | NO-GO |
| `--min-years 10` | 16,221 | -0.148 | -2.07 | NO-GO |
| `--lookback-days 45` | 16,221 | -0.148 | -2.07 | NO-GO |
| `--lookback-days 21` | 11,940 | **-0.236** | **-2.95** | NO-GO |
| `--margin 0.02` | 16,221 | -0.148 | -2.07 | NO-GO |

The `--lookback-days 21` row is the one that matters. Restricted to the last
three weeks before resolution — where accumulation dominates and the benchmark
knows the *most* — the benchmark does relatively **worse**, not better. The
market sharpens faster than the climatology does as information arrives. That
is evidence against slack for a better model to occupy, not just against this
particular benchmark.

`--min-years 10` and `--lookback-days 45` reproduce the baseline exactly, which
confirms neither filter was binding.

**Eight of ten cities individually agree:**

```
station  clusters   mean gap     won
KAUS            7   +0.00965    3/7
KDEN            7   +0.00163    4/7
KDFW            7   -0.02990    2/7
KHOU            7   -0.02665    1/7
KLAX            7   -0.01248    2/7
KMDW            8   -0.00201    5/8
KMIA            7   -0.00267    4/7
KNYC           28   -0.00783   14/28
KSEA            7   -0.00859    3/7
KSFO            7   -0.02731    1/7
```

Only KAUS and KDEN are positive, both on 7 clusters, both well inside noise.

**Clustering is on station-months, not samples.** A monthly rain ladder is one
weather event priced at ~7 strikes and sampled every few hours; those samples
are near-perfectly dependent. The `--step-hours 6` variant makes this visible:
it quadruples `n_samples` from 16,221 to 66,595 while moving t from -2.07 to
-2.12. Sample count inside a cluster is almost free information. Testing on
`n_samples` would have inflated t by roughly sqrt(samples per cluster) — the
ladder trap ADR-0018/ADR-0025 built family clustering to avoid.

## Known weaknesses, none of which rescue a GO

- **Stale-price carry-forward.** The price at an instant is the last candle
  before it, carried forward indefinitely through illiquid stretches. This
  *penalizes* the price, so it biases toward GO — the NO-GO is conservative
  with respect to it.
- **Two one-day precip gaps** (KSEA 2024-04, KSEA 2025-12). A missing day
  undercounts accumulation and biases those two markets' benchmark toward NO.
  Two station-months out of 92, one day out of ~30 each.
- **Cross-month independence is assumed.** Consecutive months at one station
  share weather regimes, so the effective cluster count is somewhat below 92.
  That would inflate |t|, but t is already the wrong sign for a GO, so it
  cannot manufacture one.
- **This gate tests a climatological benchmark, not every possible model.**
  A QPF-blended forecast could beat climatology. But the market prices QPF
  too, ADR-0014 already found the market absorbs NWS forecasts for
  temperature, and the `--lookback-days 21` result shows the gap *widening*
  as information arrives. Building that model is a different and much larger
  project, and nothing here suggests it would clear the bar.

## What this means for the project

Every research candidate this project has generated is now closed:

| candidate | closed by | reason |
|---|---|---|
| Track B / WP-8 weather model | ADR-0014 | price beats forecast benchmark |
| FLB-1 (favourite-longshot) | ADR-0025 | stable NO-GO on full history |
| FLB-1 "emotional" basket | ADR-0027 | underpowered, 7 families |
| HURSEAS-1 (seasonal hurricane) | ADR-0026 | 4 seasons max, 3 tickers are one event |
| v0.3 econ calibration | ADR-0022 | underpowered |
| MRAIN-1 (monthly rain) | **this ADR** | **powered NO-GO** |

The stack is sound and the discipline works — six candidates killed for a few
days of ingest and analysis each, versus the cost of trading any one of them.
What the pipeline has not produced is a candidate that survives. That is a
finding about the candidate-generation process, not about the machinery, and
the next decision is a sourcing decision rather than an engineering one.

Explicitly **not** decided here: whether to keep looking, and where. This ADR
records only that MRAIN-1 is closed and why the closure is trustworthy.

## Artifacts

- `src/climatology.py` — the PIT climatological residual benchmark
- `src/rain_calibration.py` — spec parsing, `_StationHistory`, `_TokenCandles`, `evaluate`
- `scripts/mrain1_gate.py` — the clustered gate runner
- `scripts/mrain1_settlement_check.py` — the mapping/settlement verifier
- `tests/test_climatology.py` (18 tests), `tests/test_rain_calibration.py` (18 tests)

Data in the store at time of decision: 602 resolved rain markets across 10
series, 10 stations x ~6,390 daily precipitation observations (2009-01-02 ..
2026-07-03).
