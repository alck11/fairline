"""
tests/test_prob_fn.py — WP-2 acceptance tests for src/prob_fn.py.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_prob_fn.py`). The core tests need no database at all —
they exercise MidpriceProbFn/ClimatologyProbFn against a synthetic in-memory
Reader, so they always run. One extra test (test_store_reader_round_trip)
additionally exercises `prob_fn.StoreReader` against a real WP-1 store, using
the same optional-Postgres provisioning as tests/test_store_persistence.py;
it SKIPs (not fails) if no Postgres is reachable — see that file's docstring
for the two supported paths ($DATABASE_URL, or `pip install pgserver`).

Traces to docs/architecture/plan.md WP-2 acceptance (US-3 G/W/T):
  - MidpriceProbFn is deterministic and honors the `< as_of` boundary (a
    candle exactly at as_of must NOT be used)
  - output is clamped/validated to [0,1]
  - swapping MidpriceProbFn for a different ProbFn requires no interface
    change — both conform to and are usable interchangeably via the ProbFn
    Protocol
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import prob_fn                    # noqa: E402
from prob_fn import (             # noqa: E402
    ClimatologyProbFn, MarketRef, MidpriceProbFn, NoPriorDataError, ProbFn,
    Reader, StoreReader,
)
from store import Candle          # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# synthetic in-memory Reader — no network, no real Postgres. Mirrors
# store.py's PIT contract (`ts < as_of`, ordered ascending) in Python only
# because this is a *test double*, not production code bound by ADR-0009's
# "enforce it in SQL, not Python" rule (that rule binds store.py itself,
# which this fake stands in for).
# ---------------------------------------------------------------------------
class FakeReader:
    def __init__(self, candles: list[Candle]):
        self._candles = candles

    def candles_before(self, token_id: str, as_of: datetime) -> list[Candle]:
        rows = [c for c in self._candles
                if c.token_id == token_id and c.ts < as_of]
        return sorted(rows, key=lambda c: c.ts)

    def forecasts_before(self, station, variable, as_of):
        return []

    def observations_before(self, station, variable, as_of):
        return []


def _market(token_id="tok-yes") -> MarketRef:
    return MarketRef(
        external_id="KXHIGHNY-26JUL20-TEST", venue="kalshi", category="weather",
        outcome_token_id=token_id, outcome_label="YES",
        resolves_at=None, params={"station": "KNYC", "threshold_f": 90})


# ---------------------------------------------------------------------------
# acceptance tests
# ---------------------------------------------------------------------------
def test_midprice_deterministic_and_pit_boundary():
    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    reader = FakeReader([
        Candle(t0 - timedelta(hours=2), "tok-yes", 0.18, 0.22, 0.17, 0.20, 100.0),
        Candle(t0 - timedelta(hours=1), "tok-yes", 0.20, 0.26, 0.19, 0.25, 200.0),
        # this candle sits exactly at as_of and must NOT be used
        Candle(t0, "tok-yes", 0.25, 0.99, 0.25, 0.99, 300.0),
        Candle(t0 + timedelta(hours=1), "tok-yes", 0.99, 0.99, 0.90, 0.95, 400.0),
    ])
    pf = MidpriceProbFn(reader)
    market = _market()

    p1 = pf(market, t0)
    p2 = pf(market, t0)   # calling again must yield the identical answer
    check(p1 == p2, f"MidpriceProbFn is not deterministic: {p1} vs {p2}")
    check(p1 == 0.25,
          f"expected last close strictly before as_of (0.25 from the "
          f"t0-1h candle), got {p1} — the candle *at* as_of (close=0.99) "
          f"must not have been used")


def test_midprice_boundary_excludes_at_as_of_even_when_it_is_only_candle():
    """If the only candle is exactly at as_of, that is indistinguishable from
    having no prior data at all — must raise, not fall through to it."""
    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    reader = FakeReader([Candle(t0, "tok-yes", 0.5, 0.5, 0.5, 0.5, 10.0)])
    pf = MidpriceProbFn(reader)
    try:
        pf(_market(), t0)
        raise AssertionError(
            "MidpriceProbFn should raise when the only candle is exactly "
            "at as_of (not strictly before)")
    except NoPriorDataError:
        pass


def test_midprice_no_prior_data_raises():
    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    pf = MidpriceProbFn(FakeReader([]))
    try:
        pf(_market(), t0)
        raise AssertionError("MidpriceProbFn should raise on empty history")
    except NoPriorDataError:
        pass


def test_output_clamped_to_unit_interval():
    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    high = FakeReader([Candle(t0 - timedelta(hours=1), "tok-yes",
                               1.0, 1.6, 0.9, 1.50, 10.0)])
    p_high = MidpriceProbFn(high)(_market(), t0)
    check(p_high == 1.0, f"close=1.50 must clamp to 1.0, got {p_high}")

    low = FakeReader([Candle(t0 - timedelta(hours=1), "tok-yes",
                              0.0, 0.1, -0.3, -0.20, 10.0)])
    p_low = MidpriceProbFn(low)(_market(), t0)
    check(p_low == 0.0, f"close=-0.20 must clamp to 0.0, got {p_low}")

    normal = FakeReader([Candle(t0 - timedelta(hours=1), "tok-yes",
                                 0.4, 0.5, 0.3, 0.42, 10.0)])
    p_normal = MidpriceProbFn(normal)(_market(), t0)
    check(0.0 <= p_normal <= 1.0, f"in-range close must stay unclamped: {p_normal}")
    check(p_normal == 0.42, f"in-range close must pass through unchanged: {p_normal}")


def test_climatology_prob_fn_conforms_and_ignores_market():
    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    pf = ClimatologyProbFn(0.35)
    check(pf.name == "ClimatologyProbFn", f"unexpected name: {pf.name}")
    p_a = pf(_market("tok-yes"), t0)
    p_b = pf(_market("tok-other"), t0 + timedelta(days=100))
    check(p_a == p_b == 0.35,
          f"ClimatologyProbFn must be a fixed base rate regardless of "
          f"market/as_of: {p_a}, {p_b}")

    try:
        ClimatologyProbFn(1.5)
        raise AssertionError("ClimatologyProbFn must reject base_rate outside [0,1]")
    except ValueError:
        pass


def test_probfn_implementations_are_interchangeable():
    """The whole point of the contract: a call site written against `ProbFn`
    works unmodified for MidpriceProbFn, ClimatologyProbFn, or a third,
    entirely unrelated implementation — no interface changes needed."""

    class StubProbFn:
        """A minimal third-party-style ProbFn, deliberately NOT sharing any
        base class with MidpriceProbFn/ClimatologyProbFn, to prove the
        Protocol (structural typing), not inheritance, is what's required."""
        name = "StubProbFn"

        def __init__(self, fixed_p: float):
            self._fixed_p = fixed_p

        def __call__(self, market: MarketRef, as_of: datetime) -> float:
            return self._fixed_p

    def call_site(pf: "ProbFn", market: MarketRef, as_of: datetime) -> float:
        """Stands in for the WP-4 harness call site: takes anything typed as
        ProbFn and calls it uniformly."""
        p = pf(market, as_of)
        check(0.0 <= p <= 1.0, f"{pf.name} returned out-of-range p={p}")
        return p

    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    reader = FakeReader([Candle(t0 - timedelta(hours=1), "tok-yes",
                                 0.3, 0.4, 0.2, 0.33, 10.0)])
    market = _market()

    implementations = [
        MidpriceProbFn(reader),
        ClimatologyProbFn(0.5),
        StubProbFn(0.77),
    ]
    results = {pf.name: call_site(pf, market, t0) for pf in implementations}
    check(results == {"MidpriceProbFn": 0.33, "ClimatologyProbFn": 0.5,
                       "StubProbFn": 0.77}, f"unexpected results: {results}")

    # structural typing: every implementation satisfies the runtime-checkable
    # ProbFn Protocol, despite sharing no base class.
    for pf in implementations:
        check(isinstance(pf, ProbFn),
              f"{type(pf).__name__} does not structurally satisfy ProbFn")


