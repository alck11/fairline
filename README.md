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
