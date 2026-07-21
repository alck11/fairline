# Implementation Plan — directional-EV on Kalshi (MVP, paper-first)

> Written 2026-07-17 for the confirmed Kalshi pivot. The prior plan (arb/copy-trade,
> WP-1..WP-8, all shipped) is at [`archive/plan.md`](./archive/plan.md) — historical
> only. This is the live plan. Inputs: [`requirements.md`](../product/requirements.md)
> (US-1..US-7), [`roadmap.md`](../product/roadmap.md) (Track A: A0–A4, Track B:
> B1–B3), [`overview.md`](./overview.md), and ADR-0005/0006/0008/0009/0010.

## Structure

Two interleaved tracks. **Track A (plumbing) is the critical path; when tracks
conflict, A wins.** The `prob_fn` contract (WP-2) is defined in week 1 so both
tracks build against it. Track B reaches a **calibration GO/NO-GO gate** (WP-7)
that can shortcut the expensive model build (WP-8). Estimates are developer-days
(one dev, ~6 hrs/day), carried from the roadmap.

```
Track A:  WP-1 ─▶ WP-2 ─▶ WP-3 ─▶ WP-4 ─▶ WP-5      (critical path; proven on placeholder)
                    │              ▲
Track B:  WP-6 ─▶ WP-7 ─(GO)──▶ WP-8 ──┘             (drops into WP-4; NO-GO stops here)
```
Calibration gate reached after WP-1,2 + WP-6,7 (~11–19 dev-days) → decide
build-real-model (WP-8) or KILL. Each WP is independently reviewable and leaves the
parked demos (`python3 src/<file>.py`) and existing tests green.

Every WP touching runtime code adds a standalone test under `tests/` following the
repo convention (`python3 tests/<file>.py`, no pytest dependency).

---

## WP-1 — Storage + persistence spine  *(A0, US-1)* — 3–5 dev-days

1. **Goal.** Provision PostgreSQL + TimescaleDB and a persistence layer so ingested
   Kalshi data and backtest output survive between runs. Serves **US-1**; unblocks
   every other WP.
2. **Scope.** New `schema/002_kalshi_ev.sql` (the five tables in ADR-0010:
   `candlestick`, `weather_forecast`, `weather_observation`, `directional_signal`,
   `backtest_run`, `backtest_result`). New `src/store.py` — a thin persistence layer:
   connection from env, idempotent upserts, and the point-in-time read helpers the
   `ProbFn` reader needs. README setup section for DB provisioning.
3. **Inputs.** `schema/001_schema.sql` (base dimension tables, unchanged);
   ADR-0010 (table shapes + upsert keys); `ingest.py` row dataclasses (existing +
   the `Candle`/`ResolutionRow` added in WP-3 — WP-1 defines their target columns).
4. **Outputs / signatures.**
   - `schema/002_kalshi_ev.sql` applied on top of `001`.
   - `src/store.py`:
     `connect() -> Connection`;
     `upsert_market(conn, MarketRow) -> int` (returns market_id, idempotent on
     `(venue, external_id)`); `upsert_outcomes(conn, market_id, outcomes)`;
     `upsert_candles(conn, list[Candle])`; `apply_resolutions(conn, list[ResolutionRow])`;
     `upsert_forecasts(conn, rows)`; `upsert_observations(conn, rows)`;
     `write_signal(conn, run_id, DirectionalSignal, as_of)`;
     `write_backtest_run(conn, ...) / write_backtest_result(conn, ...)`;
     PIT readers `candles_before(conn, token_id, as_of) -> list[Candle]`,
     `forecasts_before(...)`, `observations_before(...)` (all enforce `< as_of` in SQL).
5. **Acceptance (US-1 G/W/T).** A round-trip test writes and reads back a Kalshi
   market, a candlestick, and a resolved outcome identically; **re-running the same
   writes is idempotent** (row counts unchanged, values updated not duplicated).
   PIT readers never return a row dated `>= as_of` (boundary test at exactly `as_of`).
6. **Boundaries.** Do **not** modify `schema/001_schema.sql` or any parked table.
   Do **not** add business logic (EV, sizing, model) here — persistence only. Do
   **not** open network/API connections (that is WP-3).

---

## WP-2 — `prob_fn` interface contract + placeholder  *(A2, US-3; week 1)* — 1–2 dev-days

