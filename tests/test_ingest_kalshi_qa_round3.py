"""
tests/test_ingest_kalshi_qa_round3.py — QA round 3 (closing pass) adversarial
regression for WP-3.

Round 1 FAILed on malformed Kalshi API responses crashing with bare Python
exceptions instead of `KalshiAPIError`. Three follow-up fix rounds (08d5b74,
7a6e861, d71aac7) closed every variant found so far -- missing keys, non-ISO
`close_time`, out-of-range `end_period_ts`, and a non-string `series_ticker`
reaching `urllib.parse.quote()` before `candlesticks()`'s own try/except.
Reviewer round 5 did a full structural sweep of every `urllib.parse.quote()`
call site and every JSON-fed value used before a try/except in the class and
concluded the bug class was closed.

This file demonstrates a fifth variant the sweep missed: a market entry with
`"ticker": null` (present, syntactically valid JSON, but null instead of a
string) is NOT rejected anywhere in `_parse_market`/`list_markets` -- it
parses "successfully" into a `MarketRow(external_id=None, ...)` with
synthesized outcome token ids `"None-YES"` / `"None-NO"`. `list_markets()`
itself raises nothing. The failure only surfaces one layer up, when
`run_kalshi_ingest.run()` passes that row to the real `store.upsert_market()`,
whose `market.external_id` column is `NOT NULL` -- Postgres raises
`psycopg.errors.NotNullViolation`, a bare, uncaught exception that is NOT a
`KalshiAPIError` and is NOT caught by `run_kalshi_ingest.main()`'s
`except KalshiAPIError`. It propagates to the top of the process as a raw
traceback (which also leaks the failing row's column values to stderr) --
exactly the bug class QA rounds 1-2 already found and closed for four other
malformed-field variants.

Two tests:
  - test_list_markets_null_ticker_raises_kalshi_api_error (no DB, fast):
    documents that `list_markets()` should treat `ticker: null` the same way
    it already treats a non-ISO `close_time` or a missing key -- reject it
    with `KalshiAPIError` at the source, not let it through as valid data.
    Currently FAILS: `list_markets()` returns silently instead.
  - test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception
    (real throwaway Postgres, same DB scaffolding as
    test_ingest_kalshi_qa_e2e.py; SKIPS with a clear message if neither
    $DATABASE_URL nor `pgserver` is available): proves the escape end-to-end
    through the real ingest entry point and the real store.py -- the
    round-2-closing regression test for the *previous* variant
    (test_run_kalshi_ingest_malformed_series_ticker_raises_kalshi_api_error
    in test_ingest_kalshi.py) stubs out every store.* call, so it structurally
    cannot see a bug that only manifests as a DB constraint violation.
    Currently FAILS: a bare psycopg.errors.NotNullViolation escapes run().

Standalone, no pytest dependency: `python3 tests/test_ingest_kalshi_qa_round3.py`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import psycopg  # noqa: E402

import store  # noqa: E402
import run_kalshi_ingest  # noqa: E402
from ingest_kalshi import KalshiAPIError, KalshiSource  # noqa: E402
from test_ingest_kalshi import install_fixture_router  # noqa: E402
from test_ingest_kalshi_qa_e2e import (  # noqa: E402
    _apply_schema,
    _base_conninfo,
    _provision,
    _teardown_db,
)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _null_ticker_router(path, query):
    if path == "/events":
        if query.get("status") == "settled":
            return {"events": []}
        return {"events": [{"category": "Climate and Weather",
                            "series_ticker": "KXHIGHNY",
                            "markets": [{"ticker": None,
                                        "close_time": "2026-07-20T04:59:00Z"}]}]}
    raise AssertionError(f"unmocked Kalshi path: {path}")


def test_list_markets_null_ticker_raises_kalshi_api_error():
    """A market entry with `ticker: null` is syntactically valid JSON but
    the wrong shape (same class as the already-fixed missing-key /
    non-ISO-close_time / out-of-range-end_period_ts / non-string-series_ticker
    variants) -- it should raise KalshiAPIError like every other malformed
    field this module parses, not silently produce a MarketRow with
    external_id=None."""
    calls, restore = install_fixture_router(_null_ticker_router)
    try:
        src = KalshiSource()
        try:
            rows = src.list_markets(category="weather", limit=3)
            raise AssertionError(
                f"ticker=None should raise KalshiAPIError, but list_markets() "
                f"returned silently: {rows!r}")
        except KalshiAPIError:
            pass
    finally:
        restore()


def test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception(conn):
    """End-to-end: run_kalshi_ingest.run() against a real Postgres must not
    let a malformed Kalshi response escape as a bare, non-KalshiAPIError
    exception -- this is US-2's graceful-degradation contract ("clear error,
    non-zero exit", never a bare traceback) and ingest_kalshi.py's own module
    docstring promise ("nothing here calls sys.exit on its own path" / every
    unrecoverable failure -> KalshiAPIError). A bare
    psycopg.errors.NotNullViolation is exactly the class of failure US-2 was
    written to prevent, and it also leaks the failing row's raw column values
    to stderr -- worse than the tracebacks rounds 1-2 already fixed."""
    calls, restore = install_fixture_router(_null_ticker_router)
    try:
        src = KalshiSource()
        try:
            run_kalshi_ingest.run(src, conn, category="weather", limit=3,
                                  days=2, period="1h")
            raise AssertionError(
                "ticker=None should raise KalshiAPIError (or at least "
                "something other than silent success) from run()")
        except KalshiAPIError:
            pass  # correct graceful-degradation outcome
        except Exception as e:
            raise AssertionError(
                f"bare {type(e).__name__} escaped run_kalshi_ingest.run() "
                f"instead of KalshiAPIError -- the exact bug class QA "
                f"rounds 1-2 already fixed for four other malformed-field "
                f"variants, now reproduced for ticker=None: {e}") from e
    finally:
        restore()


# ---------------------------------------------------------------------------
def main() -> int:
    failures = 0

    try:
        test_list_markets_null_ticker_raises_kalshi_api_error()
        print("PASS: test_list_markets_null_ticker_raises_kalshi_api_error")
    except AssertionError as e:
        failures += 1
        print(f"FAIL: test_list_markets_null_ticker_raises_kalshi_api_error: {e}")
    except Exception as e:
        failures += 1
        print(f"ERROR: test_list_markets_null_ticker_raises_kalshi_api_error: "
              f"{type(e).__name__}: {e}")

    base = _base_conninfo()
    if not base:
        print("SKIPPED: test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception "
              "-- no Postgres reachable (set $DATABASE_URL or `pip install pgserver`); "
              "not a code defect, just missing local infra.")
    else:
        dsn = _provision(base)
        if dsn is None:
            print("SKIPPED: test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception "
                  "-- could not provision a throwaway database")
        else:
            conn = psycopg.connect(dsn, autocommit=True)
            try:
                _apply_schema(conn)
                test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception(conn)
                print("PASS: test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception")
            except AssertionError as e:
                failures += 1
                print(f"FAIL: test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR: test_run_kalshi_ingest_null_ticker_does_not_crash_with_bare_db_exception: "
                      f"{type(e).__name__}: {e}")
            finally:
                conn.close()
                _teardown_db(dsn)

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
