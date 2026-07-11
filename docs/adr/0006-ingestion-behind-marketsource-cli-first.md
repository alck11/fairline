# Ingestion sits behind a MarketSource interface; polymarket-cli is the first backend

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

## Consequences

- Kalshi ingestion is a future `KalshiSource` over their REST API — the
  interface, not the CLI, is the contract.
- `leaderboard()` is wallet **discovery only**: it seeds an append-only
  universe. Treating the leaderboard as the universe would reintroduce the
  survivorship bias ADR-0003 forbids.
- The CLI also has authenticated trading commands; they are out of bounds.
  Live placement remains unimplemented (ADR-0001), and if it is ever built the
  candidate paths (py-clob-client vs CLI) get their own decision.
