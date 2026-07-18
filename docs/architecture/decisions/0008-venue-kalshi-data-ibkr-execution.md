# Venue: Kalshi for data (free public API) + IBKR for execution (post-MVP, gated)

Under the confirmed constraints — US-based retail trader, bankroll < $10k,
paper-first (ADR-0001) — fairline needs a venue whose model-vs-price niche is
real, backtestable, and legally accessible. This ADR records the venue decision
and, critically, the **split** between where data comes from and where orders will
eventually go.

## Context

The full comparison is in the [venue research](../../research/2026-07-17-polymarket-edge-landscape.md)
Parts 6–7. Load-bearing facts (verified from venue docs there):
- **Kalshi** is US-legal, lists **exclusive weather + economics markets** (the
  ADR-0005 niche), exposes a **free public REST/WS/FIX API**, and — uniquely among
  US-accessible venues — publishes **free historical trades + candlesticks since
  2021**, so the edge is genuinely backtestable. Its fee is the same
  `coef·contracts·p·(1−p)` shape `fees.py` already models. Rate limits fit a
  non-HFT snapshot stack.
- **Polymarket US** lists sports only today, no evidenced historical data — no path.
- **IBKR Prediction Markets** routes Kalshi + ForecastEx + CME from one brokerage
  account and has a documented TWS/Web API supporting event-contract orders
  (whole-share quantities only). It is the user's chosen broker.

## Options considered

1. **Direct Kalshi API for both data and execution.** Simplest for one dev,
   matches ADR-0006, one integration. But couples the (eventual) live path to
   Kalshi's trading API and its own auth/nonce model.
2. **IBKR for both data and execution.** One account, multi-venue, smart routing.
   But adds an integration layer for *data* that we don't need — IBKR data is
   thinner/permissioned versus Kalshi's free public history, and it would put an
   extra dependency on the MVP's critical path.
3. **Hybrid: Kalshi public API for data, IBKR for execution (chosen).** Data stays
   free, direct, and backtestable from Kalshi (no auth, no broker dependency on the
   MVP path); execution — a *post-MVP*, gated concern — goes through IBKR, the
   user's broker, which also opens ForecastEx/CME later.

## Decision

**Hybrid (option 3).** For the MVP, **data = Kalshi public API** (ADR-0006,
`KalshiSource`, no trading auth). For the eventual live path (roadmap v0.2, gated
by ADR-0001), **execution = IBKR** via its TWS/Web API, implemented as a separate
execution adapter behind the Engine's risk gates — **no execution code in the MVP.**

The MVP therefore needs *none* of IBKR. The only immediate IBKR action is a
**user-side account task** (open/enable IBKR ForecastTrader / Prediction Markets +
API trading permissions) started day 1 so its approval lead time overlaps the build.

## Consequences

- **Risk to verify at execution-setup time (recorded, not resolved now):**
  *programmatic* trading of **Kalshi** contracts *through IBKR* "may vary by
  eligibility/account type," and contracts are added on a rolling basis. This is an
  execution-layer risk only; it does not touch MVP data or the backtest.
- **Fallbacks if Kalshi-via-IBKR is blocked:** (a) **ForecastEx** (IBKR-native,
  confirmed programmatic) for econ/climate contracts, or (b) the **direct Kalshi
  trading API** as the documented execution fallback. The choice among these is
  deferred to when live is actually built (it depends on which permissions clear).
- **Whole-share constraint:** IBKR event-contract orders are whole-share only; the
  sizing/Kelly layer must round to integer contracts at the execution boundary.
  Irrelevant to the paper backtest, noted for the live adapter.
- Data and execution are decoupled: swapping the execution venue later (Kalshi
  direct vs. ForecastEx vs. IBKR-routed) does not touch ingestion or the harness.
- `fees.py` already carries the Kalshi coefficient; if execution routes through
  IBKR, IBKR commissions are an *additional* line to model in the live adapter, not
  in the MVP backtest (which prices the Kalshi taker fee — the binding cost).
