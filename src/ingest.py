"""
ingest.py — the MarketSource interface: how market data enters fairline.

Every ingestion backend (polymarket-cli subprocess today, direct HTTP later,
Kalshi REST eventually) implements this Protocol, so the rest of the stack
never knows where a row came from. Row dataclasses are shaped for the schema
tables they fill (see schema/001_schema.sql):

    MarketRow      -> market (+ outcome rows via .outcomes)
    BookSnapshot   -> orderbook_snapshot ; .asks/.bids feed detector.vwap_fill
    PricePoint     -> orderbook_snapshot backfill (best bid/ask only)
    WalletTradeRow -> wallet_trade ; columns match wallet_features.REQUIRED

Wallet-universe discipline (ADR-0003): `leaderboard()` is DISCOVERY ONLY.
It seeds an append-only universe — once a wallet is seen it is never dropped,
even if it goes silent. Feeding only currently-hot wallets into scoring
systematically overstates everyone's skill.

Demo: `python3 src/ingest.py` runs against a synthetic FakeSource (no binary,
no network), matching the repo convention that every module self-demos.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Sequence

Level = tuple[float, float]          # (price, size) — same shape detector uses


# ---------------------------------------------------------------------------
# row types (each maps to one schema table)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OutcomeRef:
    """One tradable outcome of a market. `token_id` is the venue's id for it
    (Polymarket CLOB token id / Kalshi ticker side)."""
    token_id: str
    label: str                        # 'YES','NO' or candidate name
    idx: int                          # position within the market


@dataclass(frozen=True)
class MarketRow:
    venue: str                        # 'polymarket' | 'kalshi'
    external_id: str                  # venue's own market id
    question: str
    category: str
    resolution_text: str | None = None
    resolves_at: datetime | None = None
    outcomes: tuple[OutcomeRef, ...] = ()


@dataclass(frozen=True)
class BookSnapshot:
    ts: datetime
    token_id: str
    bids: tuple[Level, ...]           # sorted best-first (descending price)
    asks: tuple[Level, ...]           # sorted best-first (ascending price)

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None


@dataclass(frozen=True)
class PricePoint:
    ts: datetime
    token_id: str
    price: float


@dataclass(frozen=True)
class WalletTradeRow:
    """One resolved position, normalized per the glossary: every position is a
    BUY of an outcome (a sell of YES arrives here as a buy of NO)."""
    wallet: str
    external_market_id: str
    category: str
    token_id: str                     # the outcome bought
    size: float
    entry_price: float
    entry_ts: datetime
    resolve_ts: datetime | None = None
    resolved_value: float | None = None   # 1.0/0.0 once settled
    fee_paid: float = 0.0


# ---------------------------------------------------------------------------
# the interface
# ---------------------------------------------------------------------------
class MarketSource(Protocol):
    """A backend that can answer fairline's five ingestion questions."""

    def list_markets(self, *, active: bool = True, category: str | None = None,
                     limit: int = 50) -> list[MarketRow]: ...

    def orderbook(self, token_id: str) -> BookSnapshot: ...

    def price_history(self, token_id: str,
                      interval: str = "1d") -> list[PricePoint]: ...

    def wallet_trades(self, wallet: str,
                      limit: int = 100) -> list[WalletTradeRow]: ...

    def leaderboard(self, *, period: str = "month",
                    order_by: str = "pnl") -> list[str]:
        """Wallet addresses for DISCOVERY only — append to the universe,
        never treat as the universe."""
        ...


# ---------------------------------------------------------------------------
# synthetic backend for demos/tests
# ---------------------------------------------------------------------------
class FakeSource:
    """Deterministic in-memory MarketSource so demos and routing tests run
    with no binary and no network."""

    def __init__(self) -> None:
        self._now = datetime(2026, 7, 11, tzinfo=timezone.utc)

    def list_markets(self, *, active: bool = True, category: str | None = None,
                     limit: int = 50) -> list[MarketRow]:
        rows = [
            MarketRow("polymarket", "cond-abc", "Will it rain in NYC on Jul 12?",
                      "weather", outcomes=(OutcomeRef("tok-yes", "YES", 0),
                                           OutcomeRef("tok-no", "NO", 1))),
            MarketRow("polymarket", "cond-def", "Will X win the primary?",
                      "politics", outcomes=(OutcomeRef("tok-p-yes", "YES", 0),
                                            OutcomeRef("tok-p-no", "NO", 1))),
        ]
        if category:
            rows = [r for r in rows if r.category == category]
        return rows[:limit]

    def orderbook(self, token_id: str) -> BookSnapshot:
        return BookSnapshot(self._now, token_id,
                            bids=((0.41, 120.0), (0.39, 300.0)),
                            asks=((0.43, 80.0), (0.45, 250.0)))

    def price_history(self, token_id: str,
                      interval: str = "1d") -> list[PricePoint]:
        return [PricePoint(self._now, token_id, 0.40 + 0.01 * i)
                for i in range(3)]

    def wallet_trades(self, wallet: str,
                      limit: int = 100) -> list[WalletTradeRow]:
        return [WalletTradeRow(wallet, "cond-abc", "weather", "tok-yes",
                               size=100.0, entry_price=0.32,
                               entry_ts=self._now, resolve_ts=self._now,
                               resolved_value=1.0, fee_paid=0.70)]

    def leaderboard(self, *, period: str = "month",
                    order_by: str = "pnl") -> list[str]:
        return ["0xaaa", "0xbbb", "0xccc"]


if __name__ == "__main__":
    src: MarketSource = FakeSource()
    for m in src.list_markets(category="weather"):
        print(f"market : [{m.venue}] {m.question}  outcomes="
              f"{[o.label for o in m.outcomes]}")
        book = src.orderbook(m.outcomes[0].token_id)
        print(f"book   : bid={book.best_bid} ask={book.best_ask} "
              f"depth={len(book.asks)} ask levels")
    print("discover:", src.leaderboard())
    t = src.wallet_trades("0xaaa")[0]
    print(f"trade  : {t.wallet} bought {t.size:.0f} of {t.token_id} "
          f"@ {t.entry_price}")
