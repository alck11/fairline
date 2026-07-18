"""
tests/test_store_persistence.py — WP-1 acceptance tests for src/store.py.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_store_persistence.py`). Needs a real Postgres, reached
one of two ways:

  1. $DATABASE_URL set, pointing at a server the test user can CREATEDB on
     (the production/CI path). If that server also has the TimescaleDB
     extension installed, hypertables get created for real.
  2. $DATABASE_URL unset, but `pgserver` is importable (`pip install
     pgserver`) — spins up a throwaway local Postgres for the duration of
     this run, no manual provisioning needed. Its bundled Postgres has no
     TimescaleDB extension, so `CREATE EXTENSION timescaledb` /
     `create_hypertable(...)` statements are skipped with a warning; every
     other statement in schema/001_schema.sql and schema/002_kalshi_ev.sql
     (all table/index/constraint DDL, and every upsert/read this test
     exercises) runs unmodified. Hypertables are a chunking/performance
     optimization on top of ordinary tables — skipping them changes nothing
     this test checks (round-trip correctness, idempotency, PIT boundary are
     plain SQL semantics, identical on a hypertable or a heap table).

If neither path reaches a live Postgres, the test prints why and exits 0
(SKIPPED) rather than 1 — missing local infra is not a code defect. Note this
means a clean run of this file is not, by itself, proof the acceptance
criteria hold; check the printed PASS/FAIL lines, not just the exit code.

A fresh, uniquely-named database is created for this run and dropped at the
end (even on failure), so this never reads or writes a real dev/prod
database's tables.

Traces to docs/architecture/plan.md WP-1 acceptance (US-1 G/W/T):
  - round-trip write/read of a market + candlestick + resolved outcome
  - idempotent re-run (row counts unchanged, values updated not duplicated)
  - PIT readers never return a row dated >= as_of (boundary at exactly as_of)
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import psycopg                    # noqa: E402
import psycopg.conninfo as conninfo  # noqa: E402

import store                      # noqa: E402
from ingest import MarketRow, OutcomeRef   # noqa: E402
from ev_detector import DirectionalSignal  # noqa: E402

SCHEMA_FILES = [
    os.path.join(os.path.dirname(__file__), "..", "schema", "001_schema.sql"),
    os.path.join(os.path.dirname(__file__), "..", "schema", "002_kalshi_ev.sql"),
]
# statements referencing these are allowed to fail (TimescaleDB unavailable)
# without failing the whole schema application — see module docstring.
TIMESCALE_MARKERS = ("timescaledb", "create_hypertable")

_state = {"server": None}   # holds the pgserver instance, if any, for cleanup


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# throwaway database provisioning
# ---------------------------------------------------------------------------
def _base_conninfo() -> str:
    """A conninfo string for *some* reachable Postgres server (any database
    on it), or "" if none is available at all."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return ""
    data_dir = os.path.join(os.path.dirname(__file__), ".pgserver-test-data")
    srv = pgserver.get_server(data_dir)
    _state["server"] = srv
    return srv.get_uri()


def _strip_sql_comments(sql: str) -> str:
    """Drop `-- ...` line comments before splitting on ';' — several comments
    in schema/001_schema.sql contain a literal ';' inside the comment text
    (e.g. "one row per resolved position; this is..."), which would corrupt
    a naive semicolon split if not removed first."""
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
                    print(f"  (skip — no TimescaleDB extension here: {e})")
                    continue
                raise RuntimeError(
                    f"schema statement failed:\n{stmt}\n-> {e}") from e


def _provision() -> str | None:
    """Create a fresh throwaway database and return its DSN, or None if no
    Postgres is reachable at all."""
    base = _base_conninfo()
    if not base:
        return None
    info = conninfo.conninfo_to_dict(base)
    maint = dict(info)
    maint.setdefault("dbname", "postgres")
    try:
        conn = psycopg.connect(conninfo.make_conninfo(**maint), autocommit=True,
                                connect_timeout=5)
    except Exception as e:
        print(f"could not reach Postgres at {maint.get('host', 'default host')}: {e}")
        return None
    db_name = f"fairline_test_{uuid.uuid4().hex[:12]}"
    conn.execute(f'CREATE DATABASE "{db_name}"')
    conn.close()
    test_info = dict(info)
    test_info["dbname"] = db_name
    return conninfo.make_conninfo(**test_info)


def _teardown(dsn: str) -> None:
    try:
        info = conninfo.conninfo_to_dict(dsn)
        db_name = info.pop("dbname")
        conn = psycopg.connect(conninfo.make_conninfo(**info), autocommit=True)
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        conn.close()
    finally:
        if _state["server"] is not None:
            _state["server"].cleanup()


