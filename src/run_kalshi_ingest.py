"""
run_kalshi_ingest.py — WP-3 entry point: pulls Kalshi weather+econ markets,
candles, and resolutions into the store (WP-1's schema/upserts).

    python3 src/run_kalshi_ingest.py --category weather --days 14
    python3 src/run_kalshi_ingest.py --category economics --limit 20 --period 1h

For every market `KalshiSource.list_markets()` returns: `store.upsert_market`
+ `store.upsert_outcomes`, then `KalshiSource.candlesticks()` for each of its
two outcomes over the trailing `--days` days at `--period` granularity ->
`store.upsert_candles`, then one batched `KalshiSource.resolutions()` call
over every external_id seen this run -> `store.apply_resolutions` (only
markets that have actually settled produce rows — see
KalshiSource.resolutions' docstring).

Needs a real Postgres reachable via $DATABASE_URL (README -> "Database
setup") and live network access to Kalshi's public API — no auth/API key.
Degrades gracefully on either being unavailable: a clear message on stderr
and a non-zero exit (ADR-0006 / US-2), never a bare traceback.

This script is data-only, matching KalshiSource: it never computes EV,
sizing, or a trading signal (that starts at WP-4) and never places an order.
"""
from __future__ import annotations
import argparse
import sys
from datetime import datetime, timedelta, timezone

import store
from ingest_kalshi import CATEGORY_MAP, KalshiAPIError, KalshiSource


def run(src: KalshiSource, conn, *, category: str, limit: int, days: int,
        period: str) -> int:
    """Returns the count of markets ingested. Raises KalshiAPIError /
    whatever store.py raises on a genuine failure — callers (main() below)
    decide how to report it; this function does no printing of its own
    beyond per-market progress, so it stays easy to call from a test."""
    markets = src.list_markets(category=category, limit=limit)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    external_ids = []

    for market in markets:
        market_id = store.upsert_market(conn, market)
        store.upsert_outcomes(conn, market_id, market.outcomes)
        external_ids.append(market.external_id)

        candle_count = 0
        for outcome in market.outcomes:
            candles = src.candlesticks(outcome.token_id, start=start, end=end,
                                       period=period)
            store.upsert_candles(conn, candles)
            candle_count += len(candles)
        print(f"  {market.external_id}: {len(market.outcomes)} outcomes, "
              f"{candle_count} candles")

    resolutions = src.resolutions(external_ids)
    if resolutions:
        store.apply_resolutions(conn, resolutions)
    print(f"resolved {len(resolutions) // 2} of {len(markets)} markets "
          f"(2 outcome rows each)")
    return len(markets)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull Kalshi weather+econ markets, candles, and "
                    "resolutions into the store (WP-3).")
    parser.add_argument("--category", choices=sorted(CATEGORY_MAP), default=None,
                        help="restrict to one MVP category; default pulls both")
    parser.add_argument("--limit", type=int, default=50,
                        help="max markets to ingest (default 50)")
    parser.add_argument("--days", type=int, default=7,
                        help="trailing window of candle history in days (default 7)")
    parser.add_argument("--period", choices=("1m", "1h", "1d"), default="1h",
                        help="candlestick granularity (default 1h)")
    args = parser.parse_args(argv)

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach Postgres via $DATABASE_URL (see README -> "
              f"'Database setup'): {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    src = KalshiSource()
    try:
        n = run(src, conn, category=args.category, limit=args.limit,
               days=args.days, period=args.period)
    except KalshiAPIError as e:
        print(f"Kalshi API failure: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"ingested {n} market(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
