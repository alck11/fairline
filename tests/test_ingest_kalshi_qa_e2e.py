"""
tests/test_ingest_kalshi_qa_e2e.py — QA adversarial test for WP-3.

This is NOT part of the executor's committed suite. It independently drives
`run_kalshi_ingest.run()` end-to-end against a REAL throwaway Postgres (no
mocking of store.py) and the same fixture-backed transport used by
tests/test_ingest_kalshi.py, then queries the database directly with raw SQL
to confirm:

  1. Both open and settled markets actually land in `market`/`outcome`.
  2. Candles actually land in `candlestick` for both open and settled markets.
  3. Resolved outcomes actually land in `outcome.resolved_value` (1.0/0.0)
     and `market.resolved = true` for settled markets, matching the known
     fixture ground truth (KXHIGHNY-26JUL17-B85.5 resolves YES,
     KXHIGHNY-26JUL17-T90 resolves NO).
  4. Open markets are NOT marked resolved.

This is the exact acceptance criterion WP-3 exists to satisfy (US-2:
"a documented backtest window of real Kalshi weather/econ markets loads with
resolved outcomes") and the exact thing the reviewer's first-pass blocker
broke (run() only ever fetched open markets). The committed regression test
(test_run_kalshi_ingest_calls_apply_resolutions_with_real_data) mocks out
every store.py call, so it never actually proves rows land in a database —
this test closes that gap by using the real store.py + real Postgres.

Standalone, no pytest dependency: `python3 tests/test_ingest_kalshi_qa_e2e.py`.
Needs $DATABASE_URL or `pgserver` importable, exactly like
tests/test_store_persistence.py; prints why and exits 0 (SKIPPED) if neither
is available.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg                        # noqa: E402
import psycopg.conninfo as conninfo   # noqa: E402

import store                          # noqa: E402
import run_kalshi_ingest              # noqa: E402
from ingest_kalshi import KalshiSource  # noqa: E402

# reuse the exact fixture router from the committed suite
sys.path.insert(0, os.path.dirname(__file__))
from test_ingest_kalshi import install_fixture_router, default_router  # noqa: E402

SCHEMA_FILES = [
    os.path.join(os.path.dirname(__file__), "..", "schema", "001_schema.sql"),
    os.path.join(os.path.dirname(__file__), "..", "schema", "002_kalshi_ev.sql"),
]
TIMESCALE_MARKERS = ("timescaledb", "create_hypertable")
_state = {"server": None}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _base_conninfo() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return ""
    data_dir = os.path.join(os.path.dirname(__file__), ".pgserver-test-data-qa-e2e")
    srv = pgserver.get_server(data_dir)
    _state["server"] = srv
    return srv.get_uri()


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _apply_schema(conn) -> None:
    for path in SCHEMA_FILES:
        with open(path) as fh:
            sql = _strip_sql_comments(fh.read())
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                conn.execute(stmt)
            except Exception as e:
                if any(m in stmt.lower() for m in TIMESCALE_MARKERS):
                    continue
                raise RuntimeError(f"schema statement failed:\n{stmt}\n-> {e}") from e


def _provision(base: str) -> str | None:
    if not base:
        return None
    info = conninfo.conninfo_to_dict(base)
    maint = dict(info)
    maint.setdefault("dbname", "postgres")
    try:
        conn = psycopg.connect(conninfo.make_conninfo(**maint), autocommit=True,
                                connect_timeout=5)
    except Exception as e:
        print(f"could not reach Postgres: {e}")
        return None
    db_name = f"fairline_qa_e2e_{uuid.uuid4().hex[:12]}"
    conn.execute(f'CREATE DATABASE "{db_name}"')
    conn.close()
    test_info = dict(info)
    test_info["dbname"] = db_name
    return conninfo.make_conninfo(**test_info)


def _teardown_db(dsn: str) -> None:
    info = conninfo.conninfo_to_dict(dsn)
    db_name = info.pop("dbname")
    conn = psycopg.connect(conninfo.make_conninfo(**info), autocommit=True)
    conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
    conn.close()


def test_run_end_to_end_resolutions_land_in_real_db(conn):
    """Drive run_kalshi_ingest.run() with the REAL store.py against a REAL
    Postgres and the committed fixture router (open + settled weather
    markets), then read the database back with raw SQL — bypassing store.py
    entirely for the assertions, so a bug in store.py itself couldn't mask a
    bug in the ingest path."""
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        n = run_kalshi_ingest.run(src, conn, category="weather", limit=10,
                                   days=2, period="1h")
    finally:
        restore()

    check(n == 4, f"expected 4 weather markets ingested (2 open + 2 settled), got {n}")

    rows = conn.execute(
        "SELECT external_id, resolved FROM market WHERE venue = 'kalshi' "
        "ORDER BY external_id").fetchall()
    by_id = {r[0]: r[1] for r in rows}
    check(set(by_id) == {"KXHIGHNY-26JUL17-B85.5", "KXHIGHNY-26JUL17-T90",
                          "KXHIGHNY-26JUL19-T80", "KXHIGHNY-26JUL19-B80.5"},
          f"unexpected market set in DB: {by_id}")

    # settled markets must be marked resolved; open markets must NOT be
    check(by_id["KXHIGHNY-26JUL17-B85.5"] is True,
          "settled market KXHIGHNY-26JUL17-B85.5 should be market.resolved=true")
    check(by_id["KXHIGHNY-26JUL17-T90"] is True,
          "settled market KXHIGHNY-26JUL17-T90 should be market.resolved=true")
    check(by_id["KXHIGHNY-26JUL19-T80"] is False,
          "open market KXHIGHNY-26JUL19-T80 should NOT be market.resolved")
    check(by_id["KXHIGHNY-26JUL19-B80.5"] is False,
          "open market KXHIGHNY-26JUL19-B80.5 should NOT be market.resolved")

    # resolved_value must actually be readable from `outcome`, and correct
    # per the fixture ground truth: B85.5 result="yes", T90 result="no".
    # (idx=0 is always YES, idx=1 is always NO — see KalshiSource._parse_market;
    # sub_title text is used as the display `label`, not the literal string
    # "YES"/"NO", so assert on idx not label.)
    yes_row = conn.execute(
        "SELECT o.idx, o.resolved_value FROM outcome o "
        "JOIN market m ON m.market_id = o.market_id "
        "WHERE m.external_id = 'KXHIGHNY-26JUL17-B85.5' ORDER BY o.idx").fetchall()
    check(yes_row == [(0, 1.0), (1, 0.0)],
          f"KXHIGHNY-26JUL17-B85.5 resolved_value mismatch (idx0=YES should be "
          f"1.0, idx1=NO should be 0.0): {yes_row}")

    no_row = conn.execute(
        "SELECT o.idx, o.resolved_value FROM outcome o "
        "JOIN market m ON m.market_id = o.market_id "
        "WHERE m.external_id = 'KXHIGHNY-26JUL17-T90' ORDER BY o.idx").fetchall()
    check(no_row == [(0, 0.0), (1, 1.0)],
          f"KXHIGHNY-26JUL17-T90 resolved_value mismatch (idx0=YES should be "
          f"0.0, idx1=NO should be 1.0): {no_row}")

    # open markets must have NULL resolved_value (not resolved yet)
    open_row = conn.execute(
        "SELECT o.resolved_value FROM outcome o "
        "JOIN market m ON m.market_id = o.market_id "
        "WHERE m.external_id = 'KXHIGHNY-26JUL19-T80'").fetchall()
    check(all(v is None for (v,) in open_row),
          f"open market outcomes should have NULL resolved_value, got {open_row}")

    # candles must actually land for every market (both open and settled) —
    # this is the exact thing PIT readers (candles_before) later depend on.
    candle_counts = conn.execute(
        "SELECT m.external_id, count(*) FROM candlestick c "
        "JOIN outcome o ON o.outcome_id = c.outcome_id "
        "JOIN market m ON m.market_id = o.market_id "
        "GROUP BY m.external_id ORDER BY m.external_id").fetchall()
    counts = dict(candle_counts)
    check(all(counts.get(eid, 0) > 0 for eid in by_id),
          f"every ingested market should have >=1 candle row, got counts={counts}")


def test_rerun_is_idempotent_on_resolutions(conn):
    """Running the ingest twice must not duplicate rows or corrupt
    resolved_value — re-running is a normal operational pattern (e.g. a
    cron re-pull), and WP-1's idempotency guarantee only holds end-to-end if
    WP-3's entry point doesn't break it."""
    calls, restore = install_fixture_router(default_router)
    try:
        src = KalshiSource()
        run_kalshi_ingest.run(src, conn, category="weather", limit=10, days=2, period="1h")
        run_kalshi_ingest.run(src, conn, category="weather", limit=10, days=2, period="1h")
    finally:
        restore()

    n_markets = conn.execute(
        "SELECT count(*) FROM market WHERE venue='kalshi'").fetchone()[0]
    check(n_markets == 4, f"re-run should not duplicate market rows, got {n_markets}")

    n_candles = conn.execute(
        "SELECT count(*) FROM candlestick c JOIN outcome o ON o.outcome_id=c.outcome_id "
        "JOIN market m ON m.market_id=o.market_id WHERE m.venue='kalshi'").fetchone()[0]
    check(n_candles == 8 * 4,
          f"re-run should update candles in place, not duplicate them, got {n_candles}")

    yes_row = conn.execute(
        "SELECT o.resolved_value FROM outcome o JOIN market m ON m.market_id=o.market_id "
        "WHERE m.external_id='KXHIGHNY-26JUL17-B85.5' AND o.idx=0").fetchone()
    check(yes_row[0] == 1.0, f"re-run should not corrupt resolved_value, got {yes_row}")


# ---------------------------------------------------------------------------
def main() -> int:
    base = _base_conninfo()
    if not base:
        print("SKIPPED: no Postgres reachable (set $DATABASE_URL or `pip install "
              "pgserver`) -- not a code defect, just missing local infra.")
        return 0

    tests = [
        test_run_end_to_end_resolutions_land_in_real_db,
        test_rerun_is_idempotent_on_resolutions,
    ]
    failures = 0
    for t in tests:
        dsn = _provision(base)
        if dsn is None:
            print("SKIPPED: could not provision a throwaway database")
            return 0
        conn = psycopg.connect(dsn, autocommit=True)
        try:
            _apply_schema(conn)
            t(conn)
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")
        finally:
            conn.close()
            _teardown_db(dsn)

    if _state["server"] is not None:
        _state["server"].cleanup()

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
