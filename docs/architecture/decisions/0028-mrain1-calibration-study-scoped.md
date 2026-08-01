# ADR-0028 — MRAIN-1 calibration study scoped: smaller than feared in three places, one new piece nobody had named, ~8-10 dev-days

- **Status:** Accepted (scope only — nothing built)
- **Date:** 2026-08-01
- **Follows:** [ADR-0024](0024-mrain1-power-objection-is-false-reopened.md), which
  closed "is there enough data" (82 station-months, KXRAINNYCM alone has 27)
  and named three things the actual gate would need: precipitation-accumulation
  ingestion, a climatological residual model, and confirming Kalshi's
  settlement source matches IEM's. **All three are checked here, live,
  before any code is written** — this ADR scopes the build; it does not do it.

## Decision

**Build it. The scope is smaller than ADR-0024 assumed in three places, and
one real piece larger than what ADR-0024 named. Net: ~8-10 dev-days, not
"comparable to WP-6/WP-7" (~10-16 dev-days combined) as a vague fear — a
concrete, checkable breakdown below.**

## The mandatory pre-check, done first because it could kill everything else

Per the 2026-07-25 research doc's own instruction ("0.5 dev-day, non-negotiable:
confirm Kalshi settles on the NWS CLI/CF6 report versus IEM hourly sums — a
silent resolution-source mismatch would corrupt the whole study"): checked
live, before writing any of the rest of this document.

**Kalshi's rain rules cite an explicit NWS "CLI" station code per city**
(e.g. `KXRAINNYCM`: *"total precipitation at Central Park, New York City"*;
`KXRAINCHIM`: *"...at CLIMDW in Chicago"*) — a stronger, more specific
citation than initially assumed. Cross-checked 4 resolved `KXRAINNYCM`
months' settled strike ladders against IEM's own daily-precip sum for the
same station/month:

| month | Kalshi ladder result (>N in.) | true total per Kalshi (inferred) | IEM `daily.json` sum |
|---|---|---|---|
| 2025-12 | >1,2,3 YES, >4 NO | (3, 4] | **3.38** |
| 2024-12 | >1,2,3,4 YES, >5 NO | (4, 5] | **4.53** |
| 2024-11 | >1,2,3 YES, >4 NO | (3, 4] | **3.35** |
| 2025-04 | >1,2,3 YES, >4,5,6 NO | (3, 4] | **3.25** |
| 2025-08 | >1,2 YES, >3,4 NO | (2, 3] | **2.21** |

**5/5 match, comfortably mid-bucket, not edge cases.** IEM's `daily.json`
`precip` field is the same source WP-6 already ingests for temperature —
**Confirmed** live to be the right ground truth for this study. This was
the single check that could have invalidated the whole build; it didn't.

## Where the scope shrinks

**1. No new data source — `precip` already exists in the endpoint WP-6 uses.**
Checked live: IEM's `/daily.json` (the exact endpoint `weather_ingest.observations()`
already calls for `max_tmpf`/`min_tmpf`) returns a `precip` field (daily
accumulation, inches) on every row, already. This is not a new API
integration — it's one more field pulled from a call this project already
makes.

**2. No schema migration.** Checked `store.py`: `weather_observation.variable`
is a free-text column (no CHECK constraint, no enum) — `"precip"` is a new
*value* in an existing column, not a new column or table. `upsert_observations`
and the `observations_before` PIT reader work unchanged.

**3. Station coverage is 6/10 already done.** Cross-referencing each rain
series' rules text against `weather_ingest.STATIONS`: `KXRAINNYCM` (KNYC),
`KXRAINLAXM` (KLAX), `KXRAINCHIM` (KMDW — Chicago Midway, exact match to the
CLI code cited), `KXRAINMIAM` (KMIA), `KXRAINDENM` (KDEN), `KXRAINAUSM`
(KAUS) are **all already in the curated station registry** from the WP-6
temperature build. Only 4 new stations needed: Seattle (`KXRAINSEAM`),
Houston (`KXRAINHOUM`), San Francisco (`KXRAINSFOM`), Dallas-Ft Worth
(`KXRAINDALM`, resolves against `CLIDFW`) — same `<STATE>_ASOS` IEM
convention WP-6 already documented, needing the same live spot-check WP-6's
own docstring already calls for before trusting a new entry.

**4. The strike grammar is trivially simple.** Checked every resolved market
across all 9 populated rain series: **100% use "strictly greater than N
inches" phrasing.** No "between" or "less than" variants exist (unlike the
temperature markets, which need all three). `calibration.py`'s existing
three-way `_parse_strike` regex is overkill here — a rain-specific spec
parser needs only the "greater" case.

## Where a real new piece exists that ADR-0024 didn't name