def test_store_reader_conforms_to_reader_protocol():
    """StoreReader itself must satisfy the Reader protocol MidpriceProbFn is
    constructed with — checked structurally, no real connection needed."""
    class _DummyConn:
        pass

    reader = StoreReader(_DummyConn())
    check(isinstance(reader, Reader), "StoreReader does not satisfy Reader protocol")
    check(hasattr(reader, "candles_before"), "StoreReader missing candles_before")


# ---------------------------------------------------------------------------
# optional: StoreReader against a real WP-1 store (skips without Postgres)
# ---------------------------------------------------------------------------
def _try_store_round_trip() -> tuple[bool, str]:
    """Returns (ran, message). Mirrors test_store_persistence.py's
    provisioning so this file stays runnable with zero setup (SKIP) or with
    the same $DATABASE_URL / pgserver paths that file documents."""
    try:
        import psycopg
        import psycopg.conninfo as conninfo
    except ImportError:
        return False, "psycopg not importable"

    def base_conninfo():
        url = os.environ.get("DATABASE_URL")
        if url:
            return url, None
        try:
            import pgserver
        except ImportError:
            return "", None
        data_dir = os.path.join(os.path.dirname(__file__), ".pgserver-test-data")
        srv = pgserver.get_server(data_dir)
        return srv.get_uri(), srv

    base, server = base_conninfo()
    if not base:
        return False, "no Postgres reachable (see test_store_persistence.py)"

    info = conninfo.conninfo_to_dict(base)
    maint = dict(info)
    maint.setdefault("dbname", "postgres")
    try:
        admin = psycopg.connect(conninfo.make_conninfo(**maint), autocommit=True,
                                connect_timeout=5)
    except Exception as e:
        return False, f"could not reach Postgres: {e}"

    db_name = f"fairline_test_{uuid.uuid4().hex[:12]}"
    admin.execute(f'CREATE DATABASE "{db_name}"')
    admin.close()
    test_info = dict(info)
    test_info["dbname"] = db_name
    dsn = conninfo.make_conninfo(**test_info)

    import store
    from ingest import MarketRow, OutcomeRef

    conn = None
    try:
        conn = psycopg.connect(dsn, autocommit=True)
        for path in (
            os.path.join(os.path.dirname(__file__), "..", "schema", "001_schema.sql"),
            os.path.join(os.path.dirname(__file__), "..", "schema", "002_kalshi_ev.sql"),
        ):
            with open(path) as fh:
                sql = "\n".join(line.split("--", 1)[0] for line in fh.read().splitlines())
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                try:
                    conn.execute(stmt)
                except Exception as e:
                    if "timescaledb" in stmt.lower() or "create_hypertable" in stmt.lower():
                        continue
                    raise RuntimeError(f"schema statement failed:\n{stmt}\n-> {e}") from e

        market = MarketRow(
            venue="kalshi", external_id="KXPROBFN-TEST", question="prob_fn store round trip",
            category="weather", outcomes=(OutcomeRef("KXPROBFN-TEST-YES", "YES", 0),))
        market_id = store.upsert_market(conn, market)
        store.upsert_outcomes(conn, market_id, market.outcomes)

        t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        store.upsert_candles(conn, [
            store.Candle(t0 - timedelta(hours=1), "KXPROBFN-TEST-YES",
                         0.2, 0.3, 0.15, 0.28, 50.0),
            store.Candle(t0, "KXPROBFN-TEST-YES", 0.9, 0.9, 0.9, 0.9, 50.0),
        ])

        reader = StoreReader(conn)
        pf = MidpriceProbFn(reader)
        market_ref = MarketRef(
            external_id="KXPROBFN-TEST", venue="kalshi", category="weather",
            outcome_token_id="KXPROBFN-TEST-YES", outcome_label="YES",
            resolves_at=None, params={})
        p = pf(market_ref, t0)
        check(p == 0.28,
              f"StoreReader-backed MidpriceProbFn should see the t0-1h "
              f"candle (0.28), not the one at t0 (0.9); got {p}")
        return True, "ok"
    finally:
        if conn is not None:
            conn.close()
        try:
            cleanup_info = dict(info)
            cleanup_conn = psycopg.connect(
                conninfo.make_conninfo(**{k: v for k, v in cleanup_info.items()
                                           if k != "dbname"}),
                autocommit=True)
            cleanup_conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            cleanup_conn.close()
        finally:
            if server is not None:
                server.cleanup()