1. **Goal.** Fix the stable `prob_fn` contract both tracks build against, and a
   placeholder that unblocks the harness before the real model exists. Serves
   **US-3**; traces to **ADR-0009**.
2. **Scope.** New `src/prob_fn.py`: `MarketRef`, `ProbFn` Protocol, `MidpriceProbFn`
   (the placeholder = baseline), optional `ClimatologyProbFn`.
3. **Inputs.** ADR-0009 (the exact contract); `store.py` PIT readers from WP-1
   (`candles_before`); `ingest.py` `Candle` type.
4. **Outputs / signatures.** Exactly ADR-0009:
   `class ProbFn(Protocol)` with `name: str` and
   `__call__(self, market: MarketRef, as_of: datetime) -> float`;
   `MidpriceProbFn(reader).__call__` returns the last candle `close` with
   `ts < as_of` (raises/returns per contract if none); output clamped-validated to
   [0,1]. `MarketRef` frozen dataclass as specified.
5. **Acceptance (US-3 G/W/T).** `ev_detector.find_signal` consumes a scalar derived
   from the placeholder unchanged (demonstrated via the WP-4 harness adapter);
   swapping `MidpriceProbFn` for a different `ProbFn` requires **no** change to the
   contract or the harness call site. Placeholder is deterministic and honors the
   `< as_of` boundary (unit test).
6. **Boundaries.** Do **not** build any real/weather model here (that is WP-8). Do
   **not** modify `ev_detector.py`. Do **not** read data outside the WP-1 PIT
   readers (no direct SQL, no future rows).

---

## WP-3 — `KalshiSource` data adapter  *(A1, US-2)* — 4–7 dev-days

1. **Goal.** Kalshi market data + history behind the venue-neutral data interface,
   so the rest of the stack never sees Kalshi specifics. Serves **US-2**; traces to
   **ADR-0006** (data adapter; data/wallet split).
2. **Scope.** Add `MarketDataSource` Protocol + `Candle`/`ResolutionRow` dataclasses
   to `src/ingest.py`. New `src/ingest_kalshi.py` (`KalshiSource`). An ingest
   entry-point/script that pulls weather+econ markets, candles, trades, resolutions
   into the store (via WP-1). Comprehensive data validation (null/empty fields, OHLC
   [0,1] range, pagination hang guards, yes_bid/yes_ask fallback correctness) that
   raises `KalshiAPIError` on malformed data rather than silently succeeding or
   raising bare tracebacks. README ingestion section.
3. **Inputs.** `src/ingest.py` (existing Protocol/row types); `store.py` upserts
   (WP-1); Kalshi public REST/WS API (no trading auth). Do **not** populate
   `market.fee_rate` (schema/001): Kalshi fees are computed at call time by
   `fees.kalshi_fee` from a coefficient, never from a stored per-market rate, and
   no MVP code reads the column — it is a pre-pivot artifact, leave it NULL
   (architect ruling 2026-07-18). The only live fee lever is the `index_market`
   flag; see the fee note under WP-4.
4. **Outputs / signatures.**
   - `ingest.py`: `MarketDataSource` Protocol (`list_markets`, `orderbook`,
     `candlesticks(token_id, *, start, end, period='1h') -> list[Candle]`,
     `resolutions(external_ids) -> list[ResolutionRow]`); frozen `Candle`
     (`ts, token_id, open, high, low, close, volume`), `ResolutionRow`
     (`external_id, outcome_token_id, resolved_value, resolved_at`).
   - `ingest_kalshi.py`: `KalshiSource` implementing `MarketDataSource`;
     `wallet_trades`/`leaderboard` raise `NotImplementedError("Kalshi exposes no
     public per-trader feed")`; graceful degradation (clear message, non-zero exit)
     on API/rate-limit failure.
5. **Acceptance (US-2 G/W/T).** A documented backtest window of real Kalshi
   weather/econ markets loads with resolved outcomes and **no manual patching**;
   the adapter exits non-zero with a clear error on API/rate-limit failure; **no
   trading/execution code is present** (data only). All required fields (ticker,
   outcome token ids, prices) and numeric ranges (OHLC ∈ [0,1]) are validated
   before row construction, raising `KalshiAPIError` on any malformation.
   Pagination cannot hang (max-page cap + non-advancing cursor detection).
   Integration tests run against recorded fixture responses (no live network in CI)
   including comprehensive validation regression cases (null fields, out-of-range
   prices, pagination anomalies, fallback correctness).
