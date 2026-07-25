# ADR-0014 — WP-7 gate result: NO-GO on Track B; do not build WP-8

- **Status:** Accepted
- **Date:** 2026-07-25
- **Supersedes:** nothing. **Implements the decision procedure of** [ADR-0012](0012-calibration-edge-room-brier-skill-gate.md).

## Decision

**Track B stops. Do not build WP-8 (the weather model) as currently scoped.**

The pre-registered gate in ADR-0012 asked one question: does Kalshi's weather
price already track the public forecast, or is there room for a forecast-based
model to beat it? Run against real data, the answer is that the price is
*more* accurate than the forecast benchmark on every market type. There is no
edge room for the model to occupy.

This is the capital-saving outcome ADR-0012 was written to make possible. It
cost roughly a day of ingest and analysis instead of a model build.

## Result

Real Kalshi `KXHIGHNY` markets and real IEM `KNYC` forecasts/observations,
point-in-time honest throughout, `--step-hours 6`:

```
markets studied: 408   samples: 2442      (2026-05-17 .. 2026-07-23, 68 dates)

  market type                n  Brier(px)  Brier(fc)    skill     gap  verdict
  --------------------------------------------------------------------------
  weather:tmax:between    1628     0.0954     0.1369   -43.6%   0.136  NO-GO
  weather:tmax:greater     407     0.0175     0.0364  -107.8%   0.058  NO-GO
  weather:tmax:less        407     0.0862     0.1466   -70.1%   0.160  NO-GO

OVERALL: NO-GO
```

Skill is *negative* on all three types — the benchmark is not merely failing to
clear the 5% margin, it is losing outright. The three types are computed over
disjoint sample sets and agree.

## Why this is trustworthy

- **It is not a small-sample artifact.** A preliminary run over the most recent
  15 days (78 markets / 462 samples) reached the same verdict independently.
  Widening to 68 days and 5.3x the samples did not change the direction on any
  type:

  | type | 15-day skill | 68-day skill |
  |---|---|---|
  | between | -36.2% | -43.6% |
  | greater | -296.6% | **-107.8%** |
  | less | -44.0% | -70.1% |

  The one figure that moved materially, `greater`, moved the way a
  small-denominator artifact should: at 15 days `Brier(px)` was 0.0004, so
  *relative* skill exploded. With a real sample it settles near -108%.

- **The benchmark is working, not broken.** A degenerate benchmark (constant
  0.5) would score `Brier(fc)` ≈ 0.25. Observed values are 0.036–0.147, and the
  mean price/benchmark gap is 0.058–0.160 — the Gaussian is making real,
  reasonably good, genuinely different predictions. It is simply beaten.

- **The data is internally coherent.** 408 resolved markets across exactly 68
  target dates, 6 mutually exclusive strike buckets per date (4 `between`, 1
  `less`, 1 `greater`), and a resolved-YES fraction of **0.167 ≈ 1/6** — which
  is what must hold if exactly one bucket per date settles YES. The
  resolutions applied correctly.

- **PIT integrity held.** Every read went through the `< as_of` readers,
  including the `exclude_date` fix that stops a market's own realised outcome
  leaking into the Gaussian used to price it (ADR-0013).

## What this does NOT establish

State plainly, because a NO-GO invites over-reading:

- **It is one series, one station, one season.** `KXHIGHNY` / `KNYC`, summer
  2026. Cold-season markets, or stations with larger forecast error, are
  untested. `SERIES_STATION` maps only this one pair today.
- **68 days is a venue ceiling, not a choice.** Kalshi serves nested market
  data for ~68 rolling days per series; the 1,171 older `HIGHNY-` events
  return no markets and are not retrievable. This window cannot be extended
  backwards from the API.
- **The benchmark is a deliberate lower bound.** ADR-0012 chose a non-trained
  Gaussian over a station-level error distribution, mixing all forecast leads
  into one σ. A properly lead-stratified or multi-model approach could see edge
  this cannot. A NO-GO here says *this crude benchmark finds no room*, not
  *no model could ever win*.
- **Fee-free by construction.** Edge *room*, not net profitability. A GO here
  would still have had to survive fees and slippage in WP-4/WP-5.

## Follow-up test (2026-07-25): lead-stratified benchmark — tested, NO-GO holds

The revisit condition below listed "a lead-stratified error model" as the
cheapest way to reopen this. It was tested the same day
(`scripts/lead_stratified_study.py`) and **does not reopen it.** The result is
worth recording in full, because *why* it fails is more informative than the
verdict.

