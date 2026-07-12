# fairline

Reference scaffolding for a Polymarket/Kalshi arbitrage + copy-trade research
stack. Every module runs standalone with a synthetic demo (`python3 src/<file>.py`)
so you can see the mechanics before wiring real data. **No live order placement
ships in this repo** — that path is intentionally stubbed and gated.

Domain language lives in [CONTEXT.md](CONTEXT.md); decisions in
[docs/architecture/decisions/](docs/architecture/decisions/); architecture in [docs/architecture/](docs/architecture/).

## Blocks

| File | Block | What it does |
|------|-------|--------------|
| `schema/001_schema.sql` | Storage | TimescaleDB schema: markets, outcomes, cross-venue links, orderbook + trade hypertables, wallet trades, point-in-time wallet scores, opportunity + execution audit. |
| `src/ingest.py` | Ingestion (interface) | `MarketSource` Protocol — how markets, orderbooks, price history, wallet trades and leaderboard discovery enter the stack. Backend-agnostic (ADR-0006). |
| `src/ingest_polymarket_cli.py` | Ingestion (backend) | First `MarketSource` impl: shells out to the official [polymarket-cli](https://github.com/Polymarket/polymarket-cli) (`-o json`, no-auth public data). Install the Rust binary and put `polymarket` on PATH (or set `$POLYMARKET_CLI`). |
| `src/ev_detector.py` | Directional (experimental) | Model-vs-price EV betting: post-fee EV/share, depth-aware sizing, quarter-Kelly cap. Probability model injected, never built here. Paper-only (ADR-0005). |
| `src/fees.py` | Fee math | Polymarket V2 taker formula `rate·p·(1−p)` (maker-free) + Kalshi per-order rounded fee. The single source of truth every other module imports. |
| `src/detector.py` | Detection | Fee-aware edge for complete-set / cross-venue arb, plus depth-aware sizing that walks the book to find the profit-*maximizing* size after slippage. |
| `src/wallet_features.py` | Scoring (features) | Point-in-time, leakage-safe features (fee-adjusted PnL, Sharpe, drawdown, recency PnL, category HHI, loss streaks) + a transparent percentile composite score. |
| `src/wallet_scoring.py` | Scoring (model) | Forward-label construction, purged time-series CV, XGBoost training, and basket construction. Beats-the-baseline gate before you trust it. |
| `src/market_matcher.py` | Matching | Hybrid routing: local Ollama embeddings auto-link the obvious, Claude confirms the ambiguous by reading both resolution rule-sets. |
| `src/risk_execution.py` | Execution + risk | Paper-trade engine with notional/exposure/wallet caps, daily-loss kill switch, basket-consensus gate, and atomic both-legs-or-neither arb handling. |

## Setup

```
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/<file>.py
```

## Suggested build order

Build the **non-custodial** half first — it can't lose money and tells you
whether any edge exists:

1. `schema` + ingestion → fill `orderbook_snapshot`, `wallet_trade`.
2. `fees` + `detector` → log opportunities to `arb_opportunity` (observe only).
3. `wallet_features` + `wallet_scoring` → rank wallets, build baskets.
4. `risk_execution` in **paper** mode → replay history, measure realized edge.

Only after paper results justify it do you implement `place_live` inside the
risk gates.

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
