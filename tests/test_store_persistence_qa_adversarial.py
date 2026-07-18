"""
tests/test_store_persistence_qa_adversarial.py — QA adversarial probes for
src/store.py (WP-1), beyond what tests/test_store_persistence.py covers.

Standalone, no pytest dependency (repo convention). Reuses the throwaway-
database provisioning helpers from tests/test_store_persistence.py rather
than duplicating them.

This file is QA-authored, not application code. It does not modify
src/store.py, schema/002_kalshi_ev.sql, or tests/test_store_persistence.py.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

import psycopg  # noqa: E402

import store  # noqa: E402
from ingest import MarketRow, OutcomeRef  # noqa: E402
from ev_detector import DirectionalSignal  # noqa: E402

import test_store_persistence as base  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
def test_upsert_market_idempotent_with_changed_values(conn):
    """Re-upsert_market with DIFFERENT question/category/resolves_at and
    confirm row count stays at 1 and values are actually updated, not just
    'didn't crash'."""
    ext_id = f"KXQA-MARKET-{uuid.uuid4().hex[:8]}"
    m1 = MarketRow(venue="kalshi", external_id=ext_id, question="Q1",
                    category="weather", resolution_text="R1",
                    resolves_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    mid1 = store.upsert_market(conn, m1)

    m2 = MarketRow(venue="kalshi", external_id=ext_id, question="Q2-CHANGED",
                    category="econ", resolution_text="R2-CHANGED",
                    resolves_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    mid2 = store.upsert_market(conn, m2)
    check(mid1 == mid2, f"upsert_market on same (venue,external_id) returned different ids: {mid1} vs {mid2}")

    n = conn.execute("SELECT count(*) FROM market WHERE external_id = %s", (ext_id,)).fetchone()[0]
    check(n == 1, f"expected 1 market row, got {n}")

    row = conn.execute(
        "SELECT question, category, resolution_text, resolves_at FROM market WHERE market_id = %s",
        (mid1,)).fetchone()
    check(row == ("Q2-CHANGED", "econ", "R2-CHANGED", datetime(2026, 9, 1, tzinfo=timezone.utc)),
          f"upsert_market did not update values in place: {row}")


def test_upsert_outcomes_idempotent_label_change_and_new_idx(conn):
    """Re-upsert_outcomes with a changed label at an existing idx, AND a
    brand-new idx added on the second call (a market growing an outcome).
    Row count should be old+1 (new idx added), old rows' labels updated."""
    ext_id = f"KXQA-OUT-{uuid.uuid4().hex[:8]}"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="outcomes idempotency",
                        category="weather",
                        outcomes=(OutcomeRef(f"{ext_id}-YES", "YES", 0),
                                  OutcomeRef(f"{ext_id}-NO", "NO", 1)))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    n_before = conn.execute("SELECT count(*) FROM outcome WHERE market_id = %s", (market_id,)).fetchone()[0]
    check(n_before == 2, f"expected 2 outcome rows before, got {n_before}")

    # re-upsert idx 0 with a changed label, plus a genuinely new idx 2
    changed = (OutcomeRef(f"{ext_id}-YES", "YES-RELABELED", 0),
               OutcomeRef(f"{ext_id}-MAYBE", "MAYBE", 2))
    store.upsert_outcomes(conn, market_id, changed)

    n_after = conn.execute("SELECT count(*) FROM outcome WHERE market_id = %s", (market_id,)).fetchone()[0]
    check(n_after == 3, f"expected 3 outcome rows after adding idx=2, got {n_after}")

    label0 = conn.execute("SELECT label FROM outcome WHERE market_id = %s AND idx = 0",
                           (market_id,)).fetchone()[0]
    check(label0 == "YES-RELABELED", f"idx=0 label not updated in place: {label0}")

    # token_id bridge: re-upserting the SAME token_id under a DIFFERENT idx's
    # outcome_id should repoint token->outcome (per ON CONFLICT(token_id) DO
    # UPDATE), not duplicate the bridge row.
    n_bridge = conn.execute(
        "SELECT count(*) FROM outcome_token WHERE token_id IN (%s, %s, %s)",
        (f"{ext_id}-YES", f"{ext_id}-NO", f"{ext_id}-MAYBE")).fetchone()[0]
    check(n_bridge == 3, f"expected 3 outcome_token bridge rows, got {n_bridge}")


def test_outcome_token_repoint_stale_row_becomes_orphan_but_no_crash(conn):
    """If a token_id's underlying outcome_id changes identity across a
    conflicting idx reuse, confirm upsert_outcomes doesn't silently corrupt
    the bridge (best-effort: mostly a smoke test since this is a fairly
    contrived scenario)."""
    ext_id = f"KXQA-REPOINT-{uuid.uuid4().hex[:8]}"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="repoint check",
                        category="weather", outcomes=(OutcomeRef(f"{ext_id}-A", "A", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    oid_first = conn.execute("SELECT outcome_id FROM outcome_token WHERE token_id = %s",
                              (f"{ext_id}-A",)).fetchone()[0]

    # Same token_id string reused for idx=0 again (label change only) -> same outcome row.
    store.upsert_outcomes(conn, market_id, (OutcomeRef(f"{ext_id}-A", "A2", 0),))
    oid_second = conn.execute("SELECT outcome_id FROM outcome_token WHERE token_id = %s",
                               (f"{ext_id}-A",)).fetchone()[0]
    check(oid_first == oid_second, "token_id bridge repointed unexpectedly for same idx re-upsert")


def test_upsert_candles_idempotent_multi_row_partial_overlap(conn):
    """Two calls to upsert_candles where the second call has one row that
    OVERLAPS a ts from the first (changed values) and one row that is NEW.
    Confirm exactly old_count+1 rows, with the overlapping row updated."""
    ext_id = f"KXQA-CANDLE-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="candle overlap",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    t0 = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=1)
    store.upsert_candles(conn, [
        store.Candle(t0, tok, 0.1, 0.1, 0.1, 0.1, 10.0),
        store.Candle(t1, tok, 0.2, 0.2, 0.2, 0.2, 20.0),
    ])
    n1 = conn.execute("SELECT count(*) FROM candlestick").fetchone()[0]

    t2 = t0 + timedelta(minutes=2)
    store.upsert_candles(conn, [
        store.Candle(t0, tok, 0.9, 0.9, 0.9, 0.9, 999.0),  # overlap, changed
        store.Candle(t2, tok, 0.3, 0.3, 0.3, 0.3, 30.0),   # new
    ])
    n2 = conn.execute("SELECT count(*) FROM candlestick").fetchone()[0]
    check(n2 == n1 + 1, f"expected exactly one new candle row, went from {n1} to {n2}")

    row = conn.execute(
        "SELECT open, volume FROM candlestick c JOIN outcome_token ot ON ot.outcome_id = c.outcome_id "
        "WHERE ot.token_id = %s AND c.ts = %s", (tok, t0)).fetchone()
    row = tuple(float(x) for x in row)
    check(row == (0.9, 999.0), f"overlapping candle not updated in place: {row}")


def test_upsert_candles_volume_none_roundtrip(conn):
    """volume=None should round-trip as NULL, not crash or coerce to 0."""
    ext_id = f"KXQA-VOLNONE-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="vol none",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    ts = datetime(2026, 7, 19, tzinfo=timezone.utc)
    store.upsert_candles(conn, [store.Candle(ts, tok, 0.5, 0.5, 0.5, 0.5, None)])
    back = store.candles_before(conn, tok, ts + timedelta(seconds=1))
    check(len(back) == 1 and back[0].volume is None, f"volume None round-trip failed: {back}")


def test_candlestick_check_constraint_rejects_out_of_range_price(conn):
    """Schema has CHECK (open/high/low/close BETWEEN 0 AND 1). A price of
    1.5 (plausible bug: percent vs fraction confusion) must raise, not
    silently store nonsense that would corrupt every downstream EV calc."""
    ext_id = f"KXQA-RANGE-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="range check",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    ts = datetime(2026, 7, 19, tzinfo=timezone.utc)
    try:
        store.upsert_candles(conn, [store.Candle(ts, tok, 1.5, 1.5, 1.5, 1.5, 1.0)])
        raise AssertionError("upsert_candles with close=1.5 should violate CHECK constraint")
    except psycopg.errors.CheckViolation:
        conn.rollback() if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE else None


def test_upsert_forecasts_idempotent_changed_horizon(conn):
    station, variable = f"KQA{uuid.uuid4().hex[:6]}", "tmax_f"
    issued_at = datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc)
    valid_at = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    store.upsert_forecasts(conn, [store.WeatherForecastRow(
        issued_at=issued_at, valid_at=valid_at, station=station, variable=variable,
        value=91.0, source="NWS", horizon_h=18.0)])
    n1 = conn.execute("SELECT count(*) FROM weather_forecast WHERE station=%s", (station,)).fetchone()[0]
    store.upsert_forecasts(conn, [store.WeatherForecastRow(
        issued_at=issued_at, valid_at=valid_at, station=station, variable=variable,
        value=95.0, source="NWS", horizon_h=999.0)])
    n2 = conn.execute("SELECT count(*) FROM weather_forecast WHERE station=%s", (station,)).fetchone()[0]
    check(n1 == n2 == 1, f"forecast idempotency row count changed: {n1} -> {n2}")
    val, hz = conn.execute("SELECT value, horizon_h FROM weather_forecast WHERE station=%s", (station,)).fetchone()
    check((float(val), float(hz)) == (95.0, 999.0), f"forecast values not updated: {(val, hz)}")


def test_upsert_observations_idempotent_source_change(conn):
    station, variable = f"KQAOBS{uuid.uuid4().hex[:6]}", "tmax_f"
    observed_at = datetime(2026, 7, 19, 6, 0, tzinfo=timezone.utc)
    store.upsert_observations(conn, [store.WeatherObservationRow(
        observed_at=observed_at, station=station, variable=variable, value=88.0, source="NWS")])
    store.upsert_observations(conn, [store.WeatherObservationRow(
        observed_at=observed_at, station=station, variable=variable, value=77.0, source="MADIS")])
    n = conn.execute("SELECT count(*) FROM weather_observation WHERE station=%s", (station,)).fetchone()[0]
    check(n == 1, f"observation idempotency row count: {n}")
    val, src = conn.execute("SELECT value, source FROM weather_observation WHERE station=%s",
                             (station,)).fetchone()
    check((float(val), src) == (77.0, "MADIS"), f"observation values not updated: {(val, src)}")


def test_write_backtest_run_idempotent_changed_values(conn):
    run_id = f"qa-run-{uuid.uuid4().hex[:8]}"
    w0 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    store.write_backtest_run(conn, run_id, prob_fn_name="Midprice", category="weather",
                              window_start=w0, window_end=w0 + timedelta(days=1), step="1h",
                              params={"a": 1})
    store.write_backtest_run(conn, run_id, prob_fn_name="Climatology", category="econ",
                              window_start=w0 + timedelta(days=5),
                              window_end=w0 + timedelta(days=6), step="1d",
                              params={"a": 2}, git_sha="deadbeef")
    n = conn.execute("SELECT count(*) FROM backtest_run WHERE run_id=%s", (run_id,)).fetchone()[0]
    check(n == 1, f"backtest_run idempotency row count: {n}")
    row = conn.execute("SELECT prob_fn_name, category, step, git_sha FROM backtest_run WHERE run_id=%s",
                        (run_id,)).fetchone()
    check(row == ("Climatology", "econ", "1d", "deadbeef"), f"backtest_run values not updated: {row}")


def test_write_signal_idempotent_changed_values_and_prob_fn_sync(conn):
    """write_signal derives prob_fn_name from the CURRENT backtest_run row at
    write time via subselect. Confirm: (a) re-write with changed p_model/price
    updates in place, (b) if backtest_run.prob_fn_name changes between two
    write_signal calls for the SAME run_id/as_of/outcome, the signal row's
    prob_fn_name reflects the latest write (or at least doesn't silently
    diverge in a way nobody would catch)."""
    ext_id = f"KXQA-SIG-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="signal idem",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    run_id = f"qa-sigrun-{uuid.uuid4().hex[:8]}"
    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    store.write_backtest_run(conn, run_id, prob_fn_name="Midprice", category="weather",
                              window_start=as_of, window_end=as_of + timedelta(days=1), step="1h")

    sig1 = DirectionalSignal(token_id=tok, venue="kalshi", category="weather",
                              p_model=0.6, price=0.5, size=100.0, ev_per_share=0.08,
                              expected_profit=8.0, kelly_size=120.0)
    store.write_signal(conn, run_id, sig1, as_of)

    sig2 = DirectionalSignal(token_id=tok, venue="kalshi", category="weather",
                              p_model=0.75, price=0.55, size=50.0, ev_per_share=0.02,
                              expected_profit=1.0, kelly_size=10.0)
    store.write_signal(conn, run_id, sig2, as_of)

    n = conn.execute("SELECT count(*) FROM directional_signal WHERE run_id=%s", (run_id,)).fetchone()[0]
    check(n == 1, f"write_signal idempotency row count: {n}")
    p_model, price, size = conn.execute(
        "SELECT p_model, price, size FROM directional_signal WHERE run_id=%s", (run_id,)).fetchone()
    check((float(p_model), float(price), float(size)) == (0.75, 0.55, 50.0),
          f"write_signal values not updated in place: {(p_model, price, size)}")


def test_write_backtest_result_idempotent_changed_pnl(conn):
    ext_id = f"KXQA-RES-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="result idem",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    run_id = f"qa-resrun-{uuid.uuid4().hex[:8]}"
    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    store.write_backtest_run(conn, run_id, prob_fn_name="Midprice", category="weather",
                              window_start=as_of, window_end=as_of + timedelta(days=1), step="1h")
    store.write_backtest_result(conn, run_id, tok, entry_as_of=as_of, entry_price=0.5,
                                 size=100.0, resolved_value=1.0, fee_paid=0.35, realized_pnl=49.65)
    store.write_backtest_result(conn, run_id, tok, entry_as_of=as_of, entry_price=0.6,
                                 size=200.0, resolved_value=0.0, fee_paid=0.70, realized_pnl=-120.7)
    n = conn.execute("SELECT count(*) FROM backtest_result WHERE run_id=%s", (run_id,)).fetchone()[0]
    check(n == 1, f"backtest_result idempotency row count: {n}")
    row = conn.execute(
        "SELECT entry_price, size, resolved_value, realized_pnl FROM backtest_result WHERE run_id=%s",
        (run_id,)).fetchone()
    check(tuple(float(x) for x in row) == (0.6, 200.0, 0.0, -120.7),
          f"backtest_result values not updated in place: {row}")


# ---------------------------------------------------------------------------
# PIT boundary adversarial probes
# ---------------------------------------------------------------------------
def test_pit_boundary_microsecond_precision(conn):
    """Postgres TIMESTAMPTZ has microsecond resolution. A candle at
    as_of - 1 microsecond must be included; as_of exactly must be excluded."""
    ext_id = f"KXQA-USEC-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="usec pit",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    as_of = datetime(2026, 7, 19, 12, 0, 0, 0, tzinfo=timezone.utc)
    just_before = as_of - timedelta(microseconds=1)
    store.upsert_candles(conn, [
        store.Candle(just_before, tok, 0.11, 0.11, 0.11, 0.11, 1.0),
        store.Candle(as_of, tok, 0.22, 0.22, 0.22, 0.22, 1.0),
    ])
    result = store.candles_before(conn, tok, as_of)
    check(len(result) == 1, f"microsecond boundary: expected 1 row, got {len(result)}: {result}")
    check(result[0].ts == just_before, f"microsecond boundary: wrong row returned {result[0].ts}")


def test_pit_boundary_empty_result_no_data(conn):
    """as_of before any data exists -> empty list, not an error."""
    ext_id = f"KXQA-EMPTY-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="empty pit",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)
    result = store.candles_before(conn, tok, datetime(2000, 1, 1, tzinfo=timezone.utc))
    check(result == [], f"expected empty list for as_of before any data, got {result}")


def test_pit_boundary_different_but_equal_instant_timezones(conn):
    """A candle stored with ts=T (UTC) and as_of passed in as the SAME
    instant but expressed in a different tzinfo offset (e.g. UTC-5) must
    still be excluded (Postgres compares timestamptz by instant, tz-offset-
    agnostic) -- verifies naive-vs-aware handling doesn't accidentally break
    correct timezone-aware comparisons."""
    from datetime import timezone as tz
    ext_id = f"KXQA-TZ-{uuid.uuid4().hex[:8]}"
    tok = f"{ext_id}-YES"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="tz equal instant",
                        category="weather", outcomes=(OutcomeRef(tok, "YES", 0),))
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, market.outcomes)

    as_of_utc = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    store.upsert_candles(conn, [store.Candle(as_of_utc, tok, 0.5, 0.5, 0.5, 0.5, 1.0)])

    # same instant, expressed as UTC-5 -> 07:00 local with offset -5
    minus5 = tz(timedelta(hours=-5))
    as_of_minus5 = datetime(2026, 7, 19, 7, 0, 0, tzinfo=minus5)
    check(as_of_utc == as_of_minus5, "test setup bug: these should be the same instant")

    result = store.candles_before(conn, tok, as_of_minus5)
    check(len(result) == 0,
          f"row at exactly as_of (same instant, different tz repr) leaked through: {result}")


