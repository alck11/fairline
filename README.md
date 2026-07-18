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

## Blocks

| File | Block | What it does |
|------|-------|--------------|
| `schema/001_schema.sql` | Storage | TimescaleDB schema: markets, outcomes, cross-venue links, orderbook + trade hypertables, wallet trades, point-in-time wallet scores, opportunity + execution audit. |
| `schema/002_kalshi_ev.sql` | Storage | Additive migration (WP-1, ADR-0010): candlestick (hypertable), weather_forecast, weather_observation, directional_signal, backtest_run, backtest_result, plus the `outcome_token` bridge `store.py` needs to address outcomes by venue-native token/ticker id. Does not touch `001` or any parked table. |
| `src/store.py` | Storage (persistence layer) | Thin layer over `001`+`002`: connection from env, idempotent upserts, and the point-in-time (`< as_of`, enforced in SQL) read helpers `prob_fn` implementations consume (ADR-0009, WP-1). No business logic, no network calls. |
| `src/ingest.py` | Ingestion (interface) | `MarketSource` Protocol — how markets, orderbooks, price history, wallet trades and leaderboard discovery enter the stack. Backend-agnostic (ADR-0006). |
| `src/ingest_polymarket_cli.py` | Ingestion (backend) · PARKED | First `MarketSource` impl: shells out to the official [polymarket-cli](https://github.com/Polymarket/polymarket-cli) (`-o json`, no-auth public data). Install the Rust binary and put `polymarket` on PATH (or set `$POLYMARKET_CLI`). |
| `src/ev_detector.py` | Directional (MVP-primary) | Model-vs-price EV betting: post-fee EV/share, depth-aware sizing, quarter-Kelly cap. Probability supplied via the `prob_fn(market, as_of)` contract (ADR-0009). Paper-first (ADR-0001, ADR-0005). |
| `src/fees.py` | Fee math | Polymarket V2 taker formula `rate·p·(1−p)` (maker-free) + Kalshi per-order rounded fee. The single source of truth every other module imports. |
| `src/detector.py` | Detection · PARKED | Fee-aware edge for complete-set / cross-venue arb, plus depth-aware sizing that walks the book to find the profit-*maximizing* size after slippage. |
| `src/wallet_features.py` | Scoring (features) · PARKED | Point-in-time, leakage-safe features (fee-adjusted PnL, Sharpe, drawdown, recency PnL, category HHI, loss streaks, dominant category + share) + a transparent percentile composite score. |
| `src/wallet_scoring.py` | Scoring (model) · PARKED | Forward-label construction, purged time-series CV, XGBoost training, and category-scoped basket construction (top-k specialists within a category, gated on score + category concentration, ADR-0007). Beats-the-baseline gate before you trust it. |
| `src/market_matcher.py` | Matching · PARKED | Triage-only routing: local Ollama embeddings discard the unrelated or escalate everything else; only Claude (reading both resolution rule-sets) or a human ever writes a link (ADR-0002). |
| `src/risk_execution.py` | Execution + risk | Paper-trade engine with notional/exposure/wallet caps, daily-loss kill switch, basket-consensus gate, and atomic both-legs-or-neither arb handling. |

## Setup

```
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/<file>.py
```

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
