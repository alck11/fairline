# Architecture Overview — directional-EV on Kalshi (backtested, paper-first)

> Owned by the dev-team architect. Rewritten 2026-07-17 for the confirmed Kalshi
> pivot (supersedes the stub). Primary inputs: [`requirements.md`](../product/requirements.md),
> [`roadmap.md`](../product/roadmap.md), the
> [venue research](../research/2026-07-17-polymarket-edge-landscape.md) Parts 6–7,
> [`CONTEXT.md`](../../CONTEXT.md), and the ADRs. Describes the system being built
> now; the parked copy-trade/arb subsystems are documented as *parked, in-repo*.

## What fairline is (now)

A research stack whose **single job** is to answer one question on real evidence:
*can a probability model beat Kalshi's weather/economics prices after fees,
out-of-sample, on paper?* It does this by ingesting free Kalshi historical data,
replaying it through a fee-aware, Kelly-capped, risk-gated **directional-EV**
strategy, and emitting a GO/KILL report against an always-market-price baseline.

- **Active (MVP):** directional EV on Kalshi weather/econ (ADR-0005, promoted to
  primary). Data via Kalshi's public REST/WS API (no trading auth). Execution is
  paper-only (ADR-0001).
- **Parked (in-repo, demo-green, not MVP):** cross-venue/complete-set **arbitrage**
  (`detector.py`) and **copy-trade** wallet scoring (`wallet_features.py`,
  `wallet_scoring.py`, `market_matcher.py`). Their ADRs (0002/0003/0004/0007) are
  flagged *parked, not active* and are not enforced against this plan.
- **Post-MVP:** live execution via **IBKR** (ADR-0008), gated behind a passing
  backtest *and* forward paper (ADR-0001). No IBKR/live code ships in the MVP.

## System context and data flow

```mermaid
flowchart TD
    subgraph Sources["Data sources (free, no trading auth)"]
        KAPI[Kalshi public REST/WS/FIX\nmarkets, candles, trades, resolutions]
        NOAA[NOAA/NWS bulk\nforecast + observation history]
    end

    subgraph Ingest["Ingestion (ADR-0006)"]
        KS[KalshiSource\nMarketDataSource impl]
        WX[weather_ingest\nNOAA/NWS loader]
    end
    KAPI --> KS
    NOAA --> WX

    subgraph Store["Storage — PostgreSQL + TimescaleDB (ADR-0010)"]
        PG[(market, outcome,\ncandlestick*, trade_print*,\nweather_forecast*, weather_observation*,\ndirectional_signal, backtest_run, backtest_result)]
    end
    KS --> PG
    WX --> PG

    subgraph Model["prob_fn contract (ADR-0009)"]
        PF[ProbFn: (market, as_of) -> p_model in 0..1\nplaceholder = midprice/climatology\nv1 = weather model, GATED on calibration GO]
    end
    PG --> PF

    subgraph Backtest["EV backtest harness (US-5)"]
        H[replay loop over as_of steps]
        EV[ev_detector.find_signal\nEV/share + quarter-Kelly]
        ENG[risk_execution.Engine\npaper mode, all risk gates]
    end
    PG --> H
    PF --> H
    H --> EV
    EV -->|DirectionalSignal| ENG
    ENG -->|paper fills, PnL| PG

    subgraph Verdict["Report + audit (US-6, US-7)"]
        RPT[report: net ROI vs baseline,\nBrier, Sharpe, drawdown]
        AUD[leakage / point-in-time audit\nfails loud on lookahead]
    end
    PG --> RPT
    PG --> AUD

    subgraph Calib["Track B gate (US-4)"]
        CAL[calibration study\ndo Kalshi prices track forecasts?\nGO / NO-GO]
    end
    PG --> CAL
    CAL -.GO.-> PF

    subgraph Parked["Parked (in-repo, not MVP)"]
        ARB[detector.py arb]
        COPY[wallet_* + market_matcher]
    end

    subgraph Future["Post-MVP (ADR-0008, gated)"]
        IBKR[IBKR execution adapter\nplace_live inside risk gates]
    end
    ENG -.post-MVP, gated.-> IBKR
```
`*` = TimescaleDB hypertable.

## Chosen stack (one line each)

