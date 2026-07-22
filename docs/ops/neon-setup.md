# Neon setup: provisioning the DB for the WP-6/WP-7 real-data gate run

Everything in the repo up through WP-7 (the calibration edge-room GO/NO-GO
study, [ADR-0012](../architecture/decisions/0012-calibration-edge-room-brier-skill-gate.md))
is built and tested against synthetic/fixture data. The one remaining step to
close the gate for real is running it against a real Kalshi + weather window,
which needs a live Postgres. This doc is the runbook for using
[Neon](https://neon.com) (serverless Postgres) for that, plus the exact
commands to run the ingest → calibration pipeline once it's up.

## Why Neon works here (verified 2026-07-21)

`src/store.py` (WP-1) needs **PostgreSQL 15+ with the TimescaleDB extension**
([README § Database setup](../../README.md#database-setup)). Checked directly
against Neon's docs and the schema before recommending this:

- **TimescaleDB support:** Neon added the `timescaledb` extension in Feb 2026 —
  Apache-2 licensed features only (`create_hypertable`, hyperfunctions like
  `time_bucket`). That's exactly what the active pipeline needs: the only
  hypertable it touches is `candlestick`
  ([schema/002_kalshi_ev.sql:61](../../schema/002_kalshi_ev.sql#L61));
  `weather_forecast`/`weather_observation` are plain tables.
- **Postgres version:** 18 is Neon's default for new projects (June 2026),
  which satisfies "15+."
- **The one Timescale feature Neon does *not* support** — TSL continuous
  aggregates (`WITH (timescaledb.continuous)`) — only exists in
  `schema/001_schema.sql`'s `obook_1m` view, which belongs to the **parked**
  arbitrage/orderbook subsystem, not anything WP-6/WP-7 touches. Safe to
  ignore if that one statement errors when applying `001`.
- **Storage:** free tier is 0.5 GB/project (confirmed). Not measured against
  this project's actual row counts — **likely sufficient** for a first pilot
  window (one series, a few months of candles + forecast/observation rows,
  all small numeric rows) but unverified until you actually load data.
  Upgrading to the Launch tier (pay-as-you-go, $0.35/GB-month, no hard cap) is
  a non-destructive change if you outgrow it.

## Phase 1 — create the Neon project (you; needs your account)

1. Sign in at [neon.com](https://neon.com) (or console.neon.tech).
2. **New Project** → name it (e.g. `fairline`) → Postgres version **17 or
   18** → pick a region → create.
3. Copy the **connection string** from the dashboard (Connect →
   `postgresql://...`). Start with the direct (non-pooled) string; switch to
   the pooled one only if you hit connection-limit errors later.
4. Set it as `$DATABASE_URL` in your shell — `store.connect()` and `psql` both
   read this env var directly (falls back to standard libpq
   `$PGHOST`/`$PGPORT`/etc. if unset). Don't commit it to the repo.

This is the only phase that needs your Neon login — everything below is a
command any agent (or you) can run once `$DATABASE_URL` is set.

## Phase 2 — schema, ingest, calibration

```bash
# 1. Enable the extension + apply schema, in order
psql "$DATABASE_URL" -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;'
psql "$DATABASE_URL" -f schema/001_schema.sql
psql "$DATABASE_URL" -f schema/002_kalshi_ev.sql

# 2. Smoke-test the connection
.venv/bin/python src/store.py

# 3. Ingest Kalshi weather markets (WP-3) for your target window
.venv/bin/python src/run_kalshi_ingest.py --category weather --start <date> --end <date>

# 4. Ingest weather forecasts + observations (WP-6) for the matching station
.venv/bin/python src/run_weather_ingest.py --station KXHIGHNY --start <date> --end <date>

# 5. Run the calibration gate (WP-7)
.venv/bin/python src/run_calibration.py --start <date> --end <date> --step-hours 12
```

Step 5's exit code encodes the verdict for scripting: `0`=GO, `2`=NO-GO,
`1`=error. See [README § Full pipeline](../../README.md#full-pipeline-ingest--calibration-gate-wp-6--wp-7)
for the data-flow explanation and failure modes (unparseable markets, no
samples, API/DB unavailability — all fail-safe, never silently corrupt).

**After running:** sanity-check storage usage against the free-tier limit:
```bash
psql "$DATABASE_URL" -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

## Open decision before step 3/4

`weather_ingest.SERIES_STATION` currently only maps **`KXHIGHNY` → `KNYC`**
(NYC). That's the only series ready to ingest without first registering a new
station in [src/weather_ingest.py](../../src/weather_ingest.py). Start with
`KXHIGHNY` over a recent multi-month window for the fastest path to a real
verdict, unless a different series/station is specifically wanted.
