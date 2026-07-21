# Weather data source: IEM point-based first, NCEI NDFD deferred

WP-6 (B1, US-4 data) must load NOAA/NWS **forecast + observation history** into
`weather_forecast` / `weather_observation` (ADR-0010) with an honest point-in-time
`issued_at` — the true forecast *publication* time, never back-filled from
`valid_at` (WP-6 boundary). This ADR records which of the two real archives that
data comes from, and why we start with the lighter one.

## Context

The obvious free endpoint, **`api.weather.gov` (the NWS API), serves no historical
forecast archive** — it returns only the *current* gridpoint/point forecast, so it
cannot supply the `issued_at`-keyed forecast history WP-7's calibration study and
WP-8's model need (verified 2026-07-20 against NCEI's NDFD product page and the IEM
archive docs). Historical NWS forecasts live in exactly two places:

1. **NCEI NDFD** — the authoritative *gridded* forecast archive (GRIB2), FTP/HTTPS
   back to ~2017. Highest fidelity, but decoding needs `cfgrib`/`pygrib` +
   the **eccodes** C system library + `xarray`, plus nearest-grid-point extraction
   from a projected grid to each station's lat/lon, plus managing large binary
   downloads. This is the same class of heavyweight bulk-data problem the roadmap
   explicitly pivoted *away* from (the paused Polymarket "107GB spike").
2. **Iowa Environmental Mesonet (IEM)** — archives NWS/NBM **MOS** guidance and
   **ASOS/METAR** observations behind a plain HTTP/JSON API
   (`mesonet.agron.iastate.edu/api/1`). Point-based, so it aligns directly to
   Kalshi's per-station weather markets (KNYC, …) with no grid interpolation, and
   is fixture-testable exactly like `KalshiSource` (stdlib `urllib`, no binary
   dependencies).

Two IEM endpoints carry everything WP-6 needs (shapes confirmed live 2026-07-20):

- **`GET /api/1/mos.json?station=<ICAO>&model=<MOS>`** → forecast rows carrying
  `runtime_utc` (the model **cycle time** = true publication time → `issued_at`),
  `ftime_utc` (the **valid** time → `valid_at`), and `tmp` (forecast temperature
  °F). `runtime_utc` is a genuine publication instant, satisfying the WP-6 "never
  back-filled from valid_at" boundary by construction, and `ftime_utc > runtime_utc`
  on every forecast row, satisfying `issued_at < valid_at`.
- **`GET /api/1/daily.json?network=<NET>&station=<ID>`** → `date`, `max_tmpf`,
  `min_tmpf` per local calendar day — the daily extremes Kalshi high/low-temp
  markets resolve against, the realized truth for `weather_observation`.

## Decision

**Build `src/weather_ingest.py` against IEM first.** NCEI NDFD is **deferred**, to
be added only if WP-7 returns **GO** *and* the calibration is close enough that
gridded-forecast fidelity is what stands between the model and an edge.

Rationale — effort vs. the kill gate:

- **~2–3 dev-days (IEM) vs. ~5–8 (NDFD).** IEM reuses almost the entire
  `KalshiSource` skeleton (HTTP `_get`, a typed `WeatherAPIError`, graceful
  degradation, small JSON fixtures); the only genuinely new work is field parsing
  and station/variable alignment. NDFD adds a whole binary-decode +
  grid-interpolation + heavy-dependency layer, each a fresh failure surface, and
  overshoots WP-6's 3–5-day budget.
- **WP-7 is a GO/NO-GO kill gate.** Paying 5–8 days for grid-perfect forecasts to
  feed a study that may well return NO-GO — stopping Track B regardless — is the
  wrong risk/reward for the MVP (`project_ultimate_goal_profit`: judge scope by
  expected edge, not buildability). IEM reaches the verdict fastest; NDFD is the
  fidelity upgrade you buy *after* the gate says the track is worth it.

## Consequences

- **Station-id normalization is load-bearing.** MOS addresses stations by ICAO
  (`KNYC`); the daily/ASOS feed uses an IEM network + short id (`NY_ASOS` / `NYC`).
  `weather_ingest.py` normalizes **both** forecast and observation rows to a single
  **canonical ICAO key** so the store's PIT readers — which filter on an exact
  `station` string — join them. A small curated `STATIONS` registry
  (`icao → network, daily-id, IANA tz`) is the source of truth; the market→station
  mapping is curated per Kalshi weather series, not auto-parsed from tickers
  (a documented, deliberate simplification for the MVP).
- **Observation `observed_at` is set to the true end-of-local-day instant** (start
  of the next local calendar day, via the station's IANA tz → UTC), a conservative
  "knowable by" bound that can never be *earlier* than the value was actually
  known — the PIT-safe direction. A daily extreme is stored under variable `tmax` /
  `tmin`; forecasts are stored as the raw hourly MOS `tmp` under variable `tmpf`.
- **Daily-extreme *forecast* derivation is deferred to WP-7/WP-8** (deliberate,
  matching WP-6's "acquire data, not model" boundary). We store the raw hourly
  forecast `tmp` rather than guess a max/min label on MOS's `n_x` field; the
  consumer computes the forecast daily high as the max over a valid-day's hourly
  `tmpf` rows, point-in-time, from the same PIT readers.
- **`source` column values are namespaced** so a later NDFD ingest coexists without
  key collision: forecasts as `iem-mos-<MODEL>` (e.g. `iem-mos-nbs`), observations
  as `iem-asos`. The `weather_forecast` upsert key includes `source`, so the same
  station/variable/time can later carry an NDFD row alongside the IEM one.

## Options considered

- **NCEI NDFD (gridded) first** — rejected *for now* (not forever): highest
  fidelity but ~2–3× the effort, heavy GRIB/eccodes dependencies with real CI/WSL
  install friction, and it front-loads that cost before the WP-7 kill gate decides
  the weather track is worth any of it. Kept as the explicit post-GO upgrade path.
- **`api.weather.gov` (NWS API)** — rejected: serves no historical forecast archive
  at all (current forecast only), so it cannot supply an `issued_at`-keyed history.
- **IEM daily-extreme forecast guidance (`n_x`) stored as `tmax`/`tmin` in WP-6** —
  deferred: classifying each `n_x` value as a max vs. a min needs day/night logic
  that is a modeling concern; shipping a guessed label would risk a silent
  correctness bug feeding WP-7. We store the unambiguous raw hourly `tmp` instead.
