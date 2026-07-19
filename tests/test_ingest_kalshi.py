"""
tests/test_ingest_kalshi.py — WP-3 tests for src/ingest_kalshi.py.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_ingest_kalshi.py`). NO LIVE NETWORK: every test
monkeypatches `urllib.request.urlopen` to route through recorded fixture
responses under tests/fixtures/kalshi/ instead of hitting Kalshi's real API.
Those fixtures were captured live on 2026-07-18 against
https://external-api.kalshi.com/trade-api/v2 — Kalshi's documented
*recommended* host (docs.kalshi.com/getting_started/api_environments) and
this repo's DEFAULT_BASE_URL (see ingest_kalshi.py's module docstring for
the endpoints/shapes this pins); confirmed live the same day that
https://api.elections.kalshi.com/trade-api/v2, the older shared host,
returns byte-identical responses for the same requests, so either host's
capture would have pinned the same shapes — trimmed to a few rows each
— the point is to freeze *real* Kalshi JSON shapes so KalshiSource's parsing
is tested against ground truth, not a hand-rolled guess at the schema, while
never touching the network in CI (plan.md WP-3 acceptance: "Integration test
runs against recorded fixture responses (no live network in CI)").

Traces to docs/architecture/plan.md WP-3 acceptance (US-2 G/W/T):
  - a documented backtest window of real Kalshi weather/econ markets loads
    with resolved outcomes and no manual patching (this file, fixture-based)
  - the adapter exits non-zero with a clear error on API/rate-limit failure
  - no trading/execution code is present (data only)
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ingest import MarketRow  # noqa: E402
from ingest_kalshi import KalshiAPIError, KalshiSource  # noqa: E402
import run_kalshi_ingest  # noqa: E402
import store  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "kalshi")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _load(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# fake transport — routes urlopen() by path, never touches the network
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _api_path(url: str) -> tuple[str, dict]:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.split("/trade-api/v2", 1)[-1]
    query = dict(urllib.parse.parse_qsl(parsed.query))
    return path, query


def install_fixture_router(router):
    """Monkeypatch urllib.request.urlopen for the duration of one test.
    `router(path, query) -> dict` returns the fixture payload, or raises to
    simulate a transport failure. Returns (calls, restore); the caller must
    call restore() in a finally block."""
    calls = []
    original = urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        path, query = _api_path(req.full_url)
        calls.append((path, query))
        payload = router(path, query)
        return _FakeResponse(payload)

    urllib.request.urlopen = fake_urlopen

    def restore():
        urllib.request.urlopen = original

    return calls, restore


def default_router(path, query):
    """Routes every endpoint KalshiSource calls to its recorded fixture.
    /events is routed by its `status` query param, mirroring live Kalshi
    behavior (confirmed live 2026-07-18): status='open' -> currently
    tradable events (events_mixed.json), status='settled' -> already
    resolved events (events_settled.json) -- see list_markets's active=True
    -> 'open' / active=False -> 'settled' mapping in ingest_kalshi.py."""
    if path == "/events":
        if query.get("status") == "settled":
            return _load("events_settled.json")
        return _load("events_mixed.json")
    if path == "/markets/KXHIGHNY-26JUL19-T80":
        return _load("market_single.json")
    if path == "/events/KXHIGHNY-26JUL19":
        return _load("event_single.json")
    if path.startswith("/series/") and path.endswith("/candlesticks"):
        return _load("candlesticks_weather.json")
    if path == "/markets/KXHIGHNY-26JUL19-T80/orderbook":
        return _load("orderbook.json")
    if path == "/markets":
        return _load("markets_resolved.json")
    raise AssertionError(f"unmocked Kalshi path in test fixture router: {path}")


# ---------------------------------------------------------------------------
# list_markets
# ---------------------------------------------------------------------------
def test_list_markets_category_weather():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.list_markets(category="weather", limit=10)
    finally:
        restore()

    check(len(rows) == 2, f"expected 2 weather markets, got {len(rows)}")
    check(all(isinstance(r, MarketRow) for r in rows), "list_markets must return MarketRow")
    check(all(r.category == "weather" for r in rows),
          f"all rows should be category='weather', got {[r.category for r in rows]}")
    check(all(r.venue == "kalshi" for r in rows), "venue must be 'kalshi'")
    tickers = {r.external_id for r in rows}
    check(tickers == {"KXHIGHNY-26JUL19-T80", "KXHIGHNY-26JUL19-B80.5"},
          f"unexpected tickers: {tickers}")

    m = next(r for r in rows if r.external_id == "KXHIGHNY-26JUL19-T80")
    check(len(m.outcomes) == 2, f"expected 2 outcomes, got {len(m.outcomes)}")
    labels = {o.label for o in m.outcomes}
    tokens = {o.token_id for o in m.outcomes}
    check(tokens == {"KXHIGHNY-26JUL19-T80-YES", "KXHIGHNY-26JUL19-T80-NO"},
          f"token_id scheme mismatch: {tokens}")
    check(m.resolves_at == datetime(2026, 7, 20, 4, 59, tzinfo=timezone.utc),
          f"resolves_at parse mismatch: {m.resolves_at}")
    check(m.question.startswith("Will the **high temp in NYC**"),
          f"question not parsed from title: {m.question!r}")


def test_list_markets_category_economics():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.list_markets(category="economics", limit=10)
    finally:
        restore()

    check(len(rows) == 2, f"expected 2 econ markets, got {len(rows)}")
    check(all(r.category == "economics" for r in rows),
          f"all rows should be category='economics', got {[r.category for r in rows]}")
    tickers = {r.external_id for r in rows}
    check(tickers == {"KXU3MAX-30-5", "KXU3MAX-30-6"}, f"unexpected tickers: {tickers}")


def test_list_markets_no_category_returns_both():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.list_markets(limit=10)
    finally:
        restore()

    check(len(rows) == 4, f"expected 4 markets (weather+econ), got {len(rows)}")
    cats = {r.category for r in rows}
    check(cats == {"weather", "economics"}, f"expected both categories, got {cats}")


def test_list_markets_unknown_category_raises_no_network():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        try:
            src.list_markets(category="sports", limit=10)
            raise AssertionError("list_markets(category='sports') should raise ValueError")
        except ValueError:
            pass
    finally:
        restore()
    check(calls == [], f"unknown category should not touch the network, got calls={calls}")


def test_list_markets_respects_limit():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.list_markets(limit=1)
    finally:
        restore()
    check(len(rows) == 1, f"limit=1 should return exactly 1 row, got {len(rows)}")


def test_list_markets_active_false_returns_settled():
    """active=False must request Kalshi's 'settled' event status (not just
    drop the filter) -- this is the seam run_kalshi_ingest.run() relies on
    to source resolution data (see the WP-3 review blocker)."""
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.list_markets(category="weather", limit=10, active=False)
    finally:
        restore()

    check(len(rows) == 2, f"expected 2 settled weather markets, got {len(rows)}")
    tickers = {r.external_id for r in rows}
    check(tickers == {"KXHIGHNY-26JUL17-B85.5", "KXHIGHNY-26JUL17-T90"},
          f"unexpected settled tickers: {tickers}")
    check(("/events", {"with_nested_markets": "true", "status": "settled",
                        "limit": "10"}) in calls,
          f"list_markets(active=False) must query status='settled', got calls={calls}")


# ---------------------------------------------------------------------------
# orderbook — YES/NO complementary pricing
# ---------------------------------------------------------------------------
def test_orderbook_yes_side():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        book = src.orderbook("KXHIGHNY-26JUL19-T80-YES")
    finally:
        restore()

    raw = _load("orderbook.json")["orderbook_fp"]
    yes_levels = [(float(p), float(sz)) for p, sz in raw["yes_dollars"]]
    no_levels = [(float(p), float(sz)) for p, sz in raw["no_dollars"]]
    expected_bids = tuple(sorted(yes_levels, key=lambda l: -l[0]))
    expected_asks = tuple(sorted(((round(1.0 - p, 4), sz) for p, sz in no_levels),
                                 key=lambda l: l[0]))

    check(book.token_id == "KXHIGHNY-26JUL19-T80-YES", "token_id must round-trip")
    check(book.bids == expected_bids, f"YES bids mismatch: {book.bids} != {expected_bids}")
    check(book.asks == expected_asks, f"YES asks mismatch: {book.asks} != {expected_asks}")
    check(book.best_bid == expected_bids[0][0], "best_bid should be the highest YES bid")
    check(book.best_ask == expected_asks[0][0], "best_ask should be the lowest derived ask")


def test_orderbook_no_side_is_complement():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        book = src.orderbook("KXHIGHNY-26JUL19-T80-NO")
    finally:
        restore()

    raw = _load("orderbook.json")["orderbook_fp"]
    yes_levels = [(float(p), float(sz)) for p, sz in raw["yes_dollars"]]
    no_levels = [(float(p), float(sz)) for p, sz in raw["no_dollars"]]
    expected_bids = tuple(sorted(no_levels, key=lambda l: -l[0]))
    expected_asks = tuple(sorted(((round(1.0 - p, 4), sz) for p, sz in yes_levels),
                                 key=lambda l: l[0]))

    check(book.bids == expected_bids, f"NO bids mismatch: {book.bids} != {expected_bids}")
    check(book.asks == expected_asks, f"NO asks mismatch: {book.asks} != {expected_asks}")


# ---------------------------------------------------------------------------
# candlesticks — series_ticker resolution + caching, YES/NO complement
# ---------------------------------------------------------------------------
def test_candlesticks_yes_side_and_series_cache():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        candles = src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start, end=end,
                                   period="1h")

        raw = _load("candlesticks_weather.json")["candlesticks"]
        check(len(candles) == len(raw), f"expected {len(raw)} candles, got {len(candles)}")
        first = candles[0]
        rp = raw[0]["price"]
        check(first.open == float(rp["open_dollars"]), f"open mismatch: {first.open}")
        check(first.high == float(rp["high_dollars"]), f"high mismatch: {first.high}")
        check(first.low == float(rp["low_dollars"]), f"low mismatch: {first.low}")
        check(first.close == float(rp["close_dollars"]), f"close mismatch: {first.close}")
        check(first.volume == float(raw[0]["volume_fp"]), f"volume mismatch: {first.volume}")
        check(first.ts == datetime.fromtimestamp(raw[0]["end_period_ts"], tz=timezone.utc),
              f"ts mismatch: {first.ts}")
        check(first.token_id == "KXHIGHNY-26JUL19-T80-YES", "token_id must round-trip")

        # series_ticker resolution (2 calls: /markets/{ticker}, /events/{event}) +
        # 1 candlesticks call this time; a second call for the same ticker must
        # hit the cache and NOT repeat the resolution calls. Stay inside the
        # same fake-router scope so the delta below only counts mocked calls.
        check(src._series_cache.get("KXHIGHNY-26JUL19-T80") == "KXHIGHNY",
              f"series_ticker not cached correctly: {src._series_cache}")
        n_calls_first = len(calls)

        src.candlesticks("KXHIGHNY-26JUL19-T80-NO", start=start, end=end, period="1h")
        n_calls_second = len(calls) - n_calls_first
        check(n_calls_second == 1,
              f"cached series_ticker should skip resolution calls, made {n_calls_second}")
    finally:
        restore()


def test_candlesticks_no_side_is_complement():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        yes_candles = src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start, end=end)
        no_candles = src.candlesticks("KXHIGHNY-26JUL19-T80-NO", start=start, end=end)
    finally:
        restore()

    check(len(yes_candles) == len(no_candles), "YES/NO candle counts must match")
    for y, n in zip(yes_candles, no_candles):
        check(n.ts == y.ts, "complementary candles must share a timestamp")
        check(abs(n.open - (1.0 - y.open)) < 1e-9, f"NO open should be 1-YES open: {n.open}")
        check(abs(n.close - (1.0 - y.close)) < 1e-9, f"NO close should be 1-YES close: {n.close}")
        check(abs(n.high - (1.0 - y.low)) < 1e-9, "NO high should be 1-YES low (inverted)")
        check(abs(n.low - (1.0 - y.high)) < 1e-9, "NO low should be 1-YES high (inverted)")


def test_candlesticks_invalid_period_no_network():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        try:
            src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=datetime.now(timezone.utc),
                             end=datetime.now(timezone.utc), period="5m")
            raise AssertionError("period='5m' should raise ValueError")
        except ValueError:
            pass
    finally:
        restore()
    check(calls == [], f"invalid period should not touch the network, got calls={calls}")


# ---------------------------------------------------------------------------
# resolutions — two ResolutionRows per settled market (YES + NO outcomes)
# ---------------------------------------------------------------------------
def test_resolutions_two_sided():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.resolutions(["KXHIGHNY-26JUL17-B85.5", "KXHIGHNY-26JUL17-T90"])
    finally:
        restore()

    check(len(rows) == 4, f"expected 2 rows per settled market (4 total), got {len(rows)}")
    by_token = {r.outcome_token_id: r for r in rows}

    yes_win = by_token["KXHIGHNY-26JUL17-B85.5-YES"]
    check(yes_win.resolved_value == 1.0, f"B85.5 YES should resolve 1.0, got {yes_win.resolved_value}")
    check(yes_win.external_id == "KXHIGHNY-26JUL17-B85.5", "external_id must be the ticker")
    no_side_of_yes_win = by_token["KXHIGHNY-26JUL17-B85.5-NO"]
    check(no_side_of_yes_win.resolved_value == 0.0,
          f"B85.5 NO should resolve 0.0, got {no_side_of_yes_win.resolved_value}")

    no_win = by_token["KXHIGHNY-26JUL17-T90-NO"]
    check(no_win.resolved_value == 1.0, f"T90 NO should resolve 1.0, got {no_win.resolved_value}")
    yes_side_of_no_win = by_token["KXHIGHNY-26JUL17-T90-YES"]
    check(yes_side_of_no_win.resolved_value == 0.0,
          f"T90 YES should resolve 0.0, got {yes_side_of_no_win.resolved_value}")

    check(all(r.resolved_at == datetime(2026, 7, 18, 4, 59, tzinfo=timezone.utc) for r in rows),
          f"resolved_at parse mismatch: {[r.resolved_at for r in rows]}")


def test_resolutions_empty_input_no_network():
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        rows = src.resolutions([])
    finally:
        restore()
    check(rows == [], "resolutions([]) should return an empty list")
    check(calls == [], f"resolutions([]) should not touch the network, got calls={calls}")


# ---------------------------------------------------------------------------
# store.py seam: Candle/ResolutionRow field-for-field compatibility (WP-1/WP-3)
# ---------------------------------------------------------------------------
def test_candle_and_resolution_row_match_store_shape():
    """ingest.Candle / ingest.ResolutionRow must be attribute-compatible with
    store.py's own Candle/ResolutionRow (store.upsert_candles /
    apply_resolutions access fields by name, not by isinstance) -- this is
    the exact seam the plan calls out between WP-1 and WP-3."""
    import ingest

    ing_candle_fields = tuple(f for f in ingest.Candle.__dataclass_fields__)
    store_candle_fields = tuple(f for f in store.Candle.__dataclass_fields__)
    check(ing_candle_fields == store_candle_fields,
          f"Candle field mismatch: ingest={ing_candle_fields} store={store_candle_fields}")

    ing_res_fields = tuple(f for f in ingest.ResolutionRow.__dataclass_fields__)
    store_res_fields = tuple(f for f in store.ResolutionRow.__dataclass_fields__)
    check(ing_res_fields == store_res_fields,
          f"ResolutionRow field mismatch: ingest={ing_res_fields} store={store_res_fields}")


# ---------------------------------------------------------------------------
# wallet_trades / leaderboard — must raise, per ADR-0006 Split 2
# ---------------------------------------------------------------------------
def test_wallet_trades_raises():
    src = KalshiSource()
    try:
        src.wallet_trades("some-wallet")
        raise AssertionError("wallet_trades should raise NotImplementedError")
    except NotImplementedError as e:
        check(str(e) == "Kalshi exposes no public per-trader feed", f"unexpected message: {e}")


def test_leaderboard_raises():
    src = KalshiSource()
    try:
        src.leaderboard()
        raise AssertionError("leaderboard should raise NotImplementedError")
    except NotImplementedError as e:
        check(str(e) == "Kalshi exposes no public per-trader feed", f"unexpected message: {e}")


# ---------------------------------------------------------------------------
# graceful degradation — API/rate-limit failure -> clear, catchable error
# ---------------------------------------------------------------------------
def test_graceful_degradation_on_repeated_5xx():
    def failing_router(path, query):
        raise urllib.error.HTTPError("http://fake", 500, "Internal Server Error", {}, None)

    calls, restore = install_fixture_router(failing_router)
    try:
        src = KalshiSource(max_retries=2, backoff=0.01)
        try:
            src.list_markets(category="weather", limit=5)
            raise AssertionError("list_markets should raise KalshiAPIError on repeated 5xx")
        except KalshiAPIError as e:
            check("500" in str(e) or "unreachable" in str(e).lower(),
                  f"error message should be clear about the failure: {e}")
    finally:
        restore()
    check(len(calls) == 2, f"expected exactly max_retries=2 attempts, got {len(calls)}")


def test_graceful_degradation_on_429():
    attempts = {"n": 0}

    def rate_limited_router(path, query):
        attempts["n"] += 1
        raise urllib.error.HTTPError("http://fake", 429, "Too Many Requests", {}, None)

    calls, restore = install_fixture_router(rate_limited_router)
    try:
        src = KalshiSource(max_retries=2, backoff=0.01)
        try:
            src.list_markets(limit=5)
            raise AssertionError("list_markets should raise KalshiAPIError on repeated 429")
        except KalshiAPIError:
            pass
    finally:
        restore()
    check(attempts["n"] == 2, f"429 should be retried, got {attempts['n']} attempt(s)")


def test_series_ticker_missing_key_raises_kalshi_api_error():
    """QA WP-3 follow-up repro: a syntactically valid response missing the
    expected 'market' key used to bypass _get()'s error wrapping entirely
    and raise a bare KeyError."""
    def router(path, query):
        return {"weird": "shape"}  # no "market" key

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        try:
            src._series_ticker("SOME-TICKER")
            raise AssertionError("missing 'market' key should raise KalshiAPIError")
        except KalshiAPIError as e:
            check("market" in str(e) and "SOME-TICKER" in str(e),
                  f"error message should name the missing field and ticker: {e}")
    finally:
        restore()


def test_resolutions_missing_ticker_key_raises_kalshi_api_error():
    """QA WP-3 follow-up repro: a market dict in the /markets response
    missing 'ticker' used to raise a bare KeyError from resolutions()."""
    def router(path, query):
        return {"markets": [{"status": "finalized", "result": "yes",
                             "close_time": "2026-07-18T04:59:00Z"}]}  # no "ticker"

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        try:
            src.resolutions(["FOO-TICKER"])
            raise AssertionError("missing 'ticker' key should raise KalshiAPIError")
        except KalshiAPIError as e:
            # tightened per reviewer: the endpoint literal "tickers batch" in
            # the wrapper message contains "ticker" regardless of which field
            # actually went missing, so plain substring "ticker" would pass
            # even if the underlying KeyError were about something else.
            # Assert the actual failure -- KeyError: 'ticker' -- is present.
            check("KeyError" in str(e) and "'ticker'" in str(e),
                  f"error message should name the actual KeyError on 'ticker': {e}")
    finally:
        restore()


def test_list_markets_malformed_close_time_raises_kalshi_api_error():
    """Reviewer follow-up on WP-3 (commit 08d5b74): a syntactically valid
    /events response with a non-ISO close_time string used to raise a bare
    ValueError out of _ts() (via _parse_market), escaping list_markets's
    KalshiAPIError wrapper -- the same bug class QA originally reported
    (bare traceback instead of a clear error), just triggered by a malformed
    field *value* instead of a missing key."""
    def router(path, query):
        return {"events": [{"category": "Climate and Weather",
                            "series_ticker": "KXHIGHNY",
                            "markets": [{"ticker": "SOME-TICKER",
                                        "close_time": "not-a-real-date"}]}]}

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        try:
            src.list_markets(category="weather", limit=3)
            raise AssertionError("malformed close_time should raise KalshiAPIError")
        except KalshiAPIError as e:
            check("ValueError" in str(e) and "not-a-real-date" in str(e),
                  f"error message should name the ValueError and bad value: {e}")
    finally:
        restore()


def test_resolutions_malformed_close_time_raises_kalshi_api_error():
    """Reviewer follow-up on WP-3 (commit 08d5b74): a syntactically valid
    /markets response with a non-ISO close_time string used to raise a bare
    ValueError out of _ts(), escaping resolutions()'s KalshiAPIError
    wrapper -- same bug class as test_list_markets_malformed_close_time
    above, for the second call site that reaches _ts() directly."""
    def router(path, query):
        return {"markets": [{"ticker": "FOO-TICKER", "status": "finalized",
                             "result": "yes", "close_time": "not-a-real-date"}]}

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        try:
            src.resolutions(["FOO-TICKER"])
            raise AssertionError("malformed close_time should raise KalshiAPIError")
        except KalshiAPIError as e:
            check("ValueError" in str(e) and "not-a-real-date" in str(e),
                  f"error message should name the ValueError and bad value: {e}")
    finally:
        restore()


def test_malformed_top_level_body_raises_kalshi_api_error():
    """QA WP-3 follow-up repro: a top-level JSON body that isn't a dict
    (null / bare list / string) used to bypass _get()'s error wrapping and
    surface as a bare AttributeError deep in a parsing site. Covers every
    _get() caller by exercising list_markets, orderbook, and candlesticks
    (via the series_ticker lookup) against each malformed shape."""
    malformed_bodies = [None, [1, 2, 3], "not an object"]

    for body in malformed_bodies:
        def router(path, query, body=body):
            return body

        calls, restore = install_fixture_router(router)
        try:
            src = KalshiSource(max_retries=2)
            try:
                src.list_markets(category="weather", limit=3)
                raise AssertionError(
                    f"list_markets should raise KalshiAPIError for top-level body {body!r}")
            except KalshiAPIError as e:
                check("JSON object" in str(e),
                      f"error message should describe the shape problem: {e}")
        finally:
            restore()

    for body in malformed_bodies:
        def router(path, query, body=body):
            return body

        calls, restore = install_fixture_router(router)
        try:
            src = KalshiSource(max_retries=2)
            try:
                src.orderbook("SOME-TICKER-YES")
                raise AssertionError(
                    f"orderbook should raise KalshiAPIError for top-level body {body!r}")
            except KalshiAPIError as e:
                check("JSON object" in str(e),
                      f"error message should describe the shape problem: {e}")
        finally:
            restore()

    for body in malformed_bodies:
        def router(path, query, body=body):
            return body

        calls, restore = install_fixture_router(router)
        try:
            src = KalshiSource(max_retries=2)
            try:
                src.resolutions(["SOME-TICKER"])
                raise AssertionError(
                    f"resolutions should raise KalshiAPIError for top-level body {body!r}")
            except KalshiAPIError as e:
                check("JSON object" in str(e),
                      f"error message should describe the shape problem: {e}")
        finally:
            restore()


def test_candlesticks_missing_key_raises_kalshi_api_error():
    """A candlestick entry missing 'end_period_ts' (or any other malformed
    field this parsing relies on) should raise KalshiAPIError, not a bare
    KeyError -- same class of bug as the series_ticker/resolutions repros,
    caught here for the third parsing site the QA report flagged
    (candlesticks/any other _get() caller) during the executor's audit."""
    def router(path, query):
        if path == "/markets/KXHIGHNY-26JUL19-T80":
            return _load("market_single.json")
        if path == "/events/KXHIGHNY-26JUL19":
            return _load("event_single.json")
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{"price": {"open_dollars": "0.5", "high_dollars": "0.6",
                                                 "low_dollars": "0.4", "close_dollars": "0.5"},
                                       "volume_fp": "10"}]}  # no "end_period_ts"
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        try:
            src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start, end=end, period="1h")
            raise AssertionError("missing 'end_period_ts' should raise KalshiAPIError")
        except KalshiAPIError as e:
            check("KXHIGHNY-26JUL19-T80" in str(e), f"error message should name the ticker: {e}")
    finally:
        restore()


