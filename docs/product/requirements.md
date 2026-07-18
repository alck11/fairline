# fairline — Product Requirements (MVP: directional-EV on Kalshi, backtested)

> Status: PM spec, rewritten 2026-07-17 after the confirmed venue pivot. This doc
> describes the **current plan only**; the strategy history (why copy-trade and
> the Polymarket venues were dropped) lives in
> `docs/research/2026-07-17-polymarket-edge-landscape.md` (Parts 5–7). Defines
> WHAT gets built and in what order, not the technical design. Respects
> CONTEXT.md and ADR-0001..0007 — see the ADR-handoff note in Non-goals.

## Blocking constraints (the plan is built around these)

- **User is US-based, retail.** Only US-legal venues are in scope.
- **Bankroll < $10k.** Rules out market-making as a lead strategy (needs ~$10k+
  to absorb adverse-selection inventory). Sizing stays small, into liquid books.
- **Venue = Kalshi.** Its **exclusive weather and economics markets** are the
  longer-horizon, model-vs-price niche fairline's `ev_detector.py` targets, and —
  uniquely among the venues assessed — Kalshi exposes **free public historical
  trades + candlesticks**, so the strategy is genuinely backtestable.
- **Data access = Kalshi public API** (no trading auth, free). **Execution =
  IBKR** (user's choice), as a **post-MVP** concern only.
- **Paper-first (ADR-0001).** No live order placement ships in the MVP. IBKR
  therefore affects only the post-MVP execution phase plus an **immediate
  user-side account-setup task** (see roadmap). `Engine.place_live` stays gated.

## Primary use case and persona

**Persona — "the researcher":** a solo, US-based, technically capable trader (the
user) with a sub-$10k bankroll who will not deploy capital on faith.

**Primary job:** *Decide, on real evidence, whether a probability model can beat
Kalshi's weather/economics prices after fees — by backtesting a directional-EV
strategy on free Kalshi historical data, entirely on paper, and reading a
fee-aware GO/KILL verdict.*

The MVP delivers exactly this. The user previously wanted a model in the MVP; they
get one — a **weather probability model (`prob_fn`)** aimed at the actual edge,
replacing the copy-trade-specific XGBoost forecast (now parked, below).

## Build sequencing — interleaved dual-track

Two tracks run together; the **prob_fn interface contract (US-3) is defined in
week 1** so both build against it.

- **Track A — plumbing (CRITICAL PATH):** storage → KalshiSource → prob_fn
  contract + placeholder → EV backtest harness → report/audit. This proves the
  whole pipeline end-to-end against a *placeholder* model before the real model
  exists.
- **Track B — weather model (interleaved/background):** NOAA/NWS bulk data
  acquisition → **calibration study** (do Kalshi weather prices already track
  public forecasts, i.e. is there edge room?) → real `prob_fn` v1.
- **When the tracks conflict, plumbing wins.** The calibration study (US-4) is a
  GO/NO-GO gate that can *shortcut the expensive model build* if no edge room
  exists.

## User stories

Given/When/Then acceptance criteria. IDs are stable references for the architect,
executor, and QA.

### US-1 — Storage + persistence spine  *(Track A)*
- **As** the researcher, **I want** a provisioned Postgres+TimescaleDB with the
  schema and a persistence layer, **so that** ingested Kalshi data and backtest
  output survive between runs.
- **Given** a fresh environment, **When** I run setup, **Then**
  `schema/001_schema.sql` (plus any Kalshi/forecast additions — architect handoff)
  is applied and each ingestion row type has a working idempotent upsert.
- **Acceptance:** a round-trip test writes and reads back a Kalshi market, a
  candlestick/price row, and a resolved outcome identically; re-running is
  idempotent.

### US-2 — KalshiSource data adapter (ADR-0006)  *(Track A)*
- **As** the researcher, **I want** Kalshi market data and history behind the
  `MarketSource` interface, **so that** ingestion is venue-swappable and the rest
  of the stack never sees Kalshi specifics.
- **Given** the Kalshi public REST/WS API (no trading auth), **When** ingestion
  runs, **Then** `KalshiSource` populates markets (weather + econ first),
  price/candlestick history, trade prints, and market resolutions, using Kalshi's
  live (last 3 months) and historical endpoints.
- **Acceptance:** a documented backtest window of real Kalshi weather/econ markets
  loads with resolved outcomes and no manual patching; the adapter degrades
  gracefully (clear error, exit non-zero) on API/rate-limit failure; **no trading
  or execution code is included** (data only).

### US-3 — prob_fn interface contract + placeholder model  *(Track A, week 1)*
- **As** the researcher, **I want** a stable `prob_fn` contract and a trivial
  placeholder implementation, **so that** both tracks build against one interface
  and the harness works before the real model exists.
- **Given** the ADR-0005 injected-model boundary, **When** the contract is defined,
  **Then** `prob_fn(market, as_of) -> p_model ∈ [0,1]` is specified (inputs it may
  read, the point-in-time guarantee it must honor) and a placeholder (e.g. returns
  current market midprice, or a fixed climatology) implements it.
- **Acceptance:** `ev_detector.py` consumes the placeholder unchanged; swapping the
  placeholder for the future weather model requires no harness change.

### US-4 — Weather data acquisition + calibration study (edge-room gate)  *(Track B)*
- **As** the researcher, **I want** NOAA/NWS forecast history and a study of
  whether Kalshi weather prices already track those forecasts, **so that** I don't
  build a model where no edge exists.
- **Given** bulk NOAA/NWS forecast + observation data aligned to Kalshi weather
  markets (temperature/hurricane), **When** the calibration study runs, **Then** it
  reports, per market type, how closely Kalshi prices track the public forecast and
  the *residual* (lag/miss) that represents potential edge room.
- **Acceptance:** the study outputs a clear GO/NO-GO signal ("Kalshi prices lag
  public forecasts by X on market type Y → edge room" vs "already efficient → no
  room"); a NO-GO result is a **valid, non-blocking** outcome that stops Track B
  before the expensive model build.

### US-5 — EV backtest harness  *(Track A, core)*
- **As** the researcher, **I want** to replay Kalshi history and generate
  fee-aware, Kelly-capped directional signals through the paper Engine, **so that**
  I get a realized, hold-to-resolution PnL.
- **Given** loaded Kalshi history and a `prob_fn` (placeholder or real), **When** I
  run the backtest over [start, end], **Then** for each step the harness computes
  `p_model` vs price, post-Kalshi-fee EV per share (`ev_detector` + `fees.py`
  Kalshi coefficient), quarter-Kelly sizing, executes the resulting
  `DirectionalSignal` via the paper `Engine` under all risk gates, and records PnL
  at resolution.
- **Acceptance:** no decision at time T uses any data (forecast or price) dated at
  or after T; fees use the Kalshi formula; the paper kill switch and exposure caps
  are active; total PnL reconciles to the sum of per-signal realized PnL; runs
  identically against the placeholder and the real model.

### US-6 — Fee-aware PnL report vs. market-price baseline  *(Track A)*
- **As** the researcher, **I want** one report that says whether the model beat the
  market after fees, **so that** I can make the GO/KILL call.
- **Given** a completed backtest, **When** I generate the report, **Then** it shows
  net (post-Kalshi-fee) PnL, ROI, hit rate, Brier/calibration of `p_model`, Sharpe,
  max drawdown, per-market-type breakdown, and the **same metrics for the
  always-take-market-price baseline** (i.e. `p_model = price`, which by
  construction has zero gross edge and only pays fees).
- **Acceptance:** the report's headline is the model's out-of-sample net ROI *minus*
  the baseline's, as one number; reproducible from stored tables without re-ingest.

### US-7 — Leakage / point-in-time audit  *(Track A)*
- **As** the researcher, **I want** an automated check that the backtest is honest,
  **so that** a positive result is not a lookahead artifact.
- **Given** a completed backtest, **When** the audit runs, **Then** it confirms
  every `prob_fn` call and every price used at decision time T drew only on
  forecast/observation/price data timestamped strictly before T.
- **Acceptance:** the audit fails loudly (non-zero exit) on any violation; it is
  part of the backtest's definition of done.

## Parked: wallet-scoring / copy-trade subsystem (kept in repo, out of MVP)

The copy-trade stack (`wallet_features.py`, `wallet_scoring.py`, `market_matcher.py`,
the consensus/basket logic, and the **old XGBoost forecast stories US-8/US-9**) is
**parked, not deleted.** It was copy-trade-specific and depended on public
per-trader on-chain data that **no US-legal venue exposes** and that does not exist
for Kalshi's weather/econ markets. It stays importable and demo-green.

**Revive it only if ALL hold:** (a) the user gains lawful access to a venue with
public per-trader data (e.g. international Polymarket) **or** a US venue begins
exposing per-trader feeds; **and** (b) that venue lists categories that overlap the
discoverable wallet universe; **and** (c) the weather-EV MVP has validated the
shared spine (harness, persistence, fee/report). Until then it is a background
asset, usable at most as *signal research* on public international data for
overlapping categories (politics/crypto/macro) — never as an MVP line.

## Non-goals (mandatory — the MVP will NOT do these)

- **No live / real-money execution.** Paper-first (ADR-0001); `place_live` stays
  raising. **No IBKR execution code in the MVP** — IBKR is a post-MVP phase plus a
  user-side account-setup task.
- **No copy-trade / wallet-scoring** in the MVP (parked, above).
- **No arbitrage** (complete-set or cross-venue): latency-lost to HFT, fee-gated;
  keep the detector as an opportunistic monitor only.
- **No market-making / liquidity-incentive** strategy in the MVP: needs ~$10k+;
  it is a post-MVP option (Kalshi LIP), forward-paper only.
- **No polished/production weather model.** The MVP ships a placeholder plus a
  calibration-gated `prob_fn` v1; research-grade, not a product.
- **No non-Kalshi venues** in scope (Polymarket US, ForecastEx, CME) beyond the
  IBKR execution path noted for post-MVP.
- **No real-time/low-latency path, no UI/dashboard, no early-exit modeling**
  (PnL is realized hold-to-resolution, per CONTEXT.md → PnL).

## Success metrics for the MVP (2–3 measurable signals)

1. **Pipeline works:** the EV backtest runs over a documented multi-month window of
   real Kalshi weather/econ history and emits a fee-aware report with **zero manual
   data patching** — proven first against the placeholder model.
2. **Edge verdict:** the calibration study (US-4) returns a clear edge-room GO/NO-GO;
   and, if GO, the model's out-of-sample **net (post-Kalshi-fee) ROI beats the
   always-market-price baseline** by a pre-registered margin. A NO-GO or a
   negative backtest is a **valid, capital-saving** result.
3. **Trustworthy:** the US-7 point-in-time audit passes, so the verdict in metric 2
   is not a lookahead artifact.

> **ADR handoffs (for the architect stage — not written here):** ADR-0006 backend
> (KalshiSource replaces the polymarket-cli path as the first real data adapter;
> execution adapter is separate); a **new venue-choice ADR** (Kalshi data + IBKR
> execution hybrid, US-retail/<$10k, plus the "Kalshi-via-IBKR programmatic
> permissions may vary" risk and direct-Kalshi fallback); an **update to ADR-0005**
> (directional EV is promoted from paper-only *experiment* to MVP-*primary*, and
> the prob_fn is now partly *built* here — a weather model — not purely injected);
> and marking ADR-0002/0003/0004/0007 **parked** so they are not read as active MVP
> constraints. ADR-0001 (paper-first) is unchanged.
