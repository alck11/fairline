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
to `market`/`outcome`/`venue`/`trade_print` — no columns added, no types altered, so
`001` applies byte-for-byte and the parked demos keep working. The parked tables
(`market_link`, `wallet*`, `arb_opportunity`, `execution`) stay untouched.

**One additive bridge to preserve that invariant: `outcome_token`.** The ingest DTOs
and every point-in-time reader in `src/store.py` address an outcome by its
venue-native token/ticker id (`OutcomeRef.token_id` — "Polymarket CLOB token id /
Kalshi ticker side"): `candles_before(conn, token_id, as_of)`,
`forecasts_before(...)`, `write_backtest_result(..., token_id, ...)`, etc. The
`outcome` table (untouched, per the invariant above) carries no column for that
string — outcomes are keyed internally by `(market_id, idx)`. `outcome_token
(token_id TEXT PRIMARY KEY, outcome_id BIGINT REFERENCES outcome)` maps the venue
string to the internal `outcome_id` FK. It is populated by `store.upsert_outcomes`
(idempotent on `token_id`) and every `token_id`-taking function resolves through it
via `_resolve_outcome_id`. This is a *new additive table that references* `outcome`,
not a change *to* `outcome`; it honors the "no change to the dimension tables"
invariant literally while giving the readers the O(1), PK-indexed lookup their
signatures require. Chosen over the two alternatives below.

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

These five (six physical tables, `backtest_run` + `backtest_result` are one item)
plus the `outcome_token` bridge are the seven tables in `002`.

**Idempotent upserts (US-1).** Every ingested row type gets an
`ON CONFLICT ... DO UPDATE` upsert keyed on its natural/primary key
(`market` on `(venue, external_id)`, `outcome_token` on `token_id`, `candlestick`
on `(outcome_id, ts)`, `weather_forecast` on
`(source, station, variable, issued_at, valid_at)`, `weather_observation` on its PK),
so re-running ingestion is safe.

## Options considered

- **Force candles into `orderbook_snapshot`** — rejected: misrepresents OHLC as
  depth and pollutes the parked arb path's table.
- **Store forecasts keyed only on `valid_at`** — rejected: loses the `issued_at`
  point-in-time key, which is the entire basis of the leakage guarantee (ADR-0009).
- **Compute the report on the fly from the blotter** — rejected: US-6 requires
  reproducibility from stored tables without re-ingest; hence `backtest_result`.
- **Token→outcome resolution: add a `token_id` column to `outcome`** — rejected:
  even a nullable additive column is a change *to* a dimension table this ADR froze,
  it mixes a Kalshi/Polymarket-native id into the venue-neutral `outcome` grain, and
  it needs a separate unique index to get the PK-fast lookup the bridge gets for
  free. The `outcome_token` bridge keeps the invariant literal and the lookup O(1).
- **Carry `token_id` on the time-series tables instead of a mapping** — rejected:
  `candlestick`/`directional_signal`/`backtest_result` all FK to `outcome_id`, so
  every write and every PIT read would still need a token→outcome resolution;
  denormalizing `token_id` onto each would duplicate the mapping N times and let it
  drift. One bridge table is the single source of truth.

## Consequences

- Migration is **forward-only and additive**; `001` is untouched, so parked demos
  and their tables keep working unchanged.
- `outcome_token` is the one indirection every `token_id`-taking store function pays:
  a write or read for a token the bridge has never seen raises `KeyError` —
  `upsert_outcomes()` must run for a market before candles/resolutions/signals
  reference its outcomes. This is a deliberate fail-loud, not a silent insert.
- `token_id` is the bridge PK, i.e. assumed globally unique across venues. Venue
  token ids (Polymarket CLOB hashes, Kalshi ticker+side) are unique within a venue
  and collision across venues is not a practical concern; if it ever arose, the
  `ON CONFLICT (token_id) DO UPDATE` remap is at least deterministic. Namespace the
  id at the source (e.g. `kalshi:TICKER-YES`) if cross-venue reuse is ever added.
- The weather tables are Track B's contract with Track A: the `ProbFn` reader and
  the calibration study both read them, so their PIT keys (`issued_at`,
  `observed_at`) are load-bearing and must not be "simplified" to a single timestamp.
- `directional_signal` and `backtest_result` make the US-7 leakage audit possible
  as a post-hoc query: every signal's `as_of` and `entry_price` can be checked
  against the `< as_of` data that existed.
- Station/variable/threshold live in `market.params`-style JSONB on the signal path
  via `MarketRef.params`; the schema does not hard-code weather taxonomy, keeping
  econ markets (v0.3) addable without migration.
