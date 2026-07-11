"""
ingest_polymarket_cli.py — MarketSource backed by the official polymarket-cli.

Shells out to the Rust CLI (https://github.com/Polymarket/polymarket-cli) with
`-o json`. All commands used here are the CLI's NO-AUTH public-data surface —
no wallet, no keys, no custody — which keeps ingestion consistent with the
paper-first gate (ADR-0001). The interface/HTTP trade-off is ADR-0006.

    markets list/search      -> list_markets
    clob book TOKEN_ID       -> orderbook
    clob price-history       -> price_history
    data trades 0xWALLET     -> wallet_trades
    data leaderboard         -> leaderboard (wallet DISCOVERY only, ADR-0003)

Binary discovery: pass `binary=` explicitly, set $POLYMARKET_CLI, or have
`polymarket` on PATH. Kalshi has no CLI equivalent; a KalshiSource will be a
separate MarketSource implementation over their REST API.

Demo: `python3 src/ingest_polymarket_cli.py` — fetches 3 live markets and one
orderbook if the binary is installed; otherwise prints why and exits 0.

NOTE: JSON field names below follow the CLI's documented output but are
isolated in the small `_parse_*` helpers — if a CLI release renames a field,
that is the only place to touch.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from ingest import (BookSnapshot, MarketRow, OutcomeRef, PricePoint,
                    WalletTradeRow)

INSTALL_HINT = ("polymarket-cli not found. Install the Rust CLI from "
                "https://github.com/Polymarket/polymarket-cli and either put "
                "`polymarket` on PATH or set $POLYMARKET_CLI to the binary.")


class PolymarketCliSource:
    """MarketSource implementation over `polymarket -o json ...`."""

    def __init__(self, binary: str | None = None, timeout: float = 30.0):
        self.binary = binary or os.environ.get("POLYMARKET_CLI") or "polymarket"
        self.timeout = timeout
        if shutil.which(self.binary) is None:
            raise FileNotFoundError(INSTALL_HINT)

    # -- plumbing ------------------------------------------------------------
    def _run(self, *args: str):
        cmd = [self.binary, "-o", "json", *args]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self.timeout)
        if proc.returncode != 0:
            raise RuntimeError(
                f"{' '.join(cmd)} failed ({proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}")
        return json.loads(proc.stdout)

    @staticmethod
    def _ts(raw) -> datetime:
        if raw is None:
            return datetime.now(timezone.utc)
        if isinstance(raw, (int, float)):                 # epoch seconds
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))

    # -- parsing (single place that knows the CLI's JSON shapes) -------------
    @staticmethod
    def _parse_market(m: dict) -> MarketRow:
        outs = tuple(
            OutcomeRef(token_id=str(t), label=str(lbl), idx=i)
            for i, (t, lbl) in enumerate(
                zip(m.get("clobTokenIds") or m.get("tokens") or [],
                    m.get("outcomes") or []))
        )
        return MarketRow(
            venue="polymarket",
            external_id=str(m.get("conditionId") or m.get("id")),
            question=m.get("question") or m.get("title") or "",
            category=(m.get("category") or "other").lower(),
            resolution_text=m.get("description"),
            resolves_at=(PolymarketCliSource._ts(m["endDate"])
                         if m.get("endDate") else None),
            outcomes=outs,
        )

    # -- MarketSource --------------------------------------------------------
    def list_markets(self, *, active: bool = True, category: str | None = None,
                     limit: int = 50) -> list[MarketRow]:
        args = ["markets", "list", "--limit", str(limit)]
        if active:
            args.append("--active")
        data = self._run(*args)
        rows = [self._parse_market(m) for m in data]
        if category:
            rows = [r for r in rows if r.category == category.lower()]
        return rows

    def orderbook(self, token_id: str) -> BookSnapshot:
        data = self._run("clob", "book", token_id)
        mk = lambda side: tuple(
            (float(l["price"]), float(l["size"])) for l in data.get(side, []))
        bids = tuple(sorted(mk("bids"), key=lambda l: -l[0]))
        asks = tuple(sorted(mk("asks"), key=lambda l: l[0]))
        return BookSnapshot(ts=self._ts(data.get("timestamp")),
                            token_id=token_id, bids=bids, asks=asks)

    def price_history(self, token_id: str,
                      interval: str = "1d") -> list[PricePoint]:
        data = self._run("clob", "price-history", token_id,
                         "--interval", interval)
        pts = data.get("history", data) if isinstance(data, dict) else data
        return [PricePoint(self._ts(p.get("t") or p.get("timestamp")),
                           token_id, float(p.get("p") or p.get("price")))
                for p in pts]

    def wallet_trades(self, wallet: str,
                      limit: int = 100) -> list[WalletTradeRow]:
        data = self._run("data", "trades", wallet, "--limit", str(limit))
        rows = []
        for t in data:
            # glossary invariant: every position is a BUY of an outcome.
            # The CLI reports SELLs too; a sell is exposure reduction, not a
            # new position — hold-to-resolution scoring ignores it (CONTEXT.md
            # -> PnL), so only BUY prints become WalletTradeRows.
            if str(t.get("side", "BUY")).upper() != "BUY":
                continue
            rows.append(WalletTradeRow(
                wallet=wallet,
                external_market_id=str(t.get("conditionId") or t.get("market")),
                category=(t.get("category") or "other").lower(),
                token_id=str(t.get("asset") or t.get("tokenId")),
                size=float(t.get("size", 0)),
                entry_price=float(t.get("price", 0)),
                entry_ts=self._ts(t.get("timestamp")),
                fee_paid=float(t.get("fee", 0) or 0),
            ))
        return rows

    def leaderboard(self, *, period: str = "month",
                    order_by: str = "pnl") -> list[str]:
        data = self._run("data", "leaderboard",
                         "--period", period, "--order-by", order_by)
        return [str(e.get("proxyWallet") or e.get("wallet") or e.get("address"))
                for e in data]


if __name__ == "__main__":
    try:
        src = PolymarketCliSource()
    except FileNotFoundError as e:
        print(f"skip: {e}")
        sys.exit(0)

    markets = src.list_markets(limit=3)
    for m in markets:
        print(f"[{m.category}] {m.question}")
    if markets and markets[0].outcomes:
        tok = markets[0].outcomes[0].token_id
        book = src.orderbook(tok)
        print(f"book {tok}: bid={book.best_bid} ask={book.best_ask} "
              f"({len(book.bids)}x{len(book.asks)} levels)")
