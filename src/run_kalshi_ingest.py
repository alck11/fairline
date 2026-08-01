"""
run_kalshi_ingest.py — WP-3 entry point: pulls Kalshi weather+econ markets,
candles, and resolutions into the store (WP-1's schema/upserts).

    python3 src/run_kalshi_ingest.py --category weather --days 14
    python3 src/run_kalshi_ingest.py --category economics --limit 20 --period 1h
    # historical backfill (ADR-0023/0028) -- reaches years back, not ~2 months:
    python3 src/run_kalshi_ingest.py --auth --category weather \
            --historical-series KXRAINNYCM --period 1d

Fetches markets in two passes — `KalshiSource.list_markets(active=True)`
(currently open/tradable) and `list_markets(active=False)` (already
settled) — and merges them (dedup by external_id; the two sets don't
overlap in practice since Kalshi's event-level status is one-or-the-other).
Fetching only the open side would starve resolutions() of any settled
external_id to look up, since an open market has no result yet — this was a
review-blocker bug (WP-3 CHANGES REQUESTED) that meant apply_resolutions was
never reached with real data on any actual run.

For every merged market: `store.upsert_market` + `store.upsert_outcomes`,
then `KalshiSource.candlesticks()` for each of its two outcomes over the
trailing `--days` days at `--period` granularity -> `store.upsert_candles`,
then one batched `KalshiSource.resolutions()` call over every external_id
seen this run -> `store.apply_resolutions` (only markets that have actually
settled produce rows — see KalshiSource.resolutions' docstring; with the
settled-side fetch above, that now includes real rows whenever the window
covers any already-resolved market).

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
import traceback
from datetime import datetime, timedelta, timezone

import store
from ingest_kalshi import (CATEGORY_MAP, KalshiAPIError, KalshiCredentials,
                           KalshiSource)


def run(src: KalshiSource, conn, *, category: str, limit: int, days: int,
        period: str) -> int:
    """Returns the count of markets ingested. Raises KalshiAPIError /
    whatever store.py raises on a genuine failure — callers (main() below)
    decide how to report it; this function does no printing of its own
    beyond per-market progress, so it stays easy to call from a test."""
    open_markets = src.list_markets(category=category, limit=limit, active=True)
    settled_markets = src.list_markets(category=category, limit=limit, active=False)
    # dedup by external_id, open-first: an open and a settled call should
    # never return the same ticker (Kalshi's event-level status is
    # one-or-the-other), but keying on a dict rather than concatenating
    # keeps that assumption from silently double-ingesting if it ever
    # doesn't hold.
    markets_by_id = {m.external_id: m for m in settled_markets}
    markets_by_id.update({m.external_id: m for m in open_markets})
    markets = list(markets_by_id.values())

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


def run_historical(src: KalshiSource, conn, *, series: list[str], category: str,
                   period: str, candle_days: int) -> int:
    """Backfill one or more series from Kalshi's **historical** archive
    (ADR-0023/ADR-0028) rather than the live tier `run()` above reads.

    Three things differ from the live path, each of them load-bearing:

    1. **Listing.** `list_markets` reads `/events`, which retains only about
       the last two months of settled markets. That window — mistaken for the
       venue's entire history in ADR-0016/0018 — is why this project spent a
       cycle believing several research candidates were untestable.
       `historical_markets` reads the archive, which reaches Kalshi's 2021
       inception.

    2. **Resolutions come free.** The historical listing carries `result`
       inline, so no batched `resolutions()` call is needed; issuing one would
       re-fetch hundreds of markets to learn what is already in hand.

    3. **The candle window is per-market, not a trailing window.** `run()`
       asks for the last `--days` days, which is right for markets trading
       now and useless for a market that settled in 2024 — it would return
       zero candles for every row and quietly store a market with no price
       history. Here the window is anchored to each market's own
       `resolves_at`, reaching `candle_days` back from it.

    Returns the number of markets ingested."""
    total = 0
    for series_ticker in series:
        markets, resolutions = src.historical_markets(series_ticker,
                                                      category=category)
        print(f"{series_ticker}: {len(markets)} settled market(s) in the archive")
        for market in markets:
            market_id = store.upsert_market(conn, market)
            store.upsert_outcomes(conn, market_id, market.outcomes)
            candle_count = 0
            if market.resolves_at is not None:
                end = market.resolves_at
                start = end - timedelta(days=candle_days)
                for outcome in market.outcomes:
                    candles = src.candlesticks(outcome.token_id, start=start,
                                               end=end, period=period,
                                               historical=True)
                    store.upsert_candles(conn, candles)
                    candle_count += len(candles)
            print(f"  {market.external_id}: {candle_count} candles")
        if resolutions:
            store.apply_resolutions(conn, resolutions)
        print(f"{series_ticker}: applied {len(resolutions) // 2} resolution(s)")
        total += len(markets)
    return total


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
    parser.add_argument("--historical-series", action="append", dest="historical_series",
                        default=None, metavar="SERIES_TICKER",
                        help="backfill this series from Kalshi's historical archive "
                             "(ADR-0023) instead of the ~2-month live tier; repeat "
                             "for several. Requires --category. e.g. KXRAINNYCM")
    parser.add_argument("--candle-days", type=int, default=90,
                        help="with --historical-series: how far back from each "
                             "market's own resolution to pull candles (default 90). "
                             "A trailing window would return nothing for markets "
                             "that settled years ago.")
    parser.add_argument("--auth", action="store_true",
                        help="sign requests with KalshiCredentials.from_env() "
                             "($KALSHI_API_KEY_ID / $KALSHI_PRIVATE_KEY_PATH). "
                             "Required in practice for the historical tier.")
    args = parser.parse_args(argv)

    if args.historical_series and args.category is None:
        print("--historical-series requires --category (the historical listing "
              "carries no category field of its own -- see "
              "KalshiSource.historical_markets)", file=sys.stderr)
        return 1

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach Postgres via $DATABASE_URL (see README -> "
              f"'Database setup'): {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    try:
        credentials = KalshiCredentials.from_env() if args.auth else None
    except ValueError as e:
        print(f"--auth could not load credentials: {e}", file=sys.stderr)
        conn.close()
        return 1

    src = KalshiSource(credentials=credentials)
    try:
        if args.historical_series:
            n = run_historical(src, conn, series=args.historical_series,
                               category=args.category, period=args.period,
                               candle_days=args.candle_days)
        else:
            n = run(src, conn, category=args.category, limit=args.limit,
                   days=args.days, period=args.period)
    except KalshiAPIError as e:
        print(f"Kalshi API failure: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Last-resort net for this CLI entry point (US-2: "exits non-zero
        # with a clear error on API/rate-limit failure", never a bare
        # traceback). KalshiSource is supposed to translate every malformed
        # Kalshi response into KalshiAPIError, but four rounds of QA/review
        # each found one more untested field that slipped past parse-time
        # validation and only surfaced two layers down as a bare exception
        # out of store.py's Postgres upserts (e.g. psycopg.errors.
        # CheckViolation/NotNullViolation) -- or, in principle, any other
        # Python exception nobody has thought to test yet. This clause is
        # a structural backstop, not a substitute for fixing the source
        # (the closer to the source an error is caught, the better the
        # message -- Part 1 above and the four prior field-specific fixes
        # still matter): it's deliberately broader, and its message
        # deliberately says "unexpected" to distinguish it from
        # KalshiAPIError's specific, well-formed message above. The
        # traceback is printed (not swallowed) for debugging, but the
        # process still exits via this function's normal `return 1` --
        # same class of outcome as the KalshiAPIError branch -- rather than
        # letting the exception itself escape main() uncaught.
        print(f"unexpected error during Kalshi ingest (not a KalshiAPIError -- "
              f"likely an untested malformed-field case; see traceback below): "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"ingested {n} market(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