| Choice | Why |
|--------|-----|
| PostgreSQL 15 + TimescaleDB | Replayable cold time-series (candles, trades, forecasts) in hypertables; already the committed store and schema base. |
| Kalshi public REST/WS API | The only US-legal venue with **free historical trades + candlesticks** since 2021 — the one thing that makes the edge backtestable (research Part 6). |
| Python 3.10+, pandas/numpy/scipy | Point-in-time replay, calibration stats, and report metrics; matches the existing repo. |
| `fees.py` Kalshi coefficient (built) | Kalshi fee is the same `coef·contracts·p·(1−p)` shape already modelled; single source of truth. |
| `ev_detector.py` + `risk_execution.py` (built) | EV/Kelly math and the paper Engine with risk gates already exist and are Kalshi-ready. |
| NOAA/NWS bulk data | Free, authoritative forecast+observation history — the weather model's only inputs (Track B). |
| IBKR (post-MVP execution) | User's choice; one account routes Kalshi+ForecastEx+CME. Data stays free/direct from Kalshi (ADR-0008). |
| XGBoost, Ollama, polymarket-cli | **Parked** — used only by the copy-trade/matcher subsystems; not on the MVP path. |

## Data model

Canonical grain in [`CONTEXT.md`](../../CONTEXT.md); DDL in `schema/001_schema.sql`
(base) + `schema/002_kalshi_ev.sql` (this pivot, ADR-0010).

**Reused as-is (base schema):**
- **venue** (`polymarket`|`kalshi`) → **market** (one event, one venue;
  `external_id` = Kalshi ticker, `category` ∈ {weather, economics, …}, `fee_rate`,
  `resolves_at`, `resolved`) → **outcome** (one row per tradable leg; YES/NO for
  Kalshi binaries; `resolved_value` ∈ {1.0, 0.0} once settled).
- **trade_print** (hypertable) — Kalshi trade prints.

**New (ADR-0010, `schema/002_kalshi_ev.sql`):**
- **candlestick** (hypertable) — `(ts, outcome_id, open, high, low, close, volume)`,
  price in [0,1]; Kalshi's free historical price history and the harness's primary
  point-in-time price source.
- **weather_forecast** — `(issued_at, valid_at, station, variable, value, source,
  horizon_h)`; PIT key is `issued_at` (what was knowable when). Track B input.
- **weather_observation** — `(observed_at, station, variable, value, source)`; the
  realized outcome the calibration study and any model training scores against.
- **directional_signal** — persists each `DirectionalSignal` at decision time
  (`as_of`, `outcome_id`, `p_model`, `price`, `size`, `ev_per_share`, `run_id`);
  the audit trail ADR-0005 flagged as deliberate follow-up.
- **backtest_run** — `(run_id, prob_fn_name, window_start, window_end, params,
  git_sha, created_at)`; one row per backtest, makes the report reproducible.
- **backtest_result** — per-signal realized PnL at resolution
  `(run_id, outcome_id, entry_as_of, entry_price, resolved_value, fee_paid,
  realized_pnl)`; the report and the always-market-price baseline read only this.

**Parked (base schema, untouched):** `market_link`, `wallet`, `wallet_trade`,
`wallet_score`, `arb_opportunity`, `execution` — kept for the parked subsystems.

## Interface contracts (concrete, so the executor invents nothing)

### Ingestion — `MarketDataSource` (ADR-0006)
The harness depends on a narrower interface than the full `MarketSource` Protocol.
Split the venue-neutral data methods from the Polymarket-only wallet methods:

```python
# src/ingest.py — add alongside the existing MarketSource Protocol
class MarketDataSource(Protocol):
    def list_markets(self, *, active: bool = True, category: str | None = None,
                     limit: int = 50) -> list[MarketRow]: ...
    def orderbook(self, token_id: str) -> BookSnapshot: ...
    def candlesticks(self, token_id: str, *, start: datetime, end: datetime,
                     period: str = "1h") -> list[Candle]: ...     # NEW row type
    def resolutions(self, external_ids: Sequence[str]) -> list[ResolutionRow]: ...  # NEW
```
`KalshiSource` (`src/ingest_kalshi.py`) implements `MarketDataSource`. It does
**not** implement `wallet_trades`/`leaderboard`; calling them raises
`NotImplementedError("Kalshi exposes no public per-trader feed")` — this is the
data/execution and data/wallet split ADR-0006 records. `Candle` and
`ResolutionRow` are new frozen dataclasses in `ingest.py` shaped for the
`candlestick` and `market`/`outcome` tables respectively.