6. **Boundaries.** Do **not** implement order placement or any auth'd/trading
   endpoint. Do **not** touch `ingest_polymarket_cli.py` (parked) or the full
   `MarketSource` Protocol's existing methods. Do **not** compute EV/sizing here.

---

## WP-4 — EV backtest harness  *(A3, US-5)* — 5–8 dev-days

1. **Goal.** Replay Kalshi history and generate fee-aware, Kelly-capped directional
   signals through the paper Engine, producing realized hold-to-resolution PnL.
   Serves **US-5**; traces to **ADR-0005**. The core missing piece.
2. **Scope.** New `src/backtest.py` (the replay loop). One **additive** method on
   `src/risk_execution.py`: `Engine.execute_signal`. Persist signals + results via
   WP-1.
3. **Inputs.** `store.py` PIT readers (WP-1); `prob_fn.ProbFn` (WP-2); Kalshi data
   in the store (WP-3); `ev_detector.find_signal` + `fees.Leg` (built);
   `risk_execution.Engine` + `RiskLimits` (built).
4. **Outputs / signatures.**
   - `backtest.run_backtest(store, prob_fn, *, category, start, end, step, limits,
     run_id) -> BacktestSummary`. Per `as_of` step: price = last candle `ts < as_of`;
     `p = prob_fn(MarketRef, as_of)`; `find_signal(..., prob_fn=lambda _tok: p, ...)`;
     `Engine.execute_signal(signal, category=...)`; on resolution
     `Engine.settle(realized_pnl)` and `store.write_backtest_result(...)`.
   - `risk_execution.Engine.execute_signal(self, signal, *, category) -> dict` —
     routes a `DirectionalSignal` through `_check` + `_fill`, records to the blotter,
     never writes `arb_opportunity`.
5. **Acceptance (US-5 G/W/T).** No decision at time T uses any data (forecast or
   price) dated `>= T`; fees use the Kalshi formula; the paper kill switch and
   exposure caps are active; **total PnL reconciles to the sum of per-signal realized
   PnL**; the harness runs identically against the placeholder and (later) the real
   model. Runs end-to-end on a small fixture window in CI.
6. **Boundaries.** Do **not** modify `ev_detector.py`, `fees.py`, or the existing
   `Engine` gate/kill-switch/`execute_arb`/`execute_copy` logic (only *add*
   `execute_signal`). Do **not** implement live execution. Do **not** build the
   report or the leakage audit (WP-5).