**The motivating defect is real.** ADR-0012's `_error_stats` estimates σ from
past dates, where "the latest cycle before `as_of`" is always a final ~16h-lead
nowcast — then applies that σ to price a market whose forecast may be days out.
On this station's data the spread more than doubles across that range:

| lead | n | bias | σ |
|---|---|---|---|
| 12–24h | 83 | -0.45 | 2.45 |
| 36–48h | 82 | -0.67 | 2.84 |
| 48–72h | 81 | -0.80 | 3.25 |
| 72–120h | 80 | +9.25 | 5.76 |

**But it never binds, because of market structure.** Every KXHIGHNY market's
price history begins **exactly ~37–38h before end-of-target-day** — verified as
a real listing fact, not the truncation the candlestick cap could have caused:
requesting daily bars over a 30-day window returns only **2** bars, hourly
returns 39, minute returns 1383, and all three agree on the same ~38h span.
Three granularities cannot be truncated to an identical window.

So every sample sits at 0–48h lead, where the pooled σ is nearly correct.
Stratifying changed skill by -1.6% / -17.6% / +0.1% — slightly *worse*, and
nowhere near the +5% margin.

**The structural finding.** Breaking the pooled study down by lead:

| lead | n | Brier(px) | Brier(fc) | skill |
|---|---|---|---|---|
| 0–6h | 408 | 0.0110 | 0.1173 | -967.6% |
| 6–12h | 408 | 0.0709 | 0.1173 | -65.3% |
| 12–18h | 408 | 0.0935 | 0.1238 | -32.5% |
| 18–24h | 408 | 0.0948 | 0.1238 | -30.6% |
| 24–30h | 408 | 0.1072 | 0.1241 | -15.8% |
| 30–36h | 402 | 0.1082 | 0.1245 | -15.0% |

`Brier(fc)` is essentially **flat** (0.117→0.125): between 12h and 38h out, the
MOS forecast barely changes, so the benchmark carries the same information
throughout. `Brier(px)` rises steeply with lead (0.011→0.108) as the market
loses its late information. The two converge — but the market is still ~15%
ahead at the oldest lead that exists, and the trend is **flattening**
(-15.8% → -15.0%), not closing.

**This is why Track B fails, and it is not a modelling failure.** The window
where a forecast edge could exist (3+ days out, where σ balloons and the market
would be uninformed) is a window in which **the market does not exist to trade**.
By the time Kalshi lists these contracts, the forecast is a short-lead nowcast
that the price has already absorbed. No improvement to the model reaches the
missing 20 points of skill, because the constraint is the listing schedule, not
the benchmark.

That makes the NO-GO stronger than ADR-0012's gate alone implies: it is not
"this crude benchmark found no room" here, it is "there is no tradeable window
in which room could exist for this series."

## What would justify revisiting

Narrowed by the finding above. A better *model* is no longer a plausible route
for KXHIGHNY — the tradeable window forecloses it. What remains:

- **A series listed further ahead of resolution.** The binding constraint is the
  ~38h listing window. A weather market listed a week out would put samples in
  the 72h+ band where σ is 5.76 and the market is uninformed. This is the only
  high-value check left, and it is a *venue/series* question, not a modelling one.
- **A station with materially worse public forecasts** (`SERIES_STATION` maps
  only KXHIGHNY→KNYC today).
- **A cold-season sample** — this is one summer.

## Operational note (follow-up)

The lead-stratified study runs the full 408-market comparison in **12 seconds**
using an in-memory preloading reader, against **3,251s** for the same pooled
model over the network — a ~270x speedup on identical output. It reproduces
this ADR's headline numbers exactly, which is what validates the reader. Strong
confirmation that research belongs on local data
([docs/ops/local-postgres.md](../../ops/local-postgres.md)).

## Operational note

The first attempt at this run failed in a way worth remembering: `_error_stats`
re-read the station's whole forecast history once per (market × as_of) pair,
~10⁵ whole-history reads, which exhausted the hosted database's monthly
data-transfer quota in 95 minutes and locked out every query. See ADR-0012's
reversed memoization decision. Post-fix the same study completes in 3,251s,
dominated by the ~55k candle reads that remain — which is why research runs
belong on a local database ([docs/ops/local-postgres.md](../../ops/local-postgres.md)).
