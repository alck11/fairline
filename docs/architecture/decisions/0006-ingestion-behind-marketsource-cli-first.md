# Ingestion sits behind a MarketSource interface; KalshiSource is the first real backend

> **Updated 2026-07-17 for the Kalshi pivot.** The interface decision stands; the
> *first real backend* changes. `KalshiSource` (Kalshi public REST/WS) is now the
> MVP's data adapter, **superseding the polymarket-cli path** as the live source.
> The polymarket-cli backend stays in-repo (parked). This update also records two
> splits the pivot forces: **data adapter vs. execution adapter**, and, within the
> data interface, **market data vs. wallet discovery**. Original text preserved below.

## What changed

Market data still enters fairline only through a Protocol in `src/ingest.py`; the
rest of the stack never knows which venue a row came from. The change is which
backend is real:

- **`KalshiSource` (`src/ingest_kalshi.py`) is the MVP data adapter.** It reads
  Kalshi's **public** REST/WS API — **no trading auth, free** — for markets
  (weather + econ first), candlesticks, trade prints, and market resolutions,
  across Kalshi's live (last ~3 months) and historical endpoints. Lower risk than
  the old Polymarket 107GB spike: official, documented, stable, free.
- **polymarket-cli is parked**, not deleted. It remains a valid `MarketSource`
  backend for the parked copy-trade path; it is off the MVP critical path.

**Split 1 — data adapter vs. execution adapter.** `KalshiSource` is a *data-only*
adapter: it contains **no order placement**. Execution is a separate concern on a
separate (post-MVP) adapter, and — per the venue decision (ADR-0008) — a separate
*venue*: data comes free from Kalshi's public API, while live execution is intended
via IBKR. The `MarketSource`/`MarketDataSource` Protocol is never allowed to grow a
`place_order`; that lives behind the Engine (ADR-0001) and its own future adapter.

**Split 2 — market data vs. wallet discovery.** The original `MarketSource`
Protocol bundled venue-neutral market data (`list_markets`, `orderbook`,
`price_history`) with Polymarket-only wallet methods (`wallet_trades`,
`leaderboard`). Kalshi has no public per-trader feed, so we introduce a narrower
`MarketDataSource` Protocol — `list_markets`, `orderbook`, `candlesticks` (new),
`resolutions` (new) — which is what the backtest harness depends on.
`KalshiSource` implements `MarketDataSource`; its `wallet_trades`/`leaderboard`
raise `NotImplementedError("Kalshi exposes no public per-trader feed")`. The full
`MarketSource` (with wallet methods) remains the interface the parked polymarket-cli
backend satisfies. No consumer of the old Protocol breaks.

New row dataclasses in `ingest.py` (shaped for `schema/002_kalshi_ev.sql`,
ADR-0010): `Candle` → `candlestick`, `ResolutionRow` → `market`/`outcome`
resolution fields.

## Consequences

- The harness and `prob_fn` depend on `MarketDataSource`, not on Kalshi specifics —
  a future direct-HTTP or IBKR *data* backend can replace `KalshiSource` without
  touching consumers, exactly as the original interface decision intended.
- Kalshi's official API gives **no historical orderbook depth** (only third parties
  persist it); the MVP directional-EV backtest uses candlesticks + trades +
  settlement, which *are* free, so this is not a blocker. Depth-sensitive backtests
  (e.g. a maker track) would need a third-party depth source — out of MVP scope.
- Kalshi rate limits make HFT impractical but suit a snapshot/replay stack;
  ingestion must degrade gracefully on rate-limit/API failure (clear error,
  non-zero exit — US-2).
- If live execution is ever built it gets its own adapter and decision (ADR-0008),
  never a method on the data Protocol.

---

## Original decision (preserved — pre-pivot context)

Market data enters fairline only through the `MarketSource` Protocol
(`src/ingest.py`): markets, orderbooks, price history, wallet trades, and
leaderboard discovery. The first implementation shells out to the official
**polymarket-cli** (Rust) with `-o json` (`src/ingest_polymarket_cli.py`); a
direct-HTTP backend can replace it later without touching any consumer.

Why a subprocess around a CLI rather than API client code: the CLI is
maintained by the Polymarket org (it absorbs API churn for us), its public-data
commands need **no wallet or keys** — which keeps ingestion consistent with the
paper-first, no-custody gate (ADR-0001) — and a research stack's polling/backfill
cadence doesn't need streaming latency. Why an interface anyway: the moment we
want real-time books (websockets) or Kalshi (no CLI exists), the backend has to
change, and consumers shouldn't notice. The known costs: an external Rust
binary as a dependency, one process spawn per call, and JSON field names pinned
to the CLI's output format (isolated in the `_parse_*` helpers — the only place
to touch when a CLI release renames a field).

- Kalshi ingestion is a future `KalshiSource` over their REST API — the
  interface, not the CLI, is the contract.
- `leaderboard()` is wallet **discovery only**: it seeds an append-only
  universe. Treating the leaderboard as the universe would reintroduce the
  survivorship bias ADR-0003 forbids.
- The CLI also has authenticated trading commands; they are out of bounds.
  Live placement remains unimplemented (ADR-0001), and if it is ever built the
  candidate paths (py-clob-client vs CLI) get their own decision.
