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

## What would justify revisiting

Any one of: a second station/series with materially worse public forecasts; a
cold-season sample; or evidence that a lead-stratified error model beats the
pooled-σ benchmark on the same data (cheap to test — the data is already
ingested and backed up).

## Operational note

The first attempt at this run failed in a way worth remembering: `_error_stats`
re-read the station's whole forecast history once per (market × as_of) pair,
~10⁵ whole-history reads, which exhausted the hosted database's monthly
data-transfer quota in 95 minutes and locked out every query. See ADR-0012's
reversed memoization decision. Post-fix the same study completes in 3,251s,
dominated by the ~55k candle reads that remain — which is why research runs
belong on a local database ([docs/ops/local-postgres.md](../../ops/local-postgres.md)).
