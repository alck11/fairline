# fairline

A prediction-market trading-research stack. The **active MVP** validates one
strategy: **directional-EV on Kalshi's exclusive weather/economics markets**,
backtested on Kalshi's free public history and run **paper-first** — does a
probability model beat the price after fees, out-of-sample? Earlier
**arbitrage** and **copy-trade** subsystems are **parked** (kept in repo,
demo-green, out of the MVP) after the 2026-07-17 venue pivot; see
[docs/product/requirements.md](docs/product/requirements.md),
[docs/product/roadmap.md](docs/product/roadmap.md), and
[the venue research](docs/research/2026-07-17-polymarket-edge-landscape.md).

Every module runs standalone with a synthetic demo (`python3 src/<file>.py`) so
you can see the mechanics before wiring real data. **No live order placement
ships in this repo** — that path is intentionally stubbed and gated, with IBKR
the intended eventual live venue (ADR-0008).

Domain language lives in [CONTEXT.md](CONTEXT.md); decisions in
[docs/architecture/decisions/](docs/architecture/decisions/); architecture in
[docs/architecture/overview.md](docs/architecture/overview.md) and the live
[implementation plan](docs/architecture/plan.md).

## Professional Tooling

This project includes a complete professional development setup:

| Tool | Purpose | Quick Start |
|------|---------|-------------|
| **ruff** | Linting + formatting (E, W, F, I, B, SIM, etc.) | `make lint`, `make format` |
| **mypy** | Static type checking (Python 3.12+) | `make type-check` |
| **pytest** | Unit + integration testing (fixture-based, no network in CI) | `make test` |
| **pre-commit** | Automated checks on git commit | `make pre-commit-install` |
| **bandit** | Security scanning | `make security-check` |
| **pytest-cov** | Code coverage reporting | `make coverage` |
| **black** | Code formatter (ruff is primary) | `make format` |
| **GitHub Actions** | CI/CD on every push | `.github/workflows/ci.yml` |

Configuration: `pyproject.toml` (single source of truth), `.pre-commit-config.yaml`, `Makefile`