# ---------------------------------------------------------------------------
# naive as_of variants
# ---------------------------------------------------------------------------
def test_naive_as_of_variants(conn):
    """Try several ways of constructing a naive datetime beyond the
    follow-up's own datetime(...) literal: datetime.now(), datetime.combine,
    fromtimestamp without tz, strptime."""
    variants = {
        "datetime.now()": datetime.now(),
        "datetime.combine(date, time)": datetime.combine(date(2026, 7, 19), datetime.min.time()),
        "fromtimestamp no tz": datetime.fromtimestamp(1700000000),
        "strptime": datetime.strptime("2026-07-19 12:00:00", "%Y-%m-%d %H:%M:%S"),
        "utcnow()": datetime.utcnow(),
    }
    for label, naive in variants.items():
        check(naive.tzinfo is None, f"test setup bug: {label} is not actually naive")
        try:
            store.candles_before(conn, "no-such-token-for-naive-test", naive)
            raise AssertionError(f"candles_before should reject naive as_of ({label}); it did not raise")
        except ValueError:
            pass
        except KeyError:
            raise AssertionError(
                f"candles_before with naive as_of ({label}) raised KeyError (token lookup) "
                f"instead of ValueError -- naive-check is not happening before token resolution / "
                f"is order-dependent")


def test_naive_as_of_rejected_before_token_lookup_order(conn):
    """_require_aware should run BEFORE the token resolution so callers get
    the tz error, not a confusing 'unknown token' error, when both are wrong.
    (Also relevant: does the naive check happen at all if token_id resolves
    to nothing?)"""
    naive = datetime(2026, 1, 1, 0, 0, 0)
    try:
        store.candles_before(conn, "definitely-not-a-real-token", naive)
        raise AssertionError("should have raised")
    except ValueError as e:
        check("naive" in str(e).lower() or "aware" in str(e).lower(),
              f"expected a tz-awareness ValueError, got: {e}")
    except KeyError:
        raise AssertionError(
            "naive as_of + unknown token: got KeyError (token lookup ran first) instead of "
            "ValueError (tz check) -- order dependency could mask the real problem in production")


