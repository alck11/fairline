"""
tests/test_ingest_kalshi_qa_round6.py — QA round 6 (closing pass) on
src/ingest_kalshi.py. Independent re-verification of the round-5/9034a37
midpoint-fallback range-check fix using fresh fixtures (not the committed
regression test's literal values), plus a fresh adversarial pass per the
round-6 QA brief:

  1. Independent midpoint-fallback out-of-range repro (asymmetric per-field,
     includes a small negative value rather than the committed test's large
     uniform 5.0/9.0).
  2. Legitimate paths unaffected: a normal traded bar, and a normal
     no-trade bar with valid in-range bid/ask.
  3. Adversarial: BOTH primary (price.*) and fallback (yes_bid/yes_ask)
     completely absent/null simultaneously in the same candle.
  4. orderbook() with a completely empty book (no yes/no levels at all).
  5. list_markets() page-cap/cursor-repeat behavior with category=None
     (both categories requested).
  6. wallet_trades / leaderboard NotImplementedError.

Standalone, no pytest dependency (repo convention). NO LIVE NETWORK — reuses
tests/test_ingest_kalshi.py's fixture-router pattern.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from ingest_kalshi import KalshiAPIError, KalshiSource  # noqa: E402
from test_ingest_kalshi import _load, install_fixture_router, check  # noqa: E402


def test_qa6_midpoint_fallback_asymmetric_out_of_range_raises():
    """Independent repro of the round-5/9034a37 bug, deliberately NOT reusing
    the committed test's fixture values. Three fields (open/high/close) are
    valid in-range midpoints; only `low_dollars` is malformed, and it's
    malformed by being slightly NEGATIVE (mid = -0.05) rather than wildly out
    of range like the committed 5.0/9.0 case -- this exercises the boundary
    of the [0, 1] check, not just an obviously-absurd value, and confirms the
    per-field loop doesn't get short-circuited by the other three fields
    being fine."""
    def router(path, query):
        if path == "/markets/KXHIGHNY-26JUL19-T80":
            return _load("market_single.json")
        if path == "/events/KXHIGHNY-26JUL19":
            return _load("event_single.json")
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{
                "price": {"open_dollars": None, "high_dollars": None,
                          "low_dollars": None, "close_dollars": None},
                "yes_bid": {"open_dollars": "0.40", "high_dollars": "0.50",
                           "low_dollars": "-0.20", "close_dollars": "0.30"},
                "yes_ask": {"open_dollars": "0.60", "high_dollars": "0.70",
                           "low_dollars": "0.10", "close_dollars": "0.50"},
                "volume_fp": "5", "end_period_ts": 1784620800,
            }]}
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        try:
            candles = src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start,
                                       end=end, period="1h")
            raise AssertionError(
                f"expected KalshiAPIError for low_dollars midpoint "
                f"(-0.20+0.10)/2 = -0.05, out of [0,1], but got: {candles!r}")
        except KalshiAPIError as e:
            check("low_dollars" in str(e) and "-0.05" in str(e),
                  f"error should name the offending field/value: {e}")
    finally:
        restore()


def test_qa6_normal_traded_bar_produces_correct_candle():
    """Legitimate path 1: a bar with real (non-null) trade data. Confirms the
    fix didn't disturb the primary parsing path -- YES side values pass
    through untouched, NO side is the exact 1-x complement with high/low
    swapped."""
    def router(path, query):
        if path == "/markets/KXHIGHNY-26JUL19-T80":
            return _load("market_single.json")
        if path == "/events/KXHIGHNY-26JUL19":
            return _load("event_single.json")
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{
                "price": {"open_dollars": "0.30", "high_dollars": "0.45",
                          "low_dollars": "0.25", "close_dollars": "0.40"},
                "volume_fp": "123.4", "end_period_ts": 1784620800,
            }]}
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)

        yes_candles = src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start,
                                       end=end, period="1h")
        check(len(yes_candles) == 1, f"expected 1 candle, got {len(yes_candles)}")
        c = yes_candles[0]
        check((c.open, c.high, c.low, c.close) == (0.30, 0.45, 0.25, 0.40),
              f"YES candle OHLC mismatch: {c}")
        check(c.volume == 123.4, f"volume mismatch: {c.volume}")

        no_candles = src.candlesticks("KXHIGHNY-26JUL19-T80-NO", start=start,
                                      end=end, period="1h")
        c2 = no_candles[0]
        check((round(c2.open, 10), round(c2.high, 10), round(c2.low, 10), round(c2.close, 10))
              == (0.70, 0.75, 0.55, 0.60),
              f"NO candle should be 1-x complement w/ high<->low swap: {c2}")
    finally:
        restore()


def test_qa6_normal_no_trade_bar_valid_midpoint_produces_candle():
    """Legitimate path 2: a genuine quiet bar (price.* all null, as Kalshi
    documents for no-trade bars) with a normal, valid, in-range yes_bid/
    yes_ask quote. Confirms the fallback + its new range-check still let a
    correct, real value through -- the fix must not have turned into an
    overly aggressive check that also rejects valid data."""
    def router(path, query):
        if path == "/markets/KXHIGHNY-26JUL19-T80":
            return _load("market_single.json")
        if path == "/events/KXHIGHNY-26JUL19":
            return _load("event_single.json")
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{
                "price": {"open_dollars": None, "high_dollars": None,
                          "low_dollars": None, "close_dollars": None},
                "yes_bid": {"open_dollars": "0.20", "high_dollars": "0.25",
                           "low_dollars": "0.18", "close_dollars": "0.22"},
                "yes_ask": {"open_dollars": "0.24", "high_dollars": "0.29",
                           "low_dollars": "0.22", "close_dollars": "0.26"},
                "volume_fp": "0", "end_period_ts": 1784620800,
            }]}
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        candles = src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start,
                                   end=end, period="1h")
        check(len(candles) == 1, f"expected 1 candle, got {len(candles)}")
        c = candles[0]
        # open midpoint = (0.20+0.24)/2 = 0.22, etc.
        check((c.open, c.high, c.low, c.close) == (0.22, 0.27, 0.20, 0.24),
              f"midpoint fallback OHLC mismatch: {c}")
    finally:
        restore()


def test_qa6_both_primary_and_fallback_null_simultaneously():
    """Adversarial: price.* is entirely null (no trades) AND yes_bid/yes_ask
    are ALSO entirely absent (not just one-sided -- fully missing keys).
    mid() treats a missing side as 0 for each field, so BOTH sides are
    missing -> midpoint is exactly 0.0 for every field. 0.0 passes the
    [0, 1] range check (it's the boundary, not outside it), so this reports
    what it actually observes rather than asserting a bug -- but the
    assertion pins the current, documented-by-code-comment behavior (see
    ingest_kalshi.py's KNOWN GAP note on mid()) so any change here (e.g. if
    a future patch decides to raise instead) is a visible, deliberate
    change, not a silent regression."""
    def router(path, query):
        if path == "/markets/KXHIGHNY-26JUL19-T80":
            return _load("market_single.json")
        if path == "/events/KXHIGHNY-26JUL19":
            return _load("event_single.json")
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{
                "price": {"open_dollars": None, "high_dollars": None,
                          "low_dollars": None, "close_dollars": None},
                # yes_bid / yes_ask keys entirely absent -- not just an
                # empty dict on one side.
                "volume_fp": "0", "end_period_ts": 1784620800,
            }]}
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        candles = src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start,
                                   end=end, period="1h")
        check(len(candles) == 1, f"expected 1 candle, got {len(candles)}")
        c = candles[0]
        check((c.open, c.high, c.low, c.close) == (0.0, 0.0, 0.0, 0.0),
              f"fully-absent price+quote bar currently fabricates an "
              f"all-zero candle rather than raising or being dropped: {c} "
              f"-- see QA finding: FLAG (see report) -- this silently "
              f"emits a fictitious 'certain NO' bar with zero underlying "
              f"signal, distinct from the documented one-sided-quote gap.")
    finally:
        restore()


def test_qa6_orderbook_completely_empty_book():
    """Adversarial: orderbook_fp with BOTH yes_dollars and no_dollars as
    empty lists (a real, legal 'no resting orders at all' book state, not
    a malformed response). Confirms orderbook() returns an empty-but-valid
    BookSnapshot rather than raising, for both the yes and no side (the no
    side's complement math must not choke on an empty asks_raw list)."""
    def router(path, query):
        if path.endswith("/orderbook"):
            return {"orderbook_fp": {"yes_dollars": [], "no_dollars": []}}
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        book_yes = src.orderbook("KXHIGHNY-26JUL19-T80-YES")
        check(book_yes.bids == () and book_yes.asks == (),
              f"expected empty bids/asks, got {book_yes}")
        check(book_yes.best_bid is None and book_yes.best_ask is None,
              f"expected None best_bid/best_ask, got "
              f"{book_yes.best_bid}/{book_yes.best_ask}")

        book_no = src.orderbook("KXHIGHNY-26JUL19-T80-NO")
        check(book_no.bids == () and book_no.asks == (),
              f"expected empty bids/asks (NO side), got {book_no}")
    finally:
        restore()


def test_qa6_list_markets_page_cap_with_category_none():
    """Adversarial: list_markets(category=None) (both weather+econ wanted)
    against an /events feed that keeps paginating forever with events that
    never match EITHER wanted category, and a cursor that genuinely
    advances every page (so the non-advancing-cursor short-circuit from QA
    round 4 does NOT fire) -- only the MAX_PAGES hard cap can terminate
    this. Confirms it does, with a clear KalshiAPIError, not a hang, and
    that the cap logic isn't somehow bypassed when category=None broadens
    `wanted_kalshi` to two values instead of one."""
    call_count = {"n": 0}

    def router(path, query):
        if path == "/events":
            call_count["n"] += 1
            n = call_count["n"]
            return {
                "events": [{"category": "Sports",  # matches neither weather
                                                     # nor economics
                            "series_ticker": "S-IRRELEVANT",
                            "markets": [{"ticker": f"IRRELEVANT-{n}",
                                        "close_time": "2026-08-01T00:00:00Z"}]}],
                "cursor": f"cursor-{n}",  # always advances -- never repeats
            }
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        try:
            rows = src.list_markets(category=None, active=True, limit=10)
            raise AssertionError(
                f"expected KalshiAPIError (MAX_PAGES exceeded), got "
                f"{len(rows)} row(s) instead of terminating")
        except KalshiAPIError as e:
            check("page" in str(e).lower(), f"error should mention pagination: {e}")
            # confirm it actually terminated (bounded number of fetches),
            # not an accidental infinite loop that happened to raise for a
            # different reason after this test's own timeout machinery.
            check(call_count["n"] < 10000,
                  f"pagination fetched an implausible {call_count['n']} pages "
                  f"before raising -- looks unbounded, not capped")
    finally:
        restore()


def test_qa6_wallet_trades_and_leaderboard_not_implemented():
    """US-2 / plan.md WP-3 acceptance: wallet_trades/leaderboard must raise
    NotImplementedError (Kalshi has no public per-trader feed), not return
    an empty list or silently no-op."""
    src = KalshiSource()
    try:
        src.wallet_trades("0xdeadbeef")
        raise AssertionError("wallet_trades should raise NotImplementedError")
    except NotImplementedError as e:
        check("Kalshi" in str(e), f"message should explain why: {e}")

    try:
        src.leaderboard()
        raise AssertionError("leaderboard should raise NotImplementedError")
    except NotImplementedError as e:
        check("Kalshi" in str(e), f"message should explain why: {e}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = []
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except Exception as e:
            failures.append((t.__name__, e))
            print(f"FAIL: {t.__name__}: {type(e).__name__}: {e}")
    print()
    if failures:
        print(f"{len(failures)} of {len(tests)} FAILED")
        sys.exit(1)
    print(f"ALL {len(tests)} PASSED")