See [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow and code style guide.

## Blocks

| File | Block | What it does |
|------|-------|--------------|
| `schema/001_schema.sql` | Storage | TimescaleDB schema: markets, outcomes, cross-venue links, orderbook + trade hypertables, wallet trades, point-in-time wallet scores, opportunity + execution audit. |
| `schema/002_kalshi_ev.sql` | Storage | Additive migration (WP-1, ADR-0010): candlestick (hypertable), weather_forecast, weather_observation, directional_signal, backtest_run, backtest_result, plus the `outcome_token` bridge `store.py` needs to address outcomes by venue-native token/ticker id. Does not touch `001` or any parked table. |
| `src/store.py` | Storage (persistence layer) | Thin layer over `001`+`002`: connection from env, idempotent upserts, and the point-in-time (`< as_of`, enforced in SQL) read helpers `prob_fn` implementations consume (ADR-0009, WP-1). No business logic, no network calls. |
| `src/ingest.py` | Ingestion (interface) | `MarketSource` Protocol — how markets, orderbooks, price history, wallet trades and leaderboard discovery enter the stack. Backend-agnostic (ADR-0006). Also carries the narrower `MarketDataSource` Protocol (`list_markets`/`orderbook`/`candlesticks`/`resolutions`, no wallet methods) plus the `Candle`/`ResolutionRow` row types (WP-3). |
| `src/ingest_polymarket_cli.py` | Ingestion (backend) · PARKED | First `MarketSource` impl: shells out to the official [polymarket-cli](https://github.com/Polymarket/polymarket-cli) (`-o json`, no-auth public data). Install the Rust binary and put `polymarket` on PATH (or set `$POLYMARKET_CLI`). |
| `src/ingest_kalshi.py` | Ingestion (backend) · MVP data adapter | `KalshiSource`: `MarketDataSource` over Kalshi's **public** trade-api v2 (weather + econ, no auth, free — ADR-0006, WP-3). `wallet_trades`/`leaderboard` raise `NotImplementedError` (Kalshi has no public per-trader feed). Data only — no order placement. |
| `src/run_kalshi_ingest.py` | Ingestion (entry point) | CLI that pulls Kalshi weather/econ markets + candles + resolutions via `KalshiSource` into the store (`store.py`, WP-1/WP-3). See "Kalshi ingestion" below. |
| `src/weather_ingest.py` | Ingestion (backend) · Track B data | `WeatherSource`: NOAA/NWS forecast + observation history via the **IEM** point API (MOS forecasts + ASOS daily obs, no auth, free — ADR-0011, WP-6). PIT `issued_at` from MOS `runtime_utc`; NCEI NDFD deferred to post-GO. Data only. |
| `src/run_weather_ingest.py` | Ingestion (entry point) | CLI that pulls IEM MOS forecasts + ASOS observations for one or more stations into the store (`store.py`, WP-1/WP-6). See "Weather ingestion" below. |
| `src/prob_fn.py` | Model interface (WP-2) | The `ProbFn` contract (ADR-0009): `prob_fn(MarketRef, as_of) -> p ∈ [0,1]`, point-in-time guaranteed via `store.py`'s PIT readers. Ships `MidpriceProbFn` (placeholder **and** US-6 baseline) and `ClimatologyProbFn`. |
| `src/backtest.py` | Backtest harness (WP-4) | `run_backtest(conn, prob_fn, ...)`: replays stored Kalshi candles step-by-step, binds `p = prob_fn(ref, as_of)` into `ev_detector.find_signal`, executes through the paper `Engine` under all risk gates, settles hold-to-resolution, and persists signals + results (US-5). See "EV backtest harness" below. |
| `src/report.py` | Backtest report (WP-5) | `build_report(conn, run_id, baseline_run_id)`: post-fee PnL/ROI, hit rate, Brier, per-trade Sharpe, max drawdown and a per-market breakdown for a model run **and** the baseline run, plus the headline — model net ROI − baseline net ROI as one number (US-6). Reads only stored tables; no re-ingest, no re-run. |
| `src/audit.py` | Leakage audit (WP-5) | `audit_run(conn, run_id)`: independently re-derives each signal's point-in-time price (`ts < as_of`, its own SQL — not `store`'s reader) and fails on any decision priced off a candle at/after `as_of`; CLI exits non-zero on a violation (US-7). The backtest's definition-of-done gate. |
| `src/calibration.py` | Edge-room GO/NO-GO study (WP-7) | `run_study(conn, ...)`: scores a naive, non-trained forecast→probability benchmark against Kalshi's price by Brier skill, per market type (ADR-0012). GO if the public forecast is more accurate than the price by a pre-registered margin (default 5%), else NO-GO — the gate for WP-8. PIT-honest; market specs parsed from stored rules; fee-free (edge room, not net edge). |
| `src/run_calibration.py` | Calibration (entry point) | CLI running the WP-7 study over stored tables; prints the per-type verdict and maps it to an exit code (0=GO, 2=NO-GO, 1=error). See "Calibration study" below. |
| `src/ev_detector.py` | Directional (MVP-primary) | Model-vs-price EV betting: post-fee EV/share, depth-aware sizing, quarter-Kelly cap. Probability supplied via the `prob_fn(market, as_of)` contract (ADR-0009). Paper-first (ADR-0001, ADR-0005). |
| `src/fees.py` | Fee math | Polymarket V2 taker formula `rate·p·(1−p)` (maker-free) + Kalshi per-order rounded fee. The single source of truth every other module imports. |
| `src/detector.py` | Detection · PARKED | Fee-aware edge for complete-set / cross-venue arb, plus depth-aware sizing that walks the book to find the profit-*maximizing* size after slippage. |
| `src/wallet_features.py` | Scoring (features) · PARKED | Point-in-time, leakage-safe features (fee-adjusted PnL, Sharpe, drawdown, recency PnL, category HHI, loss streaks, dominant category + share) + a transparent percentile composite score. |
| `src/wallet_scoring.py` | Scoring (model) · PARKED | Forward-label construction, purged time-series CV, XGBoost training, and category-scoped basket construction (top-k specialists within a category, gated on score + category concentration, ADR-0007). Beats-the-baseline gate before you trust it. |
| `src/market_matcher.py` | Matching · PARKED | Triage-only routing: local Ollama embeddings discard the unrelated or escalate everything else; only Claude (reading both resolution rule-sets) or a human ever writes a link (ADR-0002). |
| `src/risk_execution.py` | Execution + risk | Paper-trade engine with notional/exposure/wallet caps, daily-loss kill switch, basket-consensus gate, atomic both-legs-or-neither arb handling, and `execute_signal` routing directional Signals through the same gates (WP-4). |

## Setup

### Quick Start (recommended)
```bash
make setup       # One-time: creates .venv, installs all dependencies
source .venv/bin/activate
python src/store.py          # Demo any module
```

### Manual Setup
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/<file>.py
```

### Development Setup
```bash
make setup          # Creates .venv, installs prod + dev dependencies
make lint           # Auto-fix linting issues
make type-check     # Run type checker
make test           # Run tests
make pre-commit-install  # Install git pre-commit hooks
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for full development guide.

## Database setup

`src/store.py` (WP-1) needs **PostgreSQL 15+ with the TimescaleDB extension**.
Everything else in the repo (the detectors, scoring, risk engine) runs with no
database at all — only `store.py` and anything built on it need this.

1. Install Postgres + TimescaleDB. Options:
   - Docker (fastest for local dev): `docker run -d --name fairline-pg -p 5432:5432 \
     -e POSTGRES_PASSWORD=postgres timescale/timescaledb:latest-pg16`
   - Native: follow the [TimescaleDB install docs](https://docs.timescale.com/self-hosted/latest/install/)
     for your OS/Postgres version, then `CREATE EXTENSION timescaledb;` is
     handled by the schema itself (below) — you only need the extension
     files present on the server.
2. Create a database and point `$DATABASE_URL` at it (`store.connect()` and
   `psql` both read this; if unset, both fall back to the standard libpq env
   vars `$PGHOST`/`$PGPORT`/`$PGDATABASE`/`$PGUSER`/`$PGPASSWORD`):
   ```
   export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fairline
   psql "$DATABASE_URL" -c 'CREATE DATABASE fairline' 2>/dev/null || true
   ```
3. Apply the schema, **in order** — `001` first (base dimension tables:
   market/outcome/orderbook/wallet/arb — shared with the parked subsystems),
   then `002` (the five Kalshi/weather/backtest tables from ADR-0010, plus
   the small `outcome_token` bridge `store.py` needs — see the comment at
   the top of `schema/002_kalshi_ev.sql`):
   ```
   psql "$DATABASE_URL" -f schema/001_schema.sql
   psql "$DATABASE_URL" -f schema/002_kalshi_ev.sql
   ```
4. `.venv/bin/pip install -r requirements.txt` (pulls in `psycopg[binary]`),
   then `.venv/bin/python src/store.py` runs a small demo against it.

**Running `tests/test_store_persistence.py` without provisioning anything:**
if `$DATABASE_URL` is unset, the test falls back to `pgserver`
(`.venv/bin/pip install pgserver`, test-only, not in `requirements.txt`) to
spin up a throwaway local Postgres for the duration of the run — no manual
setup needed, at the cost of running without the TimescaleDB extension (the
test detects this and skips the extension/hypertable statements; every
correctness check it makes — round-trip, idempotency, PIT boundaries — is
plain SQL and unaffected by whether the tables are hypertables). If neither
`$DATABASE_URL` nor `pgserver` is available, the test prints why and exits 0
(skipped, not failed) rather than pretending to pass.

## Kalshi ingestion (WP-3)

`src/ingest_kalshi.py`'s `KalshiSource` reads Kalshi's **public** trade-api v2
(`https://external-api.kalshi.com/trade-api/v2` by default) — no API key, no
auth headers, free. Endpoints used: `GET /events?with_nested_markets=true`
(markets, filtered client-side to `category` in `{'Climate and Weather',
'Economics'}` — Kalshi's `category` query param is not actually applied
server-side, confirmed live), `GET /markets/{ticker}/orderbook`,
`GET /series/{series_ticker}/markets/{ticker}/candlesticks`, and
`GET /markets?tickers=...` (resolutions, via `status`/`result`). It implements
`ingest.py`'s `MarketDataSource` Protocol, not the full `MarketSource`:
`wallet_trades`/`leaderboard` raise `NotImplementedError("Kalshi exposes no
public per-trader feed")`, since Kalshi has no public per-trader feed to back
them (ADR-0006).

Token ids: Kalshi has no separate per-side id like Polymarket's CLOB tokens —
`KalshiSource` synthesizes `"<ticker>-YES"` / `"<ticker>-NO"` (matching the
convention `store.py`'s own demo/tests already use). NO-side candles/orderbook
levels are derived as the complement of the YES side (Kalshi's yes+no≈1
pricing), documented inline in `ingest_kalshi.py`.

**Data validation (2026-07-19 hardening pass):**
Every parser validates required fields and numeric ranges before constructing
a row:

- **Null/empty field checks:** `_parse_market()` and `resolutions()` now
  validate `ticker` is present; `orderbook()` validates every level's
  `price` is non-null; `candlesticks()` validates every `price_dollars` field
  before using it. Any missing identifier or required field raises
  `KalshiAPIError` (not `KeyError` or `TypeError` downstream).
- **OHLC range validation:** `candlesticks()` enforces `[0, 1]` range for all
  price fields — both the primary `open/high/low/close_dollars` fields and
  any fallback values computed from `yes_bid`/`yes_ask` midpoints (for bars
  with no trades). A price outside [0, 1] raises `KalshiAPIError` immediately
  rather than flowing through to a silent CHECK constraint violation in
  Postgres.
- **Pagination guards:** `list_markets()` cannot hang on a stuck cursor — it
  enforces a hard page cap (min 50, scaled by limit) and detects non-advancing
  cursors (exact repeat or previously-seen value) within 1–2 pages, raising
  `KalshiAPIError` with details instead of spinning forever.
- **CLI-level backstop:** `run_kalshi_ingest.py` catches any exception
  escaping `run()` (not just `KalshiAPIError`), prints a clearly-labeled
  "unexpected error" message + traceback to stderr, and exits 1 — preventing
  bare tracebacks from untested future API changes.

Run the demo (network required, no database, no auth) to see it against live
data:
```
.venv/bin/python src/ingest_kalshi.py
```

Run the real ingest — pulls markets, candles, and resolutions into the store
(needs `$DATABASE_URL` provisioned per "Database setup" above, plus network):
```
.venv/bin/python src/run_kalshi_ingest.py --category weather --days 14
.venv/bin/python src/run_kalshi_ingest.py --category economics --limit 20 --period 1h
```
`--category` (`weather`|`economics`, default both), `--limit` (max markets,
default 50), `--days` (trailing candle history window, default 7), `--period`
(`1m`|`1h`|`1d`, default `1h`). On an API or rate-limit failure it prints a
clear message to stderr and exits non-zero (`KalshiAPIError`) rather than
partially ingesting or crashing on a bare traceback — every HTTP call retries
transient (429/5xx) failures with backoff first.

**Tests are fixture-based, no live network:**
`tests/test_ingest_kalshi.py` monkeypatches `urllib.request.urlopen` to
replay real Kalshi responses recorded under `tests/fixtures/kalshi/`
(captured live 2026-07-18), with comprehensive regression tests for the
validation hardening (round-6 acceptance suite): null/empty fields, OHLC
out-of-range, pagination hangs, and yes_bid/yes_ask fallback correctness —
no network call happens when running the suite:
```
.venv/bin/python tests/test_ingest_kalshi.py
```

## Weather ingestion (WP-6)

`src/weather_ingest.py`'s `WeatherSource` loads NOAA/NWS **forecast +
observation history** — the weather model's only inputs (Track B) — from the
**Iowa Environmental Mesonet (IEM)** point API (public/free/no-auth). Source
chosen per **ADR-0011**: `api.weather.gov` serves no historical *forecast*
archive (current forecast only), so forecasts come from IEM's **MOS** guidance
and observations from IEM's **ASOS daily** summaries. The authoritative gridded
**NCEI NDFD** archive is deferred to post-GO (it needs GRIB/eccodes + grid
point-extraction — overkill before the WP-7 kill gate).

- **Point-in-time by construction:** `weather_forecast.issued_at` is the MOS
  `runtime_utc` (the model **cycle** = true publication time, never back-filled
  from `valid_at`); `valid_at` is `ftime_utc`. Every forecast row is checked for
  `issued_at < valid_at` and fails loud otherwise. `weather_observation.observed_at`
  is the end-of-local-day instant (via the station's IANA tz), a conservative
  "knowable by" bound that never leaks a future value into an earlier `as_of`.
- **Canonical station key:** MOS uses ICAO (`KNYC`), the daily feed uses an IEM
  network + short id (`NY_ASOS`/`NYC`); both are normalized to the ICAO so the
  store's PIT readers join forecasts to observations. Registry + Kalshi
  series→station map live in `weather_ingest.py` (`STATIONS`/`SERIES_STATION`).
- **Variables/source:** forecasts store raw hourly `tmp` as `tmpf`; observations
  store `tmax`/`tmin`. `source` is namespaced (`iem-mos-<model>`, `iem-asos`) and
  is part of the forecast upsert key, so a later NDFD ingest coexists without
  collision. Idempotent re-run via `store.py`'s `ON CONFLICT` upserts.

Demo (live network, no auth):
```
.venv/bin/python src/weather_ingest.py
```
Run the real ingest — pulls MOS forecasts + ASOS observations into the store:
```
.venv/bin/python src/run_weather_ingest.py --station KNYC --days 30
.venv/bin/python src/run_weather_ingest.py --station KXHIGHNY --start 2026-06-01 --end 2026-06-30
```
`--station` takes a canonical ICAO or a Kalshi series prefix (repeatable);
point the window at the dates covering your loaded Kalshi weather markets. A
single run backfills forecast **history** — one MOS model cycle per day across the
window (`--cycle-hour`, default 12Z, each a real past publication instant) — not
just the latest cycle, so WP-7 has point-in-time forecast history to study.
Degrades gracefully (clear stderr, non-zero exit) on API or DB unavailability —
never a bare traceback.

**Tests are fixture-based, no live network:** `tests/test_weather_ingest.py`
replays real IEM responses recorded under `tests/fixtures/iem/` (captured live
2026-07-20), covering PIT-key derivation, DST-correct `observed_at`, window
filtering, malformed-response handling, and idempotent re-run:
```
.venv/bin/python tests/test_weather_ingest.py
```

## Calibration study — edge-room GO/NO-GO gate (WP-7)

`src/calibration.py` answers the one question that gates the expensive weather
model (WP-8): **does Kalshi's weather price already track the public forecast, or
is there room for a forecast-based model to beat it?** It builds a *naive,
non-trained* forecast→probability benchmark and scores it against the market price
by **Brier skill**, per market type (ADR-0012):

- **The benchmark:** the forecast daily-high for the target date (max of hourly MOS
  `tmpf` from the latest cycle strictly before `as_of`), mapped through a Gaussian
  whose error mean/σ come from the station's **point-in-time** forecast-vs-observation
  history (only pairs knowable before `as_of`). P(YES) follows from the strike
  (`less`/`greater`/`between`) via the normal CDF. It is deliberately crude — a lower
  bound on edge room, *not* WP-8's model.
- **Market specs are parsed, not stored:** `(station, variable, target_date,
  strike_type, lo/hi)` come from the stored ticker + `resolution_text` (Kalshi's
  rules are unambiguous ground truth); an unparseable market is skipped, never
  guessed. WP-3 didn't persist the strike fields and backtest.py defers `params` to
  WP-8 — so WP-7 parses without touching Track A.
- **The verdict:** per type, `skill = (Brier_price − Brier_forecast) / Brier_price`;
  **GO** if `skill ≥ margin` (default 0.05), else **NO-GO** — a valid, capital-saving
  outcome that stops Track B before WP-8. Fee-free by design (edge *room*, not net
  profitability — that's the WP-4/WP-5 backtest).

```
.venv/bin/python src/run_calibration.py --start 2026-06-01 --end 2026-07-01 --step-hours 12
```
Reads only stored tables, point-in-time honest via `store.py`'s `< as_of` readers.
Exit code encodes the verdict for scripting (0=GO, 2=NO-GO, 1=error). Degrades
gracefully if Postgres is unavailable — never a bare traceback.

**Tests are synthetic + fixture-based, no network/DB:** `tests/test_calibration.py`
checks the spec parser against the **real** Kalshi `rules_primary` strings, the
`less`/`greater`/`between` probability math, PIT honesty (a forecast issued after
the window never changes the verdict), and both a **seeded GO** and a **seeded
NO-GO**:
```
.venv/bin/python tests/test_calibration.py
```

## EV backtest harness (WP-4)

`src/backtest.py` replays ingested Kalshi history through the directional-EV
strategy and the paper `Engine`, producing hold-to-resolution realized PnL:

```python
from datetime import datetime, timedelta, timezone
import store
from backtest import run_backtest
from prob_fn import MidpriceProbFn, StoreReader
from risk_execution import RiskLimits

conn = store.connect()
summary = run_backtest(
    conn, MidpriceProbFn(StoreReader(conn)),   # any ADR-0009 ProbFn drops in
    category="weather",
    start=datetime(2026, 6, 1, tzinfo=timezone.utc),
    end=datetime(2026, 7, 1, tzinfo=timezone.utc),
    step=timedelta(hours=1),
    limits=RiskLimits(), run_id="my-run")
```

Per `as_of` step it prices each outcome off the last candle **strictly before**
`as_of` (PIT enforced in SQL by `store.candles_before` — ADR-0009), resolves
`p = prob_fn(MarketRef, as_of)`, sizes via `ev_detector.find_signal`
(quarter-Kelly, post-Kalshi-fee), and executes through
`Engine.execute_signal` under the notional/exposure caps and kill switch.
Signals persist to `directional_signal` at decision time (even when the
Engine rejects them — that's the audit trail); settled positions persist to
`backtest_result`, and the summary's total PnL reconciles to their sum.

Deliberate MVP assumptions, each recorded in `backtest_run.params`: a
synthesized one-level book (`book_depth`) since Kalshi publishes no
historical depth (ADR-0006); one position per outcome, held to resolution;
only outcomes with a stored resolution are replayed (their value is used
strictly at settlement, never at entry); every Kalshi fee uses the 0.07
coefficient (architect ruling 2026-07-18 — understates edge, the safe
direction).

**Input validation (review-round hardening):** every numeric sizing/fee
argument to `run_backtest` (`book_depth`, `bankroll`, `kelly_fraction`,
`size_step`, `max_size`) is checked finite-and-positive before the replay
starts; `min_ev` is checked finite only (it may legitimately be `<= 0` as a
deliberate stress test of the EV cutoff). A `NaN` in any of the first five
defeats Python's own comparison operators (`nan <= 0` and `nan > cap` both
evaluate `False`, and `min(cap, nan) == cap`, not `nan`), which would
otherwise silently and permanently disable the `max_open_exposure` risk cap
or bypass the Kelly cap rather than raising. `prob_fn` output is likewise
range-checked per step: `NaN` or a value outside `[0,1]` raises immediately
(naming the outcome/`as_of`); an exact `0.0`/`1.0` is treated as "market
decided" and skipped, not traded.

Demo (`python3 src/backtest.py`) seeds a synthetic market and
needs `$DATABASE_URL`; tests need no provisioning:
```
.venv/bin/python tests/test_risk_execution_signal.py   # Engine gates, no DB
.venv/bin/python tests/test_backtest.py                # end-to-end, pgserver fallback
```

## Fee-aware report + leakage audit (WP-5)

Two read-only modules turn a stored run into a verdict. Neither re-ingests or
re-runs the harness — they read the tables WP-4 populated, so a report and its
audit reproduce from a database snapshot alone.

`src/report.py` — the answer to the one question the MVP exists to answer:

```python
from report import build_report, format_report

report = build_report(conn, "my-model-run", "my-baseline-run")
print(format_report(report))
print(report.headline_net_roi_delta)   # model net ROI − baseline net ROI
```

Per run it reports net (post-Kalshi-fee) PnL, ROI (denominator = notional =
cost-to-enter, CONTEXT.md), hit rate, Brier of `p_model`, per-trade
(unannualized) Sharpe, max drawdown, and a per-market breakdown that sums back
to the run total. The **headline is one number**: model net ROI − baseline net
ROI. The `MidpriceProbFn` baseline (`p_model = price`) is −EV after fees so it
never trades — ROI 0.0 by the zero-notional convention — and the headline
reduces to "did the model make a positive net ROI". Brier is the model's
calibration *on the bets it chose to make* (a positively-biased subset — the
no-edge steps aren't persisted, by design); that limitation is documented at
the metric.

`src/audit.py` — the proof the verdict is not a lookahead artifact (US-7,
ADR-0009). It re-derives, from stored candles with its **own** `ts < as_of` SQL
(deliberately not `store.candles_before` — an auditor that trusted the reader it
polices would be blind to that reader's bugs), the point-in-time price behind
every `directional_signal`, and fails any decision whose recorded price came
from a candle at or after its own `as_of`:

```
.venv/bin/python src/audit.py my-model-run     # exit 0 clean, 1 on a violation
```

The non-zero exit makes the audit a CI gate on the backtest's definition of
done. Both modules self-demo against `$DATABASE_URL`; the acceptance tests
provision a throwaway database (or `pgserver`) and skip cleanly without one:
```
.venv/bin/python tests/test_report_audit.py    # report reconciliation + seeded lookahead
```

## Suggested build order (MVP — see [plan.md](docs/architecture/plan.md))

Interleaved dual-track; plumbing (Track A) is the critical path and is proven
against a *placeholder* model before the real one exists:

1. **WP-1** storage + persistence spine (`schema/002_kalshi_ev.sql`, `store.py`).
2. **WP-2** `prob_fn(market, as_of)` contract + placeholder (`prob_fn.py`) — week 1.
3. **WP-3** `KalshiSource` data adapter (`ingest_kalshi.py`) — data only, no execution.
4. **WP-4** EV backtest harness (`backtest.py`) → paper `Engine` → hold-to-resolution PnL.
5. **WP-5** fee-aware report vs. baseline + point-in-time leakage audit.

Track B, interleaved: **WP-6** NOAA/NWS data → **WP-7** calibration study
(GO/NO-GO edge-room gate) → **WP-8** weather `prob_fn` v1 (only on GO).

Only after a passing backtest **and** forward paper do you implement `place_live`
inside the risk gates (via IBKR, ADR-0008). The parked arb/copy-trade build order
is preserved in [docs/architecture/archive/plan.md](docs/architecture/archive/plan.md).

## Reality checks baked into the design

- **Fees are small but real now** — taker `rate·p·(1−p)`; use maker/limit orders
  to zero the Polymarket leg, accepting fill risk.
- **Top-of-book edge lies** — `detector.best_cross_venue_size` exists because a
  5% headline spread routinely goes sub-1% once you size into the book.
- **Single-wallet copying is fragile** — features are recency-weighted and the
  model is judged on out-of-time rank correlation; trade baskets, not heroes.
- **Survivorship bias** — feed the full historical wallet universe (including
  wallets that went silent), or you'll overstate everyone's skill.

Not financial or legal advice. Prediction-market access varies by jurisdiction;
confirm what's permitted where you are before funding anything.
