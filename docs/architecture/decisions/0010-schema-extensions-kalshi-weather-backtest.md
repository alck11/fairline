# Schema extensions for Kalshi candles, weather data, signals, and backtest results

The base schema (`schema/001_schema.sql`) was shaped for Polymarket orderbooks and
wallet scoring. The Kalshi directional-EV MVP needs price history in a form Kalshi
actually publishes (candlesticks), the weather model's inputs, and a durable,
reproducible record of signals and backtest PnL. This ADR records those additions
as a new forward-only migration, `schema/002_kalshi_ev.sql`.

## Context and decision

**Reuse, don't reshape, the dimension tables.** Kalshi markets map cleanly onto the
existing grain: `venue='kalshi'` → `market` (`external_id`=ticker, `category`,
`fee_rate`, `resolves_at`, `resolved`) → `outcome` (YES/NO rows; `resolved_value`
∈ {1.0,0.0} on settlement). Resolutions are just updates to these columns. No change
to `market`/`outcome`/`venue`/`trade_print`. The parked tables (`market_link`,
`wallet*`, `arb_opportunity`, `execution`) stay untouched.

**Add five tables** (migration `002`):

1. **`candlestick`** (hypertable on `ts`) — Kalshi's free historical price history,
   the harness's primary point-in-time price source.
   `(ts, outcome_id FK, open, high, low, close, volume)`, prices NUMERIC in [0,1],
   PK `(outcome_id, ts)`. Why a new table rather than `orderbook_snapshot`: candles
   are OHLC bars, not best-bid/ask snapshots, and Kalshi's official API gives no
   historical depth — modelling them as degenerate book snapshots would lie about
   what the data is.
2. **`weather_forecast`** — `(issued_at, valid_at, station, variable, value, source,
   horizon_h)`. **PIT key is `issued_at`** (what was knowable when the forecast was
   published). The `ProbFn` reader filters `issued_at < as_of` (ADR-0009). Index on
   `(station, variable, valid_at)` and `(issued_at)`.
3. **`weather_observation`** — `(observed_at, station, variable, value, source)`,
   PK `(station, variable, observed_at)`. The realized truth the calibration study
   (US-4) and any model training score against.
4. **`directional_signal`** — the audit table ADR-0005 flagged as follow-up.
   `(id, run_id, as_of, outcome_id FK, p_model, price, size, ev_per_share,
   expected_profit, prob_fn_name)`. Persists each `DirectionalSignal` at decision
   time; distinct from `arb_opportunity` (CONTEXT.md → Signal — never conflated).
5. **`backtest_run`** — `(run_id PK, prob_fn_name, category, window_start,
   window_end, step, params JSONB, git_sha, created_at)`; one row per backtest.
   **`backtest_result`** — `(run_id FK, outcome_id FK, entry_as_of, entry_price,
   size, resolved_value, fee_paid, realized_pnl)`; one row per settled signal. The
   US-6 report and the always-market-price baseline read **only** these, so the
   report reproduces from stored tables with no re-ingest (US-6 acceptance).

**Idempotent upserts (US-1).** Every ingested row type gets an
`ON CONFLICT ... DO UPDATE` upsert keyed on its natural/primary key
(`market` on `(venue, external_id)`, `candlestick` on `(outcome_id, ts)`,
`weather_forecast` on `(source, station, variable, issued_at, valid_at)`,
`weather_observation` on its PK), so re-running ingestion is safe.

## Options considered

- **Force candles into `orderbook_snapshot`** — rejected: misrepresents OHLC as
  depth and pollutes the parked arb path's table.
- **Store forecasts keyed only on `valid_at`** — rejected: loses the `issued_at`
  point-in-time key, which is the entire basis of the leakage guarantee (ADR-0009).
- **Compute the report on the fly from the blotter** — rejected: US-6 requires
  reproducibility from stored tables without re-ingest; hence `backtest_result`.

## Consequences

- Migration is **forward-only and additive**; `001` is untouched, so parked demos
  and their tables keep working unchanged.
- The weather tables are Track B's contract with Track A: the `ProbFn` reader and
  the calibration study both read them, so their PIT keys (`issued_at`,
  `observed_at`) are load-bearing and must not be "simplified" to a single timestamp.
- `directional_signal` and `backtest_result` make the US-7 leakage audit possible
  as a post-hoc query: every signal's `as_of` and `entry_price` can be checked
  against the `< as_of` data that existed.
- Station/variable/threshold live in `market.params`-style JSONB on the signal path
  via `MarketRef.params`; the schema does not hard-code weather taxonomy, keeping
  econ markets (v0.3) addable without migration.
