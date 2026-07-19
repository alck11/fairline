"""
ingest_kalshi.py — MarketDataSource backed by Kalshi's public REST API.

ADR-0006 (updated for the Kalshi pivot): `KalshiSource` reads Kalshi's
**public** trade-api v2 — no trading auth, free — for markets (weather + econ
first), candlesticks, and market resolutions. It implements the narrower
`MarketDataSource` Protocol from ingest.py, not the full `MarketSource`:
`wallet_trades`/`leaderboard` raise `NotImplementedError`, since Kalshi has no
public per-trader feed to back them (see ADR-0006 "Split 2").

Endpoints used (all confirmed live and public 2026-07-18 against
https://external-api.kalshi.com/trade-api/v2 — no API key, no auth headers;
see docs.kalshi.com/api-reference):

    GET /events?with_nested_markets=true&series_ticker=...   -> list_markets
        (category is NOT a server-side filter on this endpoint — verified
        live: passing category= is silently ignored — so KalshiSource filters
        client-side on each event's `category` field instead.)
    GET /markets/{ticker}/orderbook                          -> orderbook
    GET /series/{series_ticker}/markets/{ticker}/candlesticks -> candlesticks
        (the `/historical/markets/{ticker}/candlesticks` variant 404s for
        markets that haven't crossed Kalshi's historical-archive cutoff yet —
        confirmed live — so this module always uses the series-scoped
        endpoint, resolving `series_ticker` via GET /markets/{ticker} then
        GET /events/{event_ticker} and caching the result.)
    GET /markets?tickers=...                                 -> resolutions

Token id scheme: Kalshi has no separate per-side token id (unlike Polymarket's
CLOB token ids) — YES/NO are just sides of one `ticker`. This module
synthesizes `f"{ticker}-YES"` / `f"{ticker}-NO"` as `token_id`, matching the
convention store.py's own demo/tests already use for Kalshi outcomes.

Graceful degradation (ADR-0006, US-2): every HTTP call retries transient
failures (429 / 5xx) with exponential backoff, then raises `KalshiAPIError` —
a plain RuntimeError subclass any caller can catch. The `__main__` entry
point below catches it at the top level and exits non-zero with a clear
message; nothing here calls `sys.exit` on its own path.

Demo: `python3 src/ingest_kalshi.py` fetches a few live weather markets, an
orderbook, and one candlestick window against the real public API (network
required; no auth). Fixture-based, network-free tests live in
tests/test_ingest_kalshi.py.
"""
from __future__ import annotations
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Sequence

from ingest import BookSnapshot, Candle, MarketRow, OutcomeRef, ResolutionRow

DEFAULT_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# fairline's lowercase category vocabulary (see FakeSource: 'weather',
# 'politics') mapped to Kalshi's `event.category` values — confirmed live
# 2026-07-18 via GET /events (weather + econ first, ADR-0006).
CATEGORY_MAP = {
    "weather": "Climate and Weather",
    "economics": "Economics",
}

# Kalshi's period_interval query param is candlestick duration in MINUTES,
# restricted to exactly these three values (confirmed via docs.kalshi.com).
PERIOD_MINUTES = {"1m": 1, "1h": 60, "1d": 1440}

# statuses GetMarkets/GetEvents treat as "resolved" — result is only
# meaningful once a market has left the tradable lifecycle.
RESOLVED_STATUSES = {"finalized", "settled", "determined"}


class KalshiAPIError(RuntimeError):
    """Raised on an unrecoverable Kalshi API failure: HTTP error, rate limit
    exhausted after retries, or a malformed response. A plain RuntimeError
    subclass so a caller (the ingest entry point below, or a future WP-4
    caller) can catch specifically this and degrade gracefully — clear
    message, non-zero exit — rather than crashing on a bare traceback
    (ADR-0006 / US-2)."""