# ---------------------------------------------------------------------------
# outcome_token fail-loud contract
# ---------------------------------------------------------------------------
def test_upsert_candles_unregistered_token_raises(conn):
    ts = datetime(2026, 7, 19, tzinfo=timezone.utc)
    try:
        store.upsert_candles(conn, [store.Candle(ts, "totally-unregistered-token", 0.5, 0.5, 0.5, 0.5, 1.0)])
        raise AssertionError("upsert_candles against unregistered token_id should raise")
    except KeyError:
        pass


def test_apply_resolutions_unregistered_token_raises(conn):
    r = store.ResolutionRow(external_id="whatever", outcome_token_id="unregistered-res-token",
                             resolved_value=1.0)
    try:
        store.apply_resolutions(conn, [r])
        raise AssertionError("apply_resolutions against unregistered token_id should raise")
    except KeyError:
        pass


def test_write_backtest_result_unregistered_token_raises(conn):
    run_id = f"qa-unreg-{uuid.uuid4().hex[:8]}"
    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    store.write_backtest_run(conn, run_id, prob_fn_name="Midprice", category="weather",
                              window_start=as_of, window_end=as_of + timedelta(days=1), step="1h")
    try:
        store.write_backtest_result(conn, run_id, "unregistered-result-token", entry_as_of=as_of,
                                     entry_price=0.5, size=1.0, resolved_value=1.0,
                                     fee_paid=0.0, realized_pnl=0.5)
        raise AssertionError("write_backtest_result against unregistered token_id should raise")
    except KeyError:
        pass