**The production ingest pipeline has the same historical-tier gap
[ADR-0023](0023-historical-tier-retracts-the-68-day-ceiling.md) found and
fixed for the read-only diagnostic scripts — but the production path was
never touched this session.** Checked: `KalshiSource.list_markets` (used by
`run_kalshi_ingest.py`) queries live-tier `/events`/`/markets` only;
`candlesticks()` queries the live-tier candlestick path only. Neither reaches
`/historical/markets` or `/historical/markets/{ticker}/candlesticks`. WP-7's
calibration study worked from **real ingested store data** (408 markets via
the store/PIT pipeline) — reproducing that for MRAIN-1 means the *production*
pipeline, not just a read-only report script, needs a historical-tier path:
paginated `/historical/markets` ingestion (parses cleanly into the existing
`MarketRow`/`ResolutionRow` shape — checked, `/historical/markets` already
returns `result` inline, no separate `resolutions()` call needed for old
markets) plus per-market `/historical/markets/{ticker}/candlesticks` pulls,
both upserted idempotently the way `run_kalshi_ingest.py` already does for
live markets. This is genuinely new, and it's the largest single piece below.

## Work packages, in dependency order

| # | Package | Depends on | Output (checkable) | Est. |
|---|---|---|---|---|
| 0 | Resolution-source + strike-grammar verification | — | **Done, this ADR** | 0 (spent) |
| A | `weather_ingest.py`: add `precip` observation variable, 4 new stations (live spot-checked), `SERIES_STATION` entries for 9 rain series | 0 | `tests/test_weather_ingest.py` covers precip parsing; live demo pulls a real month's precip for each new station | 1 |
| B | `KalshiSource` historical-tier market + candlestick ingestion, wired into `run_kalshi_ingest.py` (new backfill path, idempotent upserts) | 0 | A full MRAIN series (e.g. `KXRAINNYCM`, all 168 resolved markets) lands in the store with real candle history; re-running is a no-op (idempotency test) | 3–4 |
| C | Climatological residual model: leave-one-year-out empirical distribution of remaining-month precip per station/calendar-month, built from IEM's own deep history (independent of Kalshi's shorter window — no station-count limit here) | A | Given `(station, as_of, days_remaining)`, returns a calibrated `P(total > N)` for arbitrary `N`; unit-tested against a synthetic station with known distribution | 2–3 |
| D | `RainMarketSpec` parsing (ticker→station+month, rules→threshold) + `p_forecast` function wired into `calibration.py`'s existing generic PIT/Brier/aggregation machinery (`evaluate()`, `_as_of_grid`, `_aggregate`, `CalibrationReport` — all reused unchanged, category-parameterized already) | A, C | `calibration.run_study(conn, category="rain", ...)` produces a real report against store data | 1–1.5 |
| E | Run the gate, resolve the clustering-methodology question (recommended: cluster by station-month, matching this project's own family-clustering discipline from FLB-1/HURSEAS-1 — report both raw `n_samples` and `n_clusters`, gate on the latter), write the resulting ADR | B, D | GO/NO-GO ADR, same rigor as [ADR-0014](0014-wp7-gate-result-no-go.md) | 0.5–1 |

**Total: ~7.5–10.5 dev-days.** Piece C is where disproportionate care belongs
(rule 3 territory) — it's the one genuinely novel scientific component (precip
is non-negative and right-skewed; WP-7's Gaussian-on-forecast-error benchmark
does not transfer directly and reusing it unmodified would be a real modeling
error, not a simplification). Recommend an empirical/bootstrap distribution
over a parametric fit (lognormal/gamma) as the default: IEM's per-station
history is long enough (decades, not gated by Kalshi's 82 station-months) to
support it without a distributional assumption, and this project has
consistently preferred verified-simple over modeled-elegant elsewhere (fees.py,
the decile studies).

## What a GO here would and wouldn't mean

Matching WP-7's own boundary: this measures **edge room** (does a
climatology-based benchmark beat Kalshi's price on Brier skill), fee-free,
not net tradeable profitability. A GO justifies a WP-8-equivalent (build the
real model, run FLB-1-style fee-aware ROI and tail-risk checks) — it does
not itself produce a position. A NO-GO is a valid, capital-saving stop,
exactly as WP-7's NO-GO was for temperature.

## Consequence

This is buildable as scoped, at roughly half again the size of the original
WP-6+WP-7 weather line, not a comparable-or-larger rebuild as ADR-0024's
placeholder language implied. The single biggest remaining unknown is
scientific, not engineering: whether a leave-one-year-out precip climatology
actually beats Kalshi's price (piece C/E) — genuinely unknown until built,
same honest position WP-7 started from. No code has been written; this ADR
is the go/no-go-to-start decision point, not a build log.