def test_store_reader_round_trip():
    """Returns the sentinel "skipped" (instead of a bare `return`) when no
    Postgres is reachable, so the runner can count it separately from a pass
    — this is the one test that proves MidpriceProbFn honors the `< as_of`
    boundary through the real SQL path in store.py, so its absence must show
    up in the summary, not disappear into an unqualified "ALL PASSED"."""
    ran, msg = _try_store_round_trip()
    if not ran:
        print(f"  (SKIPPED — {msg})")
        return "skipped"
    # _try_store_round_trip raises AssertionError itself on mismatch; if we
    # got here with ran=True it already passed its internal check().


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_midprice_deterministic_and_pit_boundary,
        test_midprice_boundary_excludes_at_as_of_even_when_it_is_only_candle,
        test_midprice_no_prior_data_raises,
        test_output_clamped_to_unit_interval,
        test_climatology_prob_fn_conforms_and_ignores_market,
        test_probfn_implementations_are_interchangeable,
        test_store_reader_conforms_to_reader_protocol,
        test_store_reader_round_trip,
    ]
    failures = 0
    skipped = 0
    for t in tests:
        try:
            result = t()
            if result == "skipped":
                skipped += 1
                print(f"SKIP: {t.__name__}")
            else:
                print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")

    passed = len(tests) - failures - skipped
    if failures:
        print(f"\n{passed} passed, {skipped} skipped, {failures} failed")
        return 1
    if skipped:
        print(f"\n{passed} passed, {skipped} skipped (no Postgres reachable)")
    else:
        print(f"\n{passed} passed, 0 skipped — ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