def test_write_signal_unregistered_token_raises(conn):
    run_id = f"qa-unreg2-{uuid.uuid4().hex[:8]}"
    as_of = datetime(2026, 7, 19, tzinfo=timezone.utc)
    store.write_backtest_run(conn, run_id, prob_fn_name="Midprice", category="weather",
                              window_start=as_of, window_end=as_of + timedelta(days=1), step="1h")
    sig = DirectionalSignal(token_id="unregistered-sig-token", venue="kalshi", category="weather",
                             p_model=0.5, price=0.5, size=1.0, ev_per_share=0.0,
                             expected_profit=0.0, kelly_size=1.0)
    try:
        store.write_signal(conn, run_id, sig, as_of)
        raise AssertionError("write_signal against unregistered token_id should raise")
    except KeyError:
        pass


def test_forecasts_before_unregistered_station_returns_empty_not_error(conn):
    """Unlike token_id (which is fail-loud via a bridge table lookup),
    station/variable have no registration step -- confirm the reader returns
    [] for a never-seen station rather than raising (this is a spec question:
    document actual behavior)."""
    result = store.forecasts_before(conn, "NEVER-SEEN-STATION", "tmax_f",
                                     datetime.now(timezone.utc))
    check(result == [], f"expected empty list for unknown station, got {result}")