### Model — `prob_fn` (ADR-0009)
```python
# src/prob_fn.py
@dataclass(frozen=True)
class MarketRef:                     # what a model MAY read; nothing time-forward
    external_id: str; venue: str; category: str
    outcome_token_id: str; outcome_label: str
    resolves_at: datetime | None
    params: dict                     # strike/threshold, station, target date, ...

class ProbFn(Protocol):
    name: str
    def __call__(self, market: MarketRef, as_of: datetime) -> float: ...  # p in [0,1]
```
**Point-in-time guarantee (binding):** a `ProbFn` may read only data timestamped
strictly before `as_of` (candlesticks with `ts < as_of`, forecasts with
`issued_at < as_of`, observations with `observed_at < as_of`). Placeholder
`MidpriceProbFn` returns the last candlestick close before `as_of` — this *is* the
US-6 always-market-price baseline (zero gross edge, pays only fees). The weather
`prob_fn` v1 (WP-8) implements the same Protocol and drops into the harness with
no harness change.

### Backtest harness (US-5)
```python
# src/backtest.py
def run_backtest(source_or_store, prob_fn: ProbFn, *, category: str,
                 start: datetime, end: datetime, step: timedelta,
                 limits: RiskLimits, run_id: str) -> BacktestSummary: ...
```
Per `as_of` step it: loads each candidate outcome's price as of `as_of` (last
candle `ts < as_of`); calls `p = prob_fn(market_ref, as_of)`; computes EV/share
via `ev_detector.find_signal` (binding `prob_fn=lambda _tok: p`, so `ev_detector`
stays byte-compatible — see ADR-0009); executes the resulting `DirectionalSignal`
through `Engine.execute_signal(...)` (paper) under all risk gates; on the outcome's
resolution calls `Engine.settle(realized_pnl)` and writes a `backtest_result` row.

### Execution (built, reused)
`ev_detector.find_signal(...) -> DirectionalSignal | None` and
`fees.Leg(venue, size, price, category, ...).fee()` are unchanged. The harness
needs one small additive method on the built Engine:
`Engine.execute_signal(signal, *, category) -> dict` — routes a `DirectionalSignal`
through `_check` + `_fill` like `execute_copy` does, records to the blotter, and
never touches `arb_opportunity` (CONTEXT.md → Signal). This is the only change to
`risk_execution.py`; the parked arb/copy paths and the kill switch are untouched.

## Cross-cutting policy

- **Error handling:** fail loud, never silently no-op. Ingestion validates all
  required fields and numeric constraints before constructing rows (WP-3
  2026-07-19 hardening pass: null/empty fields, OHLC [0,1] range, pagination
  hang guards, yes_bid/yes_ask fallback correctness). Bad data raises
  `KalshiAPIError` with context, not bare tracebacks. API/rate-limit failures
  degrade with a clear message and **non-zero exit** (US-2). The CLI layer has
  a backstop catch-all for any exception escaping `run()`. The leakage audit
  (US-7) exits non-zero on any lookahead. `place_live` keeps raising (ADR-0001).
  Bad `prob_fn` output (`NaN` or p ∉ [0,1]) raises, as `ev_detector` already
  does; the WP-4 harness applies the same NaN-or-range check per step before
  `find_signal` ever sees `p`. `run_backtest`'s own numeric arguments
  (`book_depth`, `bankroll`, `kelly_fraction`, `size_step`, `max_size`,
  `min_ev`) are validated finite (the first five also positive) before the
  replay starts — a `NaN` there would otherwise pass every downstream `<=`/`>`
  comparison silently and defeat the exposure or Kelly cap it was meant to
  enforce (2026-07-19 reviewer-round hardening pass).
- **Configuration:** risk limits stay in the `RiskLimits` dataclass; fee
  coefficients stay module constants in `fees.py`; DB connection and Kalshi API
  base/rate-limit from environment variables (documented in README); backtest
  windows and `step` are explicit `run_backtest` arguments recorded in
  `backtest_run.params`.
- **Logging / observability:** structured stderr logging in ingestion and the
  harness (rows ingested, as_of progress, signals fired/rejected); the
  `directional_signal` and `backtest_run`/`backtest_result` tables are the durable
  audit trail. No dashboard (non-goal).
- **Testing strategy (what gets which layer):**
  - *Unit* (standalone `python3 tests/<file>.py`, repo convention, no pytest dep):
    fee math, EV/Kelly, `prob_fn` placeholder determinism and PIT boundary,
    candlestick/resolution parsing, report metric math on synthetic PnL.
  - *Integration:* KalshiSource against recorded/fixture API responses (no live
    network in CI); persistence round-trip (US-1 write/read idempotency) against a
    local Timescale; harness end-to-end on a small **fixture** window with the
    placeholder model.
  - *E2E / acceptance:* one documented multi-month real-Kalshi backtest producing
    the report with zero manual patching (success metric 1), and the US-7 audit
    passing on it (success metric 3). These are run manually against live data, not
    in CI.
  - The US-7 point-in-time audit is itself the definition-of-done test for US-5.
```
