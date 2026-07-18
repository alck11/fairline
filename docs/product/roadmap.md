# fairline — Roadmap (directional-EV on Kalshi, dual-track)

> Companion to `requirements.md`, rewritten 2026-07-17 for the confirmed Kalshi
> pivot. Describes the **current plan only**; history is in the research doc.
> Estimates are **developer-days** for **one developer, full-time (~6 productive
> hrs/day)**. Two tracks run interleaved; a single dev works them in rough
> alternation, so calendar time ≈ the summed dev-days minus overlap on waits
> (data downloads, IBKR approval). **Plumbing (Track A) is the critical path; when
> tracks conflict, A wins.**

## Immediate parallel task (user-side, not dev-days) — start now

**IBKR account + prediction-markets enablement.** Open/enable an Interactive
Brokers account with **ForecastTrader / Prediction Markets** and **API trading
permissions**, and confirm **Kalshi** contracts are programmatically tradeable for
the account type (see risk below). This has real approval + market-data-permission
lead time and gates only the *post-MVP* execution phase — so start it on day 1 and
let it run in the background. **The MVP needs none of it** (paper-first; Kalshi
*data* comes free from Kalshi's public API, no IBKR).

- **Verified:** IBKR's **TWS API** supports event contracts programmatically (read
  order books, submit limit orders, manage positions; whole-share quantities
  only). The **Web/Client-Portal API** supports event-contract market-data
  snapshots. IBKR routes Kalshi + ForecastEx + CME from one account.
- **Risk to verify at setup (reported):** *programmatic* trading of **Kalshi**
  contracts through IBKR "may vary by eligibility/account type," and contracts are
  added "on a rolling basis." **Fallback if blocked:** ForecastEx (IBKR-native,
  confirmed programmatic) for econ/climate, or the **direct Kalshi trading API**
  as the documented execution fallback. This is an execution-layer decision only;
  it does not touch MVP data or the backtest.

---

## MVP — the weather/econ EV backtest (paper-first)

### Track A — plumbing (CRITICAL PATH)

| Phase | Story | Dev-days | Notes |
|---|---|---|---|
| **A0** — Storage + persistence spine | US-1 | **3–5** | Provision PG+Timescale, apply schema (+ Kalshi/forecast additions), idempotent upserts. |
| **A1** — `KalshiSource` data adapter (ADR-0006) | US-2 | **4–7** | Markets (weather+econ), candles/trades, resolutions, historical endpoints. Official/free/documented — lower risk than the old 107GB spike. Data only, no execution. |
| **A2** — `prob_fn` contract + placeholder | US-3 | **1–2** | **Week 1** — defines the interface both tracks build against; placeholder (midprice/climatology) unblocks the harness. |
| **A3** — EV backtest harness | US-5 | **5–8** | Replay Kalshi history → `ev_detector` EV + quarter-Kelly → paper `Engine` → hold-to-resolution PnL. The core missing piece. |
| **A4** — Fee-aware report + baseline + leakage audit | US-6, US-7 | **3–5** | Post-Kalshi-fee PnL/ROI/Brier/Sharpe/drawdown vs. always-market-price baseline; point-in-time audit as definition of done. |
| **Track A subtotal** | | **16–27** | Produces a working, trustworthy backtest **against the placeholder** — the pipeline is proven before the real model exists. |

### Track B — weather model (interleaved / background)

| Phase | Story | Dev-days | Notes |
|---|---|---|---|
| **B1** — NOAA/NWS bulk data acquisition | US-4 (data) | **3–5** | Forecast + observation history aligned to Kalshi weather markets. Overlaps A on download waits. |
| **B2** — Calibration study (edge-room gate) | US-4 (study) | **3–5** | Do Kalshi prices already track public forecasts? **GO/NO-GO** — a NO-GO shortcuts B3. |
| **B3** — `prob_fn` v1 weather model | (implements US-3) | **6–12** | **The dominant risk.** Only built if B2 says GO. Drops into the A3 harness with no harness change. |
| **Track B subtotal** | | **12–22** | B1–B2 (6–10 dev-days) reach the calibration gate; B3 is spent only on GO. |

### MVP totals and the de-risking gate
- **To the calibration gate** (A0–A2 + B1–B2, enough to prove plumbing on the
  placeholder *and* decide whether a real model is worth building): **~11–19
  dev-days.**
- **Full MVP incl. real model** (all of A + B): **~28–49 dev-days (~6–10 weeks).**
  Revised up from the earlier single-track ~21–37 because the **weather model is
  now the real deliverable** (B3 = 6–12 dev-days) and it is the honest cost of
  producing a trustworthy edge verdict. The IBKR choice adds **no MVP dev-days**
  (paper-first) — only the user-side account task above.
- **Why the gate matters:** if B2 returns NO-GO, the MVP stops at ~11–19 dev-days
  with a defensible "no exploitable edge room in Kalshi weather" verdict — a
  capital-saving result, not a failure.

---

## Post-MVP

### v0.2 — from backtest to live-adjacent (evidence-gated)

| Item | Dev-days | Depends on / gate |
|---|---|---|
| **Forward paper on live Kalshi feed** | **3–5** | MVP GO verdict. Run the proven model forward in the Engine's paper mode on live-polled Kalshi data — smoke-tests latency/data-gaps before capital. |
| **IBKR execution adapter (LIVE, gated)** | **10–18** *(when justified)* | Positive forward-paper **and** ADR-0001 gate. Implement `place_live` **inside** the risk gates via IBKR TWS/Web API (whole-share orders); verify Kalshi-via-IBKR permissions first, else ForecastEx/direct-Kalshi fallback. |

### v0.3 — additional edge lines (optional)

| Item | Dev-days | Notes |
|---|---|---|
| **Econ `prob_fn`** (CPI/payrolls/Fed ranges) | **6–12** | Reuses the A3 harness; a second Kalshi-exclusive category. Gated on its own calibration study. |
| **Kalshi maker / Liquidity Incentive track** | **8–14** | Small-account resting-order rewards; forward-paper first (no historical depth to backtest). Revisit seriously only if bankroll grows toward ~$10k. |
| **Parked copy-trade revival** | — | Only if the revival conditions in `requirements.md` are met (US-legal per-trader data appears, or lawful international access). Reuses the parked subsystem + the MVP's harness/persistence spine. |

### Later — arbitrage stays a monitor only
No dedicated build. Latency-lost to HFT (2.7s windows) and fee-gated; the existing
detector runs opportunistically at most. Not a money line for this stack.

---

## Dependency + sequencing summary

```
User-side:  [IBKR account + API/Kalshi permissions] .......... (background, gates v0.2 live only)

Track A:  A0 ─▶ A1 ─▶ A2 ─▶ A3 ─▶ A4   (critical path; proven on placeholder)
                       │        ▲
Track B:  B1 ─▶ B2 ─(GO)▶ B3 ───┘  (drops into A3; NO-GO stops here)

Gate reached at A0–A2 + B1–B2 (~11–19 dev-days) → decide build-real-model or KILL
Full MVP → v0.2 forward paper → v0.2 IBKR live (ADR-0001 gate) → v0.3 options
```
Live is reachable only through a passing backtest **and** forward paper, inside the
risk gates — never around them (ADR-0001).

## Success metrics (mirror of requirements.md)
1. EV backtest runs on a multi-month real-Kalshi window, fee-aware report, zero
   manual patching (proven on the placeholder first).
2. Calibration study returns a clear GO/NO-GO; on GO, model out-of-sample net ROI
   beats the always-market-price baseline by a pre-registered margin.
3. Point-in-time audit passes — the verdict is not a lookahead artifact.
