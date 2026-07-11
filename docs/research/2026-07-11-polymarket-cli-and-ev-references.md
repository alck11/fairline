# Reference assessment: polymarket-cli + "bot profit" threads (2026-07-11)

Four external references were reviewed for integration into fairline. This doc
records **the evidence and its quality**; the resulting *decisions* are in
ADR-0005 (directional EV strategy) and ADR-0006 (MarketSource ingestion).

## The references

### 1. [Polymarket/polymarket-cli](https://github.com/Polymarket/polymarket-cli) — the real asset

Official-org Rust CLI. What matters for fairline is that its **public data
requires no wallet or auth** and every command supports `-o json`:

| CLI command | Fills fairline table |
|---|---|
| `markets list / search / get` | `market`, `outcome` |
| `clob book TOKEN_ID` | `orderbook_snapshot` |
| `clob price-history TOKEN_ID --interval …` | `orderbook_snapshot` backfill |
| `data trades 0xWALLET` | `wallet_trade` |
| `data leaderboard --period … --order-by pnl` | wallet universe *discovery* |

This maps 1:1 onto the ingestion block that was previously stubbed in the
architecture overview. It also has authenticated trading commands
(`clob create-order`, …) — **not used**; live placement stays unimplemented
per ADR-0001. Assessment: credible, maintained, adopt.

### 2–4. The X threads — treat as anecdotes, not evidence

- **@waveking1314** — Chinese-language threads: "an HFT bot made $51K/month on
  BTC 5-minute Up/Down markets, trading every ~4.8 min"; "a trader turned $500
  + a $20 Claude subscription into $49K in two weeks arbing BTC spot vs
  Polymarket odds divergence."
- **@Dipper_pol (0xDipper)** — "a $300 weather bot made $101K in 2 months":
  scans ~20 cities via weather APIs (ECMWF/HRRR/METAR), buys ultra-rare weather
  outcomes priced at fractions of a cent when its model says they're underpriced,
  Kelly-sized.
- **RetroValix** — a GitHub account shipping a "Polymarket AI trading bot" for
  15-minute BTC UP/DOWN markets. Same genre, in repo form.

**Quality assessment: low.** The PnL claims are unverifiable, the genre is
engagement-farming, and the selection is textbook **survivorship bias** — the
same failure mode fairline's own scoring is built to avoid (ADR-0003): nobody
threads about the thousand bots that lost their $500. None of these claims
should motivate capital or architecture *directly*.

## The two real signals worth extracting

1. **Profitable algorithmic wallets are publicly discoverable on-chain.** Every
   one of these threads is someone manually doing what fairline's copy-trade
   subsystem does systematically: find a wallet with edge and follow it. The
   CLI's `data leaderboard` + `data trades` is the feed that lets fairline find
   the "$51K bots" itself — point-in-time scored, survivorship-safe — instead of
   reading about them on X. Discovery from the leaderboard is fine; the universe
   must remain **append-only** (a discovered wallet is never dropped when it
   goes silent).

2. **Short-horizon crypto and weather markets are algorithmically tradeable
   categories** — but the strategy in those threads is neither arb nor
   copy-trade: it's **model-based directional EV** (your probability model vs.
   the market's price). That's a third strategy for fairline, adopted as a
   **paper-only experimental prototype** with the probability model injected,
   not built (ADR-0005). Caveat noted there: the 5-minute markets are also a
   latency game that fairline's snapshot-based stack is not built to win;
   longer-horizon mispricings (weather-style) fit better.

## Decisions taken (recorded in ADRs)

- Ingestion goes behind a `MarketSource` interface; `polymarket-cli` subprocess
  is the first implementation, direct HTTP a later swap (ADR-0006).
- Directional EV enters as `src/ev_detector.py`, paper-only, same risk gates,
  explicitly experimental (ADR-0005).
- Nothing from these references touches live execution (ADR-0001 unchanged).