# ---------------------------------------------------------------------------
# acceptance tests
# ---------------------------------------------------------------------------
def test_round_trip_market_candle_resolution(conn):
    market = MarketRow(
        venue="kalshi", external_id="KXHIGHNY-26JUL20-RT",
        question="Will NYC's high temp on Jul 20 be >= 90F?",
        category="weather", resolution_text="NWS KNYC official high.",
        resolves_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        outcomes=(OutcomeRef("KXHIGHNY-26JUL20-RT-YES", "YES", 0),
                  OutcomeRef("KXHIGHNY-26JUL20-RT-NO", "NO", 1)),
    )
    market_id = store.upsert_market(conn, market)
    check(isinstance(market_id, int), f"upsert_market must return an int id, got {market_id!r}")
    store.upsert_outcomes(conn, market_id, market.outcomes)

    row = conn.execute(
        "SELECT m.venue, m.external_id, m.question, o.label FROM market m "
        "JOIN outcome o ON o.market_id = m.market_id "
        "WHERE m.market_id = %s AND o.idx = 0", (market_id,)).fetchone()
    check(row == ("kalshi", "KXHIGHNY-26JUL20-RT", market.question, "YES"),
          f"market/outcome round-trip mismatch: {row}")

    ts = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    candle = store.Candle(ts=ts, token_id="KXHIGHNY-26JUL20-RT-YES",
                           open=0.40, high=0.44, low=0.39, close=0.42, volume=1200.0)
    store.upsert_candles(conn, [candle])

    back = store.candles_before(conn, "KXHIGHNY-26JUL20-RT-YES", ts + timedelta(seconds=1))
    check(len(back) == 1, f"expected 1 candle back, got {len(back)}")
    b = back[0]
    check((b.ts, b.open, b.high, b.low, b.close, b.volume) ==
          (ts, 0.40, 0.44, 0.39, 0.42, 1200.0),
          f"candle round-trip mismatch: {b}")

    resolution = store.ResolutionRow(
        external_id="KXHIGHNY-26JUL20-RT", outcome_token_id="KXHIGHNY-26JUL20-RT-YES",
        resolved_value=1.0, resolved_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
    store.apply_resolutions(conn, [resolution])

    row = conn.execute(
        "SELECT o.resolved_value, m.resolved FROM outcome o "
        "JOIN market m ON m.market_id = o.market_id "
        "WHERE o.idx = 0 AND o.market_id = %s", (market_id,)).fetchone()
    check(row == (1.0, True), f"resolution round-trip mismatch: {row}")


def test_idempotent_rerun(conn):
    market = MarketRow(
        venue="kalshi", external_id="KXHIGHNY-26JUL20-IDEM",
        question="idempotency check", category="weather",
        outcomes=(OutcomeRef("KXHIGHNY-26JUL20-IDEM-YES", "YES", 0),),
    )
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    ts = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    store.upsert_candles(conn, [store.Candle(
        ts=ts, token_id="KXHIGHNY-26JUL20-IDEM-YES",
        open=0.40, high=0.44, low=0.39, close=0.42, volume=1200.0)])

    station, variable = "KIDEM", "tmax_f"
    issued_at = datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc)
    valid_at = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    store.upsert_forecasts(conn, [store.WeatherForecastRow(
        issued_at=issued_at, valid_at=valid_at, station=station, variable=variable,
        value=91.0, source="NWS", horizon_h=18.0)])

    observed_at = datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc)
    store.upsert_observations(conn, [store.WeatherObservationRow(
        observed_at=observed_at, station=station, variable=variable,
        value=88.0, source="NWS")])

    def counts():
        return conn.execute(
            "SELECT (SELECT count(*) FROM market), (SELECT count(*) FROM outcome), "
            "(SELECT count(*) FROM candlestick), "
            "(SELECT count(*) FROM weather_forecast), "
            "(SELECT count(*) FROM weather_observation)").fetchone()

    before = counts()

    # re-run the exact same market/outcome writes, and re-upsert the same
    # candle/forecast/observation with DIFFERENT values (as a real re-ingest
    # of revised data would)
    store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    store.upsert_candles(conn, [store.Candle(
        ts=ts, token_id="KXHIGHNY-26JUL20-IDEM-YES",
        open=0.41, high=0.45, low=0.40, close=0.43, volume=1500.0)])
    store.upsert_forecasts(conn, [store.WeatherForecastRow(
        issued_at=issued_at, valid_at=valid_at, station=station, variable=variable,
        value=93.0, source="NWS", horizon_h=18.0)])
    store.upsert_observations(conn, [store.WeatherObservationRow(
        observed_at=observed_at, station=station, variable=variable,
        value=89.0, source="NWS")])

    after = counts()
    check(before == after, f"row counts changed on re-run: {before} -> {after}")

    back = store.candles_before(conn, "KXHIGHNY-26JUL20-IDEM-YES", ts + timedelta(seconds=1))
    check(len(back) == 1, f"idempotent upsert duplicated rows: {len(back)}")
    check((back[0].open, back[0].close, back[0].volume) == (0.41, 0.43, 1500.0),
          f"idempotent upsert should update values in place, got {back[0]}")

    fr = store.forecasts_before(conn, station, variable, issued_at + timedelta(seconds=1))
    check(len(fr) == 1, f"idempotent forecast upsert duplicated rows: {len(fr)}")
    check(fr[0].value == 93.0,
          f"idempotent forecast upsert should update value in place, got {fr[0]}")

    orow = store.observations_before(conn, station, variable, observed_at + timedelta(seconds=1))
    check(len(orow) == 1, f"idempotent observation upsert duplicated rows: {len(orow)}")
    check(orow[0].value == 89.0,
          f"idempotent observation upsert should update value in place, got {orow[0]}")