def test_candlesticks_out_of_range_end_period_ts_raises_kalshi_api_error():
    """Reviewer follow-up on WP-3 (commit 08d5b74): an absurdly out-of-range
    numeric 'end_period_ts' (e.g. 10**20) makes datetime.fromtimestamp()
    raise OverflowError, not ValueError -- a different exception type than
    the malformed-key/malformed-shape cases test_candlesticks_missing_key_
    raises_kalshi_api_error already covers, and one the original catch tuple
    didn't include, so it used to escape candlesticks() as a bare
    OverflowError instead of KalshiAPIError."""
    def router(path, query):
        if path == "/markets/KXHIGHNY-26JUL19-T80":
            return _load("market_single.json")
        if path == "/events/KXHIGHNY-26JUL19":
            return _load("event_single.json")
        if path.startswith("/series/") and path.endswith("/candlesticks"):
            return {"candlesticks": [{"price": {"open_dollars": "0.5", "high_dollars": "0.6",
                                                 "low_dollars": "0.4", "close_dollars": "0.5"},
                                       "volume_fp": "10",
                                       "end_period_ts": 10**20}]}
        raise AssertionError(f"unmocked path: {path}")

    calls, restore = install_fixture_router(router)
    try:
        src = KalshiSource(max_retries=2)
        start = datetime(2026, 7, 17, tzinfo=timezone.utc)
        end = datetime(2026, 7, 19, tzinfo=timezone.utc)
        try:
            src.candlesticks("KXHIGHNY-26JUL19-T80-YES", start=start, end=end, period="1h")
            raise AssertionError("out-of-range end_period_ts should raise KalshiAPIError")
        except KalshiAPIError as e:
            check("OverflowError" in str(e) and "KXHIGHNY-26JUL19-T80" in str(e),
                  f"error message should name the OverflowError and ticker: {e}")
    finally:
        restore()


