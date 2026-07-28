"""
scripts/wp0_history_probe.py — WP-0: how much Kalshi history is actually
retrievable, and does it depend on which endpoint you ask?

Gates every backtest-shaped candidate in
docs/research/2026-07-25-kalshi-category-expansion.md. ADR-0014 found that the
nested-events path (`GET /events?with_nested_markets=true&status=settled`,
which is what `KalshiSource.list_markets` uses) served only ~68 rolling days
of KXHIGHNY, and that "1,171 older HIGHNY- events return no markets". If that
ceiling is a property of *the venue*, every candidate that needs resolved
history is dead and the only path left is forward paper. If it is a property of
*that query path*, the ceiling moves and the candidates live.

Three questions, all answered empirically against the live public API — the
point of this probe is to not take the docs' word for any of it:

  Q1  Does `GET /markets?series_ticker=...&status=settled` reach markets the
      nested-events path cannot? Run head to head on the same series, daily and
      long-dated, and compare depth in days and in resolved-market count.
  Q2  For the *oldest* market each path can reach, is anything served beyond
      the final `result` — candlesticks, public trades? FLB-1 needs only
      `result` plus a traded price, so it can survive a candle blackout that
      would kill MRAIN-1 / HURSEAS-1 / DROUGHT-1.
  Q3  What is the listing-to-resolution window (`close_time - open_time`) for a
      non-NYC temperature series and for a monthly-rain series? ADR-0014's
      ~38h KXHIGHNY window was measured off candlesticks; `open_time` gives it
      directly, so this both cross-checks that measurement and prices MRAIN-1.

Read-only, no database. Builds on `KalshiSource._get` rather than
reimplementing HTTP: this probe needs endpoints and query params `KalshiSource`
deliberately does not expose (`/markets` with `series_ticker`/`min_close_ts`,
`/markets/trades`), but it wants that class's retry/backoff and its
KalshiAPIError contract (ADR-0006/US-2).

Unauthenticated by default. `--auth` signs every request with
`KalshiCredentials.from_env()` (ADR-0018) to test the open question this
probe's first run could not close: ADR-0016 measured a ~68-day settled-history
ceiling against the *public* API, but Bürgi-Deng-Whelan (2026) pulled
2021-2025 Kalshi history after *registering for API access* — so it was never
established whether that ceiling is a venue property or an unauthenticated-tier
property. `--auth` re-runs the identical Q1/Q2/Q3 comparison authenticated so
the two runs are directly diffable.

    python3 scripts/wp0_history_probe.py                  # unauthenticated
    python3 scripts/wp0_history_probe.py --auth            # authenticated
    python3 scripts/wp0_history_probe.py --auth --json out.json
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ingest_kalshi import KalshiAPIError, KalshiCredentials, KalshiSource   # noqa: E402

# Series probed, chosen to separate "venue ceiling" from "query-path ceiling":
# a daily ladder resolves ~365x/yr so a 68-day window still yields a usable
# sample, while a long-dated series resolves once or twice in the same window
# and is therefore where the ceiling actually bites.
DAILY_SERIES = ["KXHIGHNY", "KXHIGHLAX"]
LONG_DATED_SERIES = ["KXNOBELPEACE", "KXHURCTOT", "KXRAINNYCM"]
# Q3 targets: a non-NYC temperature ladder (does ADR-0014's ~38h window
# generalize across the series template?) and a monthly accumulation ladder
# (is MRAIN-1 really listed weeks ahead, as its whole thesis requires?).
WINDOW_SERIES = ["KXHIGHLAX", "KXRAINNYCM"]

MAX_PAGES = 40          # bounded: this is a probe, not a backfill
PAGE_LIMIT = 1000       # GetMarkets' documented maximum
POLITE_SLEEP = 0.25     # be a good citizen on a public unauthenticated API


def _ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _fmt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d") if dt else "—"


def _days_ago(dt: datetime | None, now: datetime) -> float | None:
    return None if dt is None else (now - dt).total_seconds() / 86400.0


# ---------------------------------------------------------------- Q1 --------
def markets_path_depth(src: KalshiSource, series: str, now: datetime) -> dict:
    """Paginate GET /markets?series_ticker=...&status=settled to exhaustion."""
    out: list[dict] = []
    cursor, pages, seen = None, 0, set()
    truncated = False
    while pages < MAX_PAGES:
        pages += 1
        page = src._get("/markets", series_ticker=series, status="settled",
                        limit=PAGE_LIMIT, cursor=cursor)
        batch = page.get("markets") or []
        out.extend(batch)
        nxt = page.get("cursor")
        if not nxt or not batch or nxt in seen:
            break
        seen.add(nxt)
        cursor = nxt
        time.sleep(POLITE_SLEEP)
    else:
        truncated = True

    closes = sorted(c for c in (_ts(m.get("close_time")) for m in out) if c)
    resolved = [m for m in out if m.get("result") in ("yes", "no")]
    return {
        "series": series, "path": "GET /markets?series_ticker",
        "markets": len(out), "resolved": len(resolved), "pages": pages,
        "truncated_at_page_cap": truncated,
        "oldest_close": closes[0] if closes else None,
        "newest_close": closes[-1] if closes else None,
        "span_days": ((closes[-1] - closes[0]).total_seconds() / 86400.0
                      if len(closes) > 1 else None),
        "oldest_close_days_ago": _days_ago(closes[0] if closes else None, now),
        "raw": out,
    }


def events_path_depth(src: KalshiSource, series: str, now: datetime) -> dict:
    """The ADR-0014 path: nested markets under settled events, same series."""
    out: list[dict] = []
    empty_events, total_events = 0, 0
    cursor, pages, seen = None, 0, set()
    truncated = False
    while pages < MAX_PAGES:
        pages += 1
        page = src._get("/events", series_ticker=series, status="settled",
                        with_nested_markets="true", limit=200, cursor=cursor)
        evs = page.get("events") or []
        total_events += len(evs)
        for ev in evs:
            nested = ev.get("markets") or []
            if not nested:
                # ADR-0014's exact symptom: the event is listed but carries no
                # markets, so the resolved outcome is unreachable by this path.
                empty_events += 1
            out.extend(nested)
        nxt = page.get("cursor")
        if not nxt or not evs or nxt in seen:
            break
        seen.add(nxt)
        cursor = nxt
        time.sleep(POLITE_SLEEP)
    else:
        truncated = True

    closes = sorted(c for c in (_ts(m.get("close_time")) for m in out) if c)
    resolved = [m for m in out if m.get("result") in ("yes", "no")]
    return {
        "series": series, "path": "GET /events?with_nested_markets",
        "markets": len(out), "resolved": len(resolved), "pages": pages,
        "events": total_events, "empty_events": empty_events,
        "truncated_at_page_cap": truncated,
        "oldest_close": closes[0] if closes else None,
        "newest_close": closes[-1] if closes else None,
        "span_days": ((closes[-1] - closes[0]).total_seconds() / 86400.0
                      if len(closes) > 1 else None),
        "oldest_close_days_ago": _days_ago(closes[0] if closes else None, now),
    }


# ---------------------------------------------------------------- Q2 --------
def deep_market_payload(src: KalshiSource, market: dict, series: str) -> dict:
    """For one (ideally the oldest reachable) settled market: what survives?

    Checks the three things a backtest could need, independently, because they
    fail independently: the resolution itself, candlesticks, and public trades.
    """
    ticker = market.get("ticker")
    close = _ts(market.get("close_time"))
    open_t = _ts(market.get("open_time"))
    res: dict = {
        "ticker": ticker, "series": series,
        "close": close, "open": open_t,
        "result": market.get("result"),
        "volume": market.get("volume_fp"),
        "has_result": market.get("result") in ("yes", "no"),
    }

    # -- candlesticks over the market's own lifetime, daily bars
    if close and open_t:
        start = open_t - timedelta(days=1)
        end = close + timedelta(days=1)
        try:
            data = src._get(
                f"/series/{series}/markets/{ticker}/candlesticks",
                start_ts=int(start.timestamp()), end_ts=int(end.timestamp()),
                period_interval=1440)
            bars = data.get("candlesticks") or []
            res["candles"] = len(bars)
            res["candles_error"] = None
        except KalshiAPIError as e:
            res["candles"] = 0
            res["candles_error"] = str(e)[:160]
    time.sleep(POLITE_SLEEP)

    # -- public trade feed. Endpoint shape is itself part of the question, so
    #    try the documented one and record verbatim whatever comes back.
    try:
        data = src._get("/markets/trades", ticker=ticker, limit=100)
        trades = data.get("trades") or []
        res["trades"] = len(trades)
        res["trades_error"] = None
        if trades:
            tps = [float(t["yes_price_dollars"]) for t in trades
                   if t.get("yes_price_dollars") is not None]
            res["trade_price_sample"] = tps[:3]
            res["trade_ts_newest"] = trades[0].get("created_time")
    except (KalshiAPIError, KeyError, TypeError, ValueError) as e:
        res["trades"] = 0
        res["trades_error"] = f"{type(e).__name__}: {str(e)[:140]}"
    time.sleep(POLITE_SLEEP)
    return res


# ---------------------------------------------------------------- Q3 --------
def listing_windows(markets: list[dict]) -> dict | None:
    """close_time - open_time across a series, in hours."""
    hrs = []
    for m in markets:
        o, c = _ts(m.get("open_time")), _ts(m.get("close_time"))
        if o and c:
            hrs.append((c - o).total_seconds() / 3600.0)
    if not hrs:
        return None
    hrs.sort()
    n = len(hrs)
    return {"n": n, "min_h": hrs[0], "max_h": hrs[-1],
            "median_h": hrs[n // 2],
            "mean_h": sum(hrs) / n}


# --------------------------------------------------------------- main -------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", help="write the raw probe result to this path")
    ap.add_argument("--auth", action="store_true",
                    help="sign requests with KalshiCredentials.from_env() "
                         "(KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)")
    args = ap.parse_args()

    credentials = KalshiCredentials.from_env() if args.auth else None
    src = KalshiSource(credentials=credentials)
    now = datetime.now(timezone.utc)
    report: dict = {"probed_at": now.isoformat(), "authenticated": args.auth,
                    "q1": [], "q2": [], "q3": []}

    print(f"WP-0 history probe — {now:%Y-%m-%d %H:%M} UTC "
          f"({'AUTHENTICATED' if args.auth else 'unauthenticated'})")
    print(f"base: {src.base_url}\n")

    # -- Q1 ------------------------------------------------------------------
    print("=" * 78)
    print("Q1  How deep is retrievable settled history, and does the path matter?")
    print("=" * 78)
    hdr = (f"{'series':<16}{'path':<34}{'mkts':>6}{'resolved':>9}"
           f"{'oldest':>12}{'d.ago':>7}{'span_d':>8}")
    print(hdr)
    print("-" * len(hdr))
    depths: dict[str, dict] = {}
    for series in DAILY_SERIES + LONG_DATED_SERIES:
        for fn in (markets_path_depth, events_path_depth):
            try:
                d = fn(src, series, now)
            except KalshiAPIError as e:
                print(f"{series:<16}{fn.__name__:<34} FAILED: {str(e)[:60]}")
                continue
            if fn is markets_path_depth:
                depths[series] = d
            span = f"{d['span_days']:.0f}" if d["span_days"] is not None else "—"
            ago = (f"{d['oldest_close_days_ago']:.0f}"
                   if d["oldest_close_days_ago"] is not None else "—")
            print(f"{series:<16}{d['path']:<34}{d['markets']:>6}"
                  f"{d['resolved']:>9}{_fmt(d['oldest_close']):>12}{ago:>7}{span:>8}")
            if d.get("empty_events"):
                print(f"{'':<16}{'  ^ events with no nested markets:':<34}"
                      f"{d['empty_events']:>6} of {d['events']}")
            if d["truncated_at_page_cap"]:
                print(f"{'':<16}{'  ^ HIT THE PAGE CAP — depth is a floor':<34}")
            report["q1"].append({k: (v.isoformat() if isinstance(v, datetime) else v)
                                 for k, v in d.items() if k != "raw"})
        print()

    # -- Q2 ------------------------------------------------------------------
    print("=" * 78)
    print("Q2  On the OLDEST reachable settled market, what data survives?")
    print("=" * 78)
    hdr2 = f"{'series':<16}{'oldest ticker':<30}{'result':>8}{'candles':>9}{'trades':>8}"
    print(hdr2)
    print("-" * len(hdr2))
    for series, d in depths.items():
        raw = [m for m in d["raw"] if _ts(m.get("close_time"))]
        if not raw:
            print(f"{series:<16}(no settled markets reachable)")
            continue
        oldest = min(raw, key=lambda m: _ts(m["close_time"]))
        try:
            p = deep_market_payload(src, oldest, series)
        except KalshiAPIError as e:
            print(f"{series:<16}FAILED: {str(e)[:60]}")
            continue
        print(f"{series:<16}{str(p['ticker'])[:29]:<30}{str(p['result']):>8}"
              f"{p.get('candles', 0):>9}{p.get('trades', 0):>8}")
        for key in ("candles_error", "trades_error"):
            if p.get(key):
                print(f"{'':<16}  {key}: {p[key]}")
        report["q2"].append({k: (v.isoformat() if isinstance(v, datetime) else v)
                             for k, v in p.items()})
    print()

    # -- Q3 ------------------------------------------------------------------
    print("=" * 78)
    print("Q3  Listing-to-resolution window (close_time - open_time)")
    print("=" * 78)
    hdr3 = f"{'series':<16}{'n':>6}{'min_h':>10}{'median_h':>10}{'max_h':>10}"
    print(hdr3)
    print("-" * len(hdr3))
    for series in WINDOW_SERIES:
        d = depths.get(series)
        if d is None:
            try:
                d = markets_path_depth(src, series, now)
                depths[series] = d
            except KalshiAPIError as e:
                print(f"{series:<16}FAILED: {str(e)[:60]}")
                continue
        w = listing_windows(d["raw"])
        if w is None:
            print(f"{series:<16}(no open/close pairs)")
            continue
        print(f"{series:<16}{w['n']:>6}{w['min_h']:>10.1f}"
              f"{w['median_h']:>10.1f}{w['max_h']:>10.1f}")
        report["q3"].append({"series": series, **w})
    print()

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"raw probe result -> {args.json}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KalshiAPIError as e:
        print(f"Kalshi API failure: {e}")
        sys.exit(1)
    except ValueError as e:
        # KalshiCredentials.from_env() raises this on a missing/malformed
        # env var or key file -- surface it plainly rather than a traceback.
        print(f"--auth failed to load credentials: {e}")
        sys.exit(1)