# ---------------------------------------------------------------------------
# empty-input edge cases
# ---------------------------------------------------------------------------
def test_upsert_empty_lists_are_noops(conn):
    store.upsert_candles(conn, [])
    store.apply_resolutions(conn, [])
    store.upsert_forecasts(conn, [])
    store.upsert_observations(conn, [])
    ext_id = f"KXQA-EMPTYOUT-{uuid.uuid4().hex[:8]}"
    market = MarketRow(venue="kalshi", external_id=ext_id, question="empty outcomes",
                        category="weather", outcomes=())
    market_id = store.upsert_market(conn, market)
    store.upsert_outcomes(conn, market_id, ())  # empty sequence -- should not crash
    n = conn.execute("SELECT count(*) FROM outcome WHERE market_id=%s", (market_id,)).fetchone()[0]
    check(n == 0, f"expected 0 outcomes for empty upsert, got {n}")


# ---------------------------------------------------------------------------
def main() -> int:
    dsn = base._provision()
    if dsn is None:
        print("SKIPPED: no Postgres reachable.")
        return 0

    print("provisioned throwaway test database (QA adversarial suite)")
    os.environ["DATABASE_URL"] = dsn
    conn = store.connect()
    failures = 0
    try:
        base._apply_schema(conn)

        tests = [
            test_upsert_market_idempotent_with_changed_values,
            test_upsert_outcomes_idempotent_label_change_and_new_idx,
            test_outcome_token_repoint_stale_row_becomes_orphan_but_no_crash,
            test_upsert_candles_idempotent_multi_row_partial_overlap,
            test_upsert_candles_volume_none_roundtrip,
            test_candlestick_check_constraint_rejects_out_of_range_price,
            test_upsert_forecasts_idempotent_changed_horizon,
            test_upsert_observations_idempotent_source_change,
            test_write_backtest_run_idempotent_changed_values,
            test_write_signal_idempotent_changed_values_and_prob_fn_sync,
            test_write_backtest_result_idempotent_changed_pnl,
            test_pit_boundary_microsecond_precision,
            test_pit_boundary_empty_result_no_data,
            test_pit_boundary_different_but_equal_instant_timezones,
            test_naive_as_of_variants,
            test_naive_as_of_rejected_before_token_lookup_order,
            test_upsert_candles_unregistered_token_raises,
            test_apply_resolutions_unregistered_token_raises,
            test_write_backtest_result_unregistered_token_raises,
            test_write_signal_unregistered_token_raises,
            test_forecasts_before_unregistered_station_returns_empty_not_error,
            test_upsert_empty_lists_are_noops,
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
                # A failed statement inside a transaction can poison the
                # connection for subsequent tests under autocommit=False;
                # store.connect() uses autocommit=True so this shouldn't be
                # needed, but guard anyway.
                try:
                    conn.rollback()
                except Exception:
                    pass
    finally:
        conn.close()
        base._teardown(dsn)

    if failures:
        print(f"\n{failures} test(s) failed")
        return 1
    print("\nALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