def test_run_kalshi_ingest_main_returns_nonzero_on_api_failure():
    """run_kalshi_ingest.main() is the documented entry point (US-2: "exits
    non-zero with a clear error on API/rate-limit failure"). Stub store.connect
    (no real Postgres needed -- KalshiAPIError is raised before any upsert is
    reached) and KalshiSource so this stays fast and network-free."""

    class _DummyConn:
        def execute(self, *a, **kw):
            return None

        def close(self):
            pass

    class _FailingSource:
        def __init__(self, *a, **kw):
            pass

        def list_markets(self, *, active=True, category=None, limit=50):
            raise KalshiAPIError("simulated rate-limit exhaustion")

    orig_connect = store.connect
    orig_source = run_kalshi_ingest.KalshiSource
    store.connect = lambda: _DummyConn()
    run_kalshi_ingest.KalshiSource = _FailingSource
    try:
        rc = run_kalshi_ingest.main(["--limit", "1"])
    finally:
        store.connect = orig_connect
        run_kalshi_ingest.KalshiSource = orig_source

    check(rc == 1, f"main() should return 1 on KalshiAPIError, got {rc}")


def test_run_kalshi_ingest_calls_apply_resolutions_with_real_data():
    """WP-3 review blocker: run() used to call list_markets() with its
    active=True default only (-> status='open'), so every external_id fed to
    resolutions() belonged to an open market -- resolutions() correctly
    filters those out (RESOLVED_STATUSES), so apply_resolutions was never
    reached with real data on any actual run. That bug is invisible to a
    test that calls resolutions() directly with hand-picked settled
    tickers, bypassing run() entirely -- this test drives run() itself
    end-to-end against a fixture set containing both open (events_mixed.json)
    and settled (events_settled.json) markets and asserts apply_resolutions
    is actually invoked with non-empty resolved rows."""
    calls, restore = install_fixture_router(default_router)

    applied: list = []
    upserted_markets: list = []
    market_ids: dict = {}

    def fake_upsert_market(conn, market):
        upserted_markets.append(market.external_id)
        return market_ids.setdefault(market.external_id, len(market_ids) + 1)

    def fake_upsert_outcomes(conn, market_id, outcomes):
        pass

    def fake_upsert_candles(conn, candles):
        pass

    def fake_apply_resolutions(conn, resolutions):
        applied.extend(resolutions)

    orig_upsert_market = store.upsert_market
    orig_upsert_outcomes = store.upsert_outcomes
    orig_upsert_candles = store.upsert_candles
    orig_apply_resolutions = store.apply_resolutions
    store.upsert_market = fake_upsert_market
    store.upsert_outcomes = fake_upsert_outcomes
    store.upsert_candles = fake_upsert_candles
    store.apply_resolutions = fake_apply_resolutions
    try:
        src = KalshiSource()
        n = run_kalshi_ingest.run(src, conn=None, category="weather", limit=10,
                                  days=2, period="1h")
    finally:
        restore()
        store.upsert_market = orig_upsert_market
        store.upsert_outcomes = orig_upsert_outcomes
        store.upsert_candles = orig_upsert_candles
        store.apply_resolutions = orig_apply_resolutions

    check("KXHIGHNY-26JUL19-T80" in upserted_markets,
          f"open market from events_mixed.json should still be ingested, got {upserted_markets}")
    check("KXHIGHNY-26JUL17-B85.5" in upserted_markets,
          f"settled market from events_settled.json should also be ingested, got {upserted_markets}")
    check(n == len(upserted_markets),
          f"run() should return the count of markets actually ingested, got n={n}")

    check(len(applied) > 0,
          "apply_resolutions must be called with non-empty resolved rows when "
          "the ingest window includes settled markets -- this reproduces the "
          "WP-3 review blocker (open-only fetch starved resolutions())")
    by_token = {r.outcome_token_id: r for r in applied}
    check(by_token.get("KXHIGHNY-26JUL17-B85.5-YES") is not None
          and by_token["KXHIGHNY-26JUL17-B85.5-YES"].resolved_value == 1.0,
          f"expected the settled fixture's YES-win market resolved 1.0, got {by_token}")


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_list_markets_category_weather,
        test_list_markets_category_economics,
        test_list_markets_no_category_returns_both,
        test_list_markets_unknown_category_raises_no_network,
        test_list_markets_respects_limit,
        test_list_markets_active_false_returns_settled,
        test_orderbook_yes_side,
        test_orderbook_no_side_is_complement,
        test_candlesticks_yes_side_and_series_cache,
        test_candlesticks_no_side_is_complement,
        test_candlesticks_invalid_period_no_network,
        test_resolutions_two_sided,
        test_resolutions_empty_input_no_network,
        test_candle_and_resolution_row_match_store_shape,
        test_wallet_trades_raises,
        test_leaderboard_raises,
        test_graceful_degradation_on_repeated_5xx,
        test_graceful_degradation_on_429,
        test_series_ticker_missing_key_raises_kalshi_api_error,
        test_resolutions_missing_ticker_key_raises_kalshi_api_error,
        test_malformed_top_level_body_raises_kalshi_api_error,
        test_candlesticks_missing_key_raises_kalshi_api_error,
        test_list_markets_malformed_close_time_raises_kalshi_api_error,
        test_resolutions_malformed_close_time_raises_kalshi_api_error,
        test_candlesticks_out_of_range_end_period_ts_raises_kalshi_api_error,
        test_run_kalshi_ingest_main_returns_nonzero_on_api_failure,
        test_run_kalshi_ingest_calls_apply_resolutions_with_real_data,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
