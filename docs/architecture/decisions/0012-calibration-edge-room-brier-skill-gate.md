# Calibration study: edge-room measured as Brier skill of a naive forecast vs price

WP-7 must decide, per market type, whether Kalshi's weather price already tracks
the public forecast — the GO/NO-GO gate for the expensive WP-8 model build. This
ADR records *how* "edge room" is defined and measured, because the choice gates a
capital decision and is not obvious from the code.

## Decision

**Edge room exists iff a *naive, non-trained* public-forecast probability is more
ACCURATE than the market price**, scored by Brier score over point-in-time samples.
Per market type: `skill = (Brier_price − Brier_forecast) / Brier_price`; **GO** if
`skill ≥ margin` (pre-registered, default **0.05** = 5% relative improvement),
else **NO-GO**. Overall GO if any market type is GO. The study is **fee-free** — it
measures edge *room*, not net profitability (that is the WP-4/WP-5 backtest's job).

The naive benchmark (`calibration._forecast_prob`): the forecast daily-high for the
target date (max of hourly MOS `tmpf` from the latest cycle strictly before
`as_of`) mapped through a Gaussian whose error mean/σ come from the station's
**point-in-time** forecast-vs-observation history (only pairs knowable before
`as_of`; min 10 pairs, non-zero variance, else the sample is skipped). P(YES)
follows from the strike (`less`/`greater`/`between`) via the normal CDF (`math.erf`,
no scipy dependency). The realized label is the market's settled `resolved_value`.

## Why this criterion (options considered)

- **Brier skill of the naive forecast vs price** — chosen. It is a single,
  pre-registerable number that directly answers "could a forecast-based model be
  more accurate than the market?", and it is *conservative*: the benchmark is a
  deliberately naive Gaussian, not a real model, so a GO means "even a crude
  public-forecast transform beats the price" — a lower bound on the edge room WP-8
  could exploit. A NO-GO under this crude benchmark is not proof no model could
  ever win, but it is a defensible, capital-saving stop.
- **Price-tracks-forecast lag / residual threshold** — rejected as the primary
  gate: it measures the same phenomenon less cleanly and has no single
  pre-registerable cutoff (the report still surfaces the mean price↔forecast gap
  and lead time as diagnostics).
- **Net-of-fee edge** — rejected: it conflates WP-7 (is there room?) with WP-4/WP-5
  (does it survive fees?), and would produce NO-GOs that really mean "fees too high
  on this market," not "no forecast edge exists." Fees enter later, once a real
  model is being backtested for profitability.

## Consequences

- **Market specs are parsed in WP-7, not stored.** The strike fields Kalshi exposes
  at ingest (`strike_type`/`floor_strike`/`cap_strike`) were not persisted by WP-3,
  and backtest.py sets `MarketRef.params={}` ("WP-8's concern"). WP-7 therefore
  reconstructs `(station, variable, target_date, strike_type, lo/hi)` from stored
  text — `market.resolution_text` (the Kalshi rules) is unambiguous ground truth
  ("... is less than 80°" / "... between 80-81°"); the ticker carries the date;
  `weather_ingest.SERIES_STATION` maps the series to a station. An unparseable
  market is **skipped, never guessed** (a mis-parsed threshold would silently
  corrupt the study). The parser handles standard Kalshi phrasings: "less than X",
  "X or fewer", "greater than X", "above X", "at least X", "X or more", and
  "between X and/to/-/and Y" — tested against real Kalshi rules strings. Non-weather
  yes/no binaries (Kalshi's dominant market pattern: earthquake/climate events with
  `strike_type=None`, no numeric bounds) have no daily-high forecast anchor and are
  skipped. Promoting this to ingest-time structured storage (a `market.params` JSONB,
  foreseen in ADR-0010) is a later option, not required to reach the gate. This keeps
  WP-7 inside its "do not touch Track A" boundary.
- **The Gaussian error transform is a benchmark, not a model.** It is intentionally
  simple (a single station-level bias + σ, leads mixed) so it cannot be mistaken
  for WP-8. WP-8 is free to build a richer, per-lead, feature-based model; WP-7
  only measures whether *any* honest public-forecast signal is left on the table.
- **Point-in-time by construction.** Every input — price, forecast, and the σ/bias
  history — is read through store.py's `< as_of` readers (ADR-0009). The study is
  verified to ignore a forecast issued after the window even when it would flip the
  verdict. The per-sample label uses the settled `resolved_value`, which is an
  outcome, not a lookahead input. **The σ/bias pool excludes the priced market's own
  `target_date`:** once `as_of` sits in `[observed_at(target_date), resolves_at)`,
  that market's realized outcome is already `< as_of` (WP-6's end-of-local-day
  `observed_at`) and would otherwise leak into the Gaussian that prices it — a
  read-by-read-legal but in-spirit lookahead where the benchmark peeks at the very
  quantity it predicts. It is the only date that can leak (any later observation is
  not yet knowable at `as_of`), so `_error_stats` drops exactly that pair (reviewer
  finding, 2026-07-21; regression-tested).
- **Observation date derivation couples to WP-6's `observed_at` convention**
  (start-of-next-local-day): the study recovers the observed calendar date as one
  local day before `observed_at`. If WP-6 ever changes that convention, this
  derivation must change with it — called out here as the one cross-WP coupling.

- **No memoization of `_error_stats` (station-history sigma/bias) in MVP.** The study
  rescans the entire observation/forecast history on each `(market, as_of)` pair, which
  is O(n²) in principle; however, a 180-day history takes ~0.45ms per call. Even for
  1000 markets × 30 `as_of` samples each, this is acceptable (~13 seconds total). A
  future optimization (memoizing per-station σ/bias at each `as_of`) could amortize
  this, but it is not required to reach the gate. Trade-off: complexity vs performance
  is reasonable today; revisit if backfills span years.