def test_pit_boundary_exact_as_of(conn):
    market = MarketRow(
        venue="kalshi", external_id="KXPIT-TEST", question="pit boundary check",
        category="weather", outcomes=(OutcomeRef("KXPIT-TEST-YES", "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    as_of = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    before = store.Candle(ts=as_of - timedelta(seconds=1), token_id="KXPIT-TEST-YES",
                           open=0.1, high=0.1, low=0.1, close=0.1, volume=1.0)
    at_as_of = store.Candle(ts=as_of, token_id="KXPIT-TEST-YES",
                             open=0.2, high=0.2, low=0.2, close=0.2, volume=1.0)
    after = store.Candle(ts=as_of + timedelta(seconds=1), token_id="KXPIT-TEST-YES",
                          open=0.3, high=0.3, low=0.3, close=0.3, volume=1.0)
    store.upsert_candles(conn, [before, at_as_of, after])

    result = store.candles_before(conn, "KXPIT-TEST-YES", as_of)
    check(len(result) == 1,
          f"expected exactly 1 candle strictly before as_of, got {len(result)}: {result}")
    check(result[0].ts == before.ts, f"wrong candle returned: {result[0].ts}")
    check(all(c.ts < as_of for c in result),
          "candles_before returned a row dated >= as_of (boundary violation)")

    # forecasts_before / observations_before: same boundary discipline
    station, variable = "KNYC", "tmax_f"
    f_before = store.WeatherForecastRow(
        issued_at=as_of - timedelta(seconds=1), valid_at=as_of + timedelta(days=1),
        station=station, variable=variable, value=91.0, source="NWS")
    f_at = store.WeatherForecastRow(
        issued_at=as_of, valid_at=as_of + timedelta(days=1),
        station=station, variable=variable, value=92.0, source="NWS")
    store.upsert_forecasts(conn, [f_before, f_at])
    fr = store.forecasts_before(conn, station, variable, as_of)
    check(len(fr) == 1 and fr[0].issued_at == f_before.issued_at,
          f"forecasts_before boundary violated: issued_at values {[r.issued_at for r in fr]}")
    check(all(r.issued_at < as_of for r in fr), "forecasts_before returned issued_at >= as_of")

    o_before = store.WeatherObservationRow(
        observed_at=as_of - timedelta(seconds=1), station=station, variable=variable,
        value=89.0, source="NWS")
    o_at = store.WeatherObservationRow(
        observed_at=as_of, station=station, variable=variable, value=90.0, source="NWS")
    store.upsert_observations(conn, [o_before, o_at])
    orow = store.observations_before(conn, station, variable, as_of)
    check(len(orow) == 1 and orow[0].observed_at == o_before.observed_at,
          f"observations_before boundary violated: {[r.observed_at for r in orow]}")
    check(all(r.observed_at < as_of for r in orow),
          "observations_before returned observed_at >= as_of")


def test_signal_and_backtest_round_trip(conn):
    market = MarketRow(
        venue="kalshi", external_id="KXSIG-TEST", question="signal round trip",
        category="weather", outcomes=(OutcomeRef("KXSIG-TEST-YES", "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    run_id = f"test-run-{uuid.uuid4().hex[:8]}"
    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    store.write_backtest_run(
        conn, run_id, prob_fn_name="MidpriceProbFn", category="weather",
        window_start=as_of, window_end=as_of + timedelta(days=1), step="1h",
        params={"note": "test"})

    signal = DirectionalSignal(
        token_id="KXSIG-TEST-YES", venue="kalshi", category="weather",
        p_model=0.6, price=0.5, size=100.0, ev_per_share=0.08,
        expected_profit=8.0, kelly_size=120.0)
    store.write_signal(conn, run_id, signal, as_of)

    p_model, price, size, prob_fn_name = conn.execute(
        "SELECT p_model, price, size, prob_fn_name FROM directional_signal "
        "WHERE run_id = %s", (run_id,)).fetchone()
    row = (float(p_model), float(price), float(size), prob_fn_name)
    check(row == (0.6, 0.5, 100.0, "MidpriceProbFn"), f"signal round-trip mismatch: {row}")

    store.write_backtest_result(
        conn, run_id, "KXSIG-TEST-YES", entry_as_of=as_of, entry_price=0.5,
        size=100.0, resolved_value=1.0, fee_paid=0.35, realized_pnl=49.65)

    # idempotent re-run of both writes
    store.write_signal(conn, run_id, signal, as_of)
    store.write_backtest_result(
        conn, run_id, "KXSIG-TEST-YES", entry_as_of=as_of, entry_price=0.5,
        size=100.0, resolved_value=1.0, fee_paid=0.35, realized_pnl=49.65)

    n = conn.execute(
        "SELECT count(*) FROM directional_signal WHERE run_id = %s", (run_id,)).fetchone()[0]
    check(n == 1, f"write_signal not idempotent: {n} rows for one (run_id, as_of, outcome_id)")
    n = conn.execute(
        "SELECT count(*) FROM backtest_result WHERE run_id = %s", (run_id,)).fetchone()[0]
    check(n == 1, f"write_backtest_result not idempotent: {n} rows")


def test_unknown_token_id_raises(conn):
    try:
        store.candles_before(conn, "no-such-token", datetime.now(timezone.utc))
        raise AssertionError("candles_before(unknown token_id) should raise KeyError")
    except KeyError:
        pass


def test_naive_as_of_rejected(conn):
    """A naive as_of (no tzinfo) must be rejected up front — see store.py's
    _require_aware: Postgres would otherwise interpret it in the session
    timezone, silently shifting the `< as_of` PIT boundary (ADR-0009)."""
    naive = datetime(2026, 7, 19, 12, 0, 0)   # no tzinfo

    def expect_value_error(fn, *args):
        try:
            fn(conn, *args, naive)
            raise AssertionError(f"{fn.__name__} should reject a naive as_of")
        except ValueError:
            pass

    expect_value_error(store.candles_before, "no-such-token")
    expect_value_error(store.forecasts_before, "KNYC", "tmax_f")
    expect_value_error(store.observations_before, "KNYC", "tmax_f")


def test_write_signal_unknown_run_raises(conn):
    """With directional_signal.run_id FK'd to backtest_run(run_id), writing a
    signal against a run that was never recorded via write_backtest_run must
    raise, not silently insert a row with prob_fn_name = NULL."""
    market = MarketRow(
        venue="kalshi", external_id="KXSIG-BADRUN", question="unknown run fk check",
        category="weather", outcomes=(OutcomeRef("KXSIG-BADRUN-YES", "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    signal = DirectionalSignal(
        token_id="KXSIG-BADRUN-YES", venue="kalshi", category="weather",
        p_model=0.6, price=0.5, size=100.0, ev_per_share=0.08,
        expected_profit=8.0, kelly_size=120.0)
    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    try:
        store.write_signal(conn, "no-such-run-id", signal, as_of)
        raise AssertionError(
            "write_signal against a nonexistent run_id should raise "
            "(FK violation), not silently write NULL prob_fn_name")
    except psycopg.IntegrityError:
        pass


# ---------------------------------------------------------------------------
def main() -> int:
    dsn = _provision()
    if dsn is None:
        print("SKIPPED: no Postgres reachable — set $DATABASE_URL, or "
              "`pip install pgserver` for a throwaway local instance "
              "(see README 'Database setup').")
        return 0

    print(f"provisioned throwaway test database")
    os.environ["DATABASE_URL"] = dsn
    conn = store.connect()
    failures = 0
    try:
        _apply_schema(conn)

        tests = [
            test_round_trip_market_candle_resolution,
            test_idempotent_rerun,
            test_pit_boundary_exact_as_of,
            test_signal_and_backtest_round_trip,
            test_unknown_token_id_raises,
            test_naive_as_of_rejected,
            test_write_signal_unknown_run_raises,
        ]
        for t in tests:
            try:
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
        _teardown(dsn)

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