> **Fee note (architect ruling 2026-07-18).** The Kalshi fee path
> (`ev_detector.ev_per_share` -> `fees.Leg` -> `fees.kalshi_fee`) has **no seam**
> for the reduced-coefficient `index_market` flag: `find_signal`/`ev_per_share`
> construct `Leg(venue, size, price, category)` without it, so every Kalshi fee
> uses `KALSHI_COEF_DEFAULT` (0.07). For the MVP this is **accepted as-is** — 0.07
> is the higher coefficient, so it *understates* edge, the safe direction for a
> GO/NO-GO backtest (you cannot false-positive into trading on overstated fees).
> WP-4 must therefore **not** try to source or pass `index_market` (that would
> require editing `ev_detector.py`/`fees.py`, forbidden by this WP's boundary).
> **Open item:** if a later target market is Kalshi index-classified and the
> pessimism matters, the fix is an additive `index_market` param threaded
> `find_signal -> ev_per_share -> Leg` — a separate, future `ev_detector` change,
> out of MVP scope.

---

## WP-5 — Fee-aware report + baseline + leakage audit  *(A4, US-6 + US-7)* — 3–5 dev-days

1. **Goal.** One report that says whether the model beat the market after fees, plus
   an automated point-in-time audit that the result is honest. Serves **US-6, US-7**;
   traces to **ADR-0009** (PIT) and the ADR-0003 leakage principle.
2. **Scope.** New `src/report.py` (metrics + baseline) and `src/audit.py` (leakage
   check). Both read only stored tables (WP-1).
3. **Inputs.** `backtest_run` / `backtest_result` / `directional_signal` tables
   (WP-1, populated by WP-4); a completed backtest for the model and for the
   `MidpriceProbFn` baseline (same window, WP-2/WP-4).
4. **Outputs / signatures.**
   - `report.build_report(store, run_id, baseline_run_id) -> Report` showing net
     (post-Kalshi-fee) PnL, ROI, hit rate, Brier/calibration of `p_model`, Sharpe,
     max drawdown, per-market-type breakdown, and the same metrics for the baseline;
     **headline = model net ROI − baseline net ROI as one number**; reproducible
     from stored tables without re-ingest.
   - `audit.audit_run(store, run_id) -> AuditResult`; **exits non-zero** on any
     signal whose recorded price drew on a candlestick timestamped `>= as_of`
     (price-surface PIT re-derivation). `p_model`/forecast PIT-honesty is enforced
     by construction via the store's `< as_of` readers, and audited per-model
     in WP-8.
5. **Acceptance (US-6/US-7 G/W/T).** Report headline is one number (model minus
   baseline net ROI), reproducible from tables; audit fails loudly (non-zero exit)
   on a seeded lookahead violation and passes on a clean run. The audit is part of
   the backtest's definition of done.
6. **Boundaries.** Do **not** re-run ingestion or the harness inside the report
   (read stored tables only). Do **not** add early-exit/mark-to-market PnL (PnL is
   hold-to-resolution — CONTEXT.md). No UI/dashboard.

---

## WP-6 — NOAA/NWS bulk data acquisition  *(B1, US-4 data)* — 3–5 dev-days

1. **Goal.** Load NOAA/NWS forecast + observation history aligned to Kalshi weather
   markets, so Track B has point-in-time inputs. Serves **US-4 (data)**.
2. **Scope.** New `src/weather_ingest.py` — a `WeatherSource` over the **Iowa
   Environmental Mesonet (IEM)** point API (MOS forecasts + ASOS daily observations)
   that downloads/parses forecast + observation history into `weather_forecast` /
   `weather_observation` (WP-1 upserts). Mirrors `KalshiSource`'s shape: HTTP `_get`
   transport, a typed `WeatherAPIError`, graceful degradation, and fixture-based
   network-free tests. Source chosen per **ADR-0011** — IEM first (lightweight,
   stdlib-only, reaches the WP-7 kill gate fastest); the authoritative gridded
   **NCEI NDFD** archive is deferred to post-GO. `api.weather.gov` is ruled out (it
   serves no historical forecast archive). Runs in parallel with A on download waits.
3. **Inputs.** `store.py` upserts + `WeatherForecastRow`/`WeatherObservationRow`
   (WP-1, tables from ADR-0010); the IEM point API
   (`mesonet.agron.iastate.edu/api/1`, free, no auth); a curated `STATIONS` registry
   (`ICAO → IEM network, daily-id, IANA tz`) mapping each Kalshi weather series to
   the station its markets resolve against (per ADR-0011; not auto-parsed from
   tickers in the MVP).
4. **Outputs / signatures.** `weather_ingest.load_forecasts(...)` /
   `load_observations(...)` populating the tables with correct `issued_at` (from MOS
   `runtime_utc`, the true model-cycle publication time) and `observed_at` (the
   end-of-local-day instant the daily extreme became knowable, via the station tz)
   PIT keys; idempotent re-run. Forecasts stored as raw hourly `tmp` under variable
   `tmpf`; observations as `tmax`/`tmin`. `source` is namespaced (`iem-mos-<model>`,
   `iem-asos`) so a later NDFD ingest coexists without upsert-key collision.
5. **Acceptance.** Forecast history for the target stations/variables loads with
   `issued_at < valid_at` on every row; observations cover the resolution dates of
   the loaded Kalshi weather markets; re-running does not duplicate rows.
6. **Boundaries.** Do **not** build the calibration study (WP-7) or any model
   (WP-8). Do **not** touch Track A modules. `issued_at` must be the true forecast
   publication time — never back-filled from `valid_at`.

---

## WP-7 — Calibration study (edge-room GO/NO-GO gate)  *(B2, US-4 study)* — 3–5 dev-days

1. **Goal.** Decide, per market type, whether Kalshi weather prices already track
   public forecasts — i.e. whether there is edge room worth a model. Serves **US-4
   (study)**. **This is the GO/NO-GO gate for WP-8.**
2. **Scope.** New `src/calibration.py` — align Kalshi weather candles (WP-3) to
   NOAA/NWS forecasts (WP-6) at matching `as_of`, measure how closely price tracks
   the forecast-implied probability and the residual (lag/miss).
3. **Inputs.** `candlestick`, `weather_forecast`, `weather_observation` (WP-1/3/6);
   PIT readers (WP-1) — the study itself must be point-in-time honest.
4. **Outputs / signatures.** `calibration.run_study(store, *, category='weather',
   window) -> CalibrationReport` reporting, per market type, price-vs-forecast
   tracking and the residual, and a **clear GO/NO-GO signal** ("Kalshi prices lag
   public forecasts by X on type Y → edge room" vs "already efficient → no room").
5. **Acceptance (US-4 G/W/T).** Outputs a clear per-market-type GO/NO-GO; a NO-GO is
   a **valid, non-blocking** outcome that stops Track B before WP-8. Uses only
   pre-`as_of` forecast data (same PIT discipline as the backtest).
6. **Boundaries.** Do **not** build the predictive model (WP-8) — this only measures
   edge *room*. Do **not** gate Track A on the result (A proves plumbing on the
   placeholder regardless).

---

## WP-8 — `prob_fn` v1 weather model  *(B3, implements US-3)* — 6–12 dev-days — GATED on WP-7 GO

1. **Goal.** A research-grade weather probability model implementing the `ProbFn`
   contract, turning NOAA/NWS forecasts into an outcome probability that (hopefully)
   beats price. Implements **US-3** with a real model. **The dominant risk. Built
   only if WP-7 returns GO.**
2. **Scope.** New `src/weather_model.py` — a `ProbFn` implementation
   (`WeatherProbFn`) mapping forecast + climatology inputs to `p` for temperature /
   hurricane markets.
3. **Inputs.** `ProbFn` contract + `MarketRef` (WP-2); `weather_forecast` /
   `weather_observation` via WP-1 PIT readers; WP-7 GO verdict; the WP-4 harness
   (unchanged) to evaluate it.
4. **Outputs / signatures.** `WeatherProbFn(reader).__call__(market: MarketRef,
   as_of) -> float` conforming to ADR-0009 (reads only `< as_of` data). Drops into
   `run_backtest` by passing it where `MidpriceProbFn` went — **no harness change.**
5. **Acceptance.** The harness runs the model unchanged (US-3 acceptance); the WP-5
   report shows its out-of-sample net ROI vs. the baseline; the WP-5 audit passes on
   the run (no lookahead). A negative result is a valid, capital-saving verdict.
6. **Boundaries.** Do **not** modify the harness, `ev_detector`, or the contract to
   fit the model — the model conforms to them. If trained on history, obey ADR-0003's
   purged-CV / no-shared-sample discipline. Do **not** start before WP-7 GO.

---

## Traceability

| WP | Phase | Stories | ADRs | Depends on |
|----|-------|---------|------|-----------|
| WP-1 | A0 | US-1 | 0010 | — |
| WP-2 | A2 | US-3 | 0009, 0005 | WP-1 |
| WP-3 | A1 | US-2 | 0006, 0008 | WP-1 |
| WP-4 | A3 | US-5 | 0005, 0009 | WP-1, WP-2, WP-3 |
| WP-5 | A4 | US-6, US-7 | 0009, 0003(principle) | WP-1, WP-4 |
| WP-6 | B1 | US-4(data) | 0010, 0011 | WP-1, WP-3 |
| WP-7 | B2 | US-4(study) | 0009 | WP-3, WP-6 |
| WP-8 | B3 | US-3(real) | 0009, 0005 | WP-2, WP-6, WP-7=GO |

**Critical path:** WP-1 → WP-2 → WP-3 → WP-4 → WP-5 (~16–27 dev-days, proven on the
placeholder). **Gate at WP-1,2 + WP-6,7** (~11–19 dev-days): GO → WP-8, NO-GO →
stop with a defensible "no exploitable edge room" verdict. Full MVP: ~28–49
dev-days. Live (IBKR, ADR-0008) is post-MVP, reached only through a passing
backtest **and** forward paper, inside the risk gates (ADR-0001) — never around them.