class KalshiSource:
    """MarketDataSource implementation over Kalshi's public REST API. Data
    only — no order placement anywhere in this class, and none of its
    methods ever will (ADR-0006's data/execution split)."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, *, timeout: float = 15.0,
                 max_retries: int = 4, backoff: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        # ticker -> series_ticker, populated as a side effect of list_markets
        # (each event already carries series_ticker) and by candlesticks()'s
        # own lookup on a cache miss — avoids two extra round trips per call
        # for every market a caller already discovered via list_markets.
        self._series_cache: dict[str, str] = {}

    # -- plumbing --------------------------------------------------------
    def _get(self, path: str, **params) -> dict:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429 or e.code >= 500:
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                raise KalshiAPIError(
                    f"Kalshi API error {e.code} for {url}: {e.reason}") from e
            except urllib.error.URLError as e:
                last_err = e
                time.sleep(self.backoff * (2 ** attempt))
            except (json.JSONDecodeError, TimeoutError) as e:
                last_err = e
                time.sleep(self.backoff * (2 ** attempt))
        raise KalshiAPIError(
            f"Kalshi API unreachable after {self.max_retries} attempt(s): "
            f"{url} ({type(last_err).__name__}: {last_err})") from last_err

    @staticmethod
    def _dollars(s: str | None) -> float | None:
        if s in (None, ""):
            return None
        return float(s)

    @staticmethod
    def _ts(raw: str | None) -> datetime | None:
        if not raw:
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    @staticmethod
    def _split_token(token_id: str) -> tuple[str, str]:
        """'<ticker>-YES' / '<ticker>-NO' -> (ticker, 'yes'|'no'). Splits on
        the trailing suffix only (market tickers themselves contain '-', so
        this can't split on the first/every dash)."""
        if token_id.endswith("-YES"):
            return token_id[:-len("-YES")], "yes"
        if token_id.endswith("-NO"):
            return token_id[:-len("-NO")], "no"
        raise ValueError(
            f"unrecognized Kalshi token_id {token_id!r} — expected "
            f"'<ticker>-YES' or '<ticker>-NO' (KalshiSource's synthesized "
            f"per-side id; see module docstring)")

    def _series_ticker(self, ticker: str) -> str:
        if ticker in self._series_cache:
            return self._series_cache[ticker]
        market = self._get(f"/markets/{ticker}")["market"]
        event_ticker = market["event_ticker"]
        event = self._get(f"/events/{event_ticker}")["event"]
        series_ticker = event["series_ticker"]
        self._series_cache[ticker] = series_ticker
        return series_ticker

    # -- parsing (single place that knows Kalshi's JSON shapes) -----------
    @staticmethod
    def _parse_market(m: dict, category: str) -> MarketRow:
        ticker = m["ticker"]
        outcomes = (
            OutcomeRef(f"{ticker}-YES", m.get("yes_sub_title") or "YES", 0),
            OutcomeRef(f"{ticker}-NO", m.get("no_sub_title") or "NO", 1),
        )
        return MarketRow(
            venue="kalshi",
            external_id=ticker,
            question=m.get("title") or "",
            category=category,
            resolution_text=m.get("rules_primary"),
            resolves_at=KalshiSource._ts(m.get("close_time")),
            outcomes=outcomes,
        )

    # -- MarketDataSource --------------------------------------------------
    def list_markets(self, *, active: bool = True, category: str | None = None,
                     limit: int = 50) -> list[MarketRow]:
        """Weather + econ only (ADR-0006's MVP scope for this adapter):
        `category=None` returns both supported categories, not every Kalshi
        category — sports/politics/crypto/etc. are out of this adapter's
        scope, and silently returning them would misrepresent what
        KalshiSource covers. Unknown categories raise ValueError rather than
        silently returning nothing."""
        if category is not None and category not in CATEGORY_MAP:
            raise ValueError(
                f"KalshiSource only covers {sorted(CATEGORY_MAP)} in the MVP "
                f"(ADR-0006), got category={category!r}")
        wanted = [category] if category else list(CATEGORY_MAP)
        wanted_kalshi = {CATEGORY_MAP[c] for c in wanted}

        status = "open" if active else None
        rows: list[MarketRow] = []
        cursor = None
        while len(rows) < limit:
            page = self._get("/events", with_nested_markets="true", status=status,
                             limit=min(200, limit), cursor=cursor)
            events = page.get("events") or []
            for ev in events:
                if ev.get("category") not in wanted_kalshi:
                    continue
                fair_category = next(k for k, v in CATEGORY_MAP.items()
                                     if v == ev["category"])
                for m in ev.get("markets") or []:
                    rows.append(self._parse_market(m, fair_category))
                    self._series_cache[m["ticker"]] = ev["series_ticker"]
                    if len(rows) >= limit:
                        break
                if len(rows) >= limit:
                    break
            cursor = page.get("cursor")
            if not cursor or not events:
                break
        return rows[:limit]

    def orderbook(self, token_id: str) -> BookSnapshot:
        ticker, side = self._split_token(token_id)
        data = self._get(f"/markets/{ticker}/orderbook")["orderbook_fp"]
        yes_levels = [(self._dollars(p), float(sz))
                      for p, sz in (data.get("yes_dollars") or [])]
        no_levels = [(self._dollars(p), float(sz))
                     for p, sz in (data.get("no_dollars") or [])]
        # a resting bid for the OTHER side at price q is equivalent to a
        # resting ask for THIS side at price (1 - q) — Kalshi's YES/NO
        # complementary pricing (the orderbook endpoint's own documented
        # note); see module docstring.
        if side == "yes":
            bids, asks_raw = yes_levels, no_levels
        else:
            bids, asks_raw = no_levels, yes_levels
        asks = [(round(1.0 - p, 4), sz) for p, sz in asks_raw]
        bids_sorted = tuple(sorted(bids, key=lambda l: -l[0]))
        asks_sorted = tuple(sorted(asks, key=lambda l: l[0]))
        return BookSnapshot(ts=datetime.now(timezone.utc), token_id=token_id,
                            bids=bids_sorted, asks=asks_sorted)

    def candlesticks(self, token_id: str, *, start: datetime, end: datetime,
                     period: str = "1h") -> list[Candle]:
        if period not in PERIOD_MINUTES:
            raise ValueError(
                f"period must be one of {sorted(PERIOD_MINUTES)}, got {period!r}")
        ticker, side = self._split_token(token_id)
        series_ticker = self._series_ticker(ticker)
        data = self._get(
            f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            start_ts=int(start.timestamp()), end_ts=int(end.timestamp()),
            period_interval=PERIOD_MINUTES[period],
        )
        candles = []
        for c in data.get("candlesticks") or []:
            price = c.get("price") or {}
            o, h, l, cl = (self._dollars(price.get("open_dollars")),
                          self._dollars(price.get("high_dollars")),
                          self._dollars(price.get("low_dollars")),
                          self._dollars(price.get("close_dollars")))
            if None in (o, h, l, cl):
                # no trades in this bar (Kalshi's `price` fields are null
                # when nothing traded) -- fall back to the yes bid/ask
                # midpoint so a quiet bar doesn't just vanish from the series.
                yb, ya = c.get("yes_bid") or {}, c.get("yes_ask") or {}
                mid = lambda k: (
                    (self._dollars(yb.get(k)) or 0) + (self._dollars(ya.get(k)) or 0)
                ) / 2.0
                o = o if o is not None else mid("open_dollars")
                h = h if h is not None else mid("high_dollars")
                l = l if l is not None else mid("low_dollars")
                cl = cl if cl is not None else mid("close_dollars")
            volume = self._dollars(c.get("volume_fp"))
            ts = datetime.fromtimestamp(c["end_period_ts"], tz=timezone.utc)
            if side == "yes":
                candles.append(Candle(ts, token_id, o, h, l, cl, volume))
            else:
                # NO is the complement of YES (Kalshi's yes+no == 1 pricing;
                # see module docstring / orderbook()); high/low invert.
                candles.append(Candle(
                    ts, token_id,
                    open=1.0 - o, high=1.0 - l, low=1.0 - h, close=1.0 - cl,
                    volume=volume))
        return candles

    def resolutions(self, external_ids: Sequence[str]) -> list[ResolutionRow]:
        if not external_ids:
            return []
        rows: list[ResolutionRow] = []
        # GetMarkets' `tickers` filter is documented for a bounded batch; chunk
        # defensively so a large backfill can't build one oversized URL.
        chunk_size = 100
        ids = list(external_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            data = self._get("/markets", tickers=",".join(chunk),
                             limit=len(chunk))
            for m in data.get("markets") or []:
                if m.get("status") not in RESOLVED_STATUSES:
                    continue
                result = m.get("result")
                if result not in ("yes", "no"):
                    continue
                ticker = m["ticker"]
                resolved_at = self._ts(m.get("close_time"))
                yes_value = 1.0 if result == "yes" else 0.0
                rows.append(ResolutionRow(ticker, f"{ticker}-YES", yes_value, resolved_at))
                rows.append(ResolutionRow(ticker, f"{ticker}-NO", 1.0 - yes_value, resolved_at))
        return rows

    # -- MarketDataSource explicitly does NOT cover wallet discovery -------
    def wallet_trades(self, wallet: str, limit: int = 100):
        raise NotImplementedError("Kalshi exposes no public per-trader feed")

    def leaderboard(self, *, period: str = "month", order_by: str = "pnl"):
        raise NotImplementedError("Kalshi exposes no public per-trader feed")


if __name__ == "__main__":
    from datetime import timedelta

    src = KalshiSource()
    try:
        markets = src.list_markets(category="weather", limit=3)
        if not markets:
            print("no open weather markets returned — Kalshi API reachable "
                  "but empty result (unusual but not an error)")
        for m in markets:
            print(f"[{m.category}] {m.question}  outcomes="
                  f"{[o.label for o in m.outcomes]}")
        if markets and markets[0].outcomes:
            tok = markets[0].outcomes[0].token_id
            book = src.orderbook(tok)
            print(f"book {tok}: bid={book.best_bid} ask={book.best_ask} "
                  f"({len(book.bids)}x{len(book.asks)} levels)")
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=2)
            candles = src.candlesticks(tok, start=start, end=end, period="1h")
            print(f"candles {tok}: {len(candles)} bars in the last 2 days")
    except KalshiAPIError as e:
        print(f"Kalshi API failure: {e}")
        sys.exit(1)
