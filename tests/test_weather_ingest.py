"""
tests/test_weather_ingest.py — WP-6 tests for src/weather_ingest.py.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_weather_ingest.py`). NO LIVE NETWORK: every test
monkeypatches `urllib.request.urlopen` to route through recorded fixture
responses under tests/fixtures/iem/ instead of hitting IEM's real API. Those
fixtures (mos_knyc_nbs.json, daily_nyc_2026_06.json) were captured live on
2026-07-20 against https://mesonet.agron.iastate.edu/api/1 and trimmed to a few
rows — the point is to freeze *real* IEM JSON shapes so WeatherSource's parsing is
tested against ground truth, not a hand-rolled guess at the schema (plan.md WP-6 /
ADR-0011).

Traces to plan.md WP-6 acceptance (US-4 data G/W/T):
  - forecast history loads with issued_at < valid_at on every row (PIT key from
    MOS runtime_utc, never back-filled from valid_at)
  - observations cover the requested dates; re-running does not duplicate rows
  - a malformed/unreachable API surfaces as a clear WeatherAPIError, non-zero exit
"""
import contextlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import store  # noqa: E402
import weather_ingest  # noqa: E402
import run_weather_ingest  # noqa: E402
from weather_ingest import (  # noqa: E402
    WeatherAPIError, WeatherSource, WeatherStation, resolve_station,
    STATIONS, SERIES_STATION,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "iem")


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
    path = parsed.path.split("/api/1", 1)[-1]
    query = dict(urllib.parse.parse_qsl(parsed.query))
    return path, query


def install_fixture_router(router):
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
    if path == "/mos.json":
        return _load("mos_knyc_nbs.json")
    if path == "/daily.json":
        return _load("daily_nyc_2026_06.json")
    raise AssertionError(f"unmocked IEM path in test fixture router: {path}")


# ---------------------------------------------------------------------------
# station resolution
# ---------------------------------------------------------------------------
def test_resolve_station_icao_series_and_unknown():
    st = resolve_station("KNYC")
    check(isinstance(st, WeatherStation) and st.icao == "KNYC", f"ICAO lookup failed: {st}")
    check(st.iem_network == "NY_ASOS" and st.iem_daily_station == "NYC",
          f"KNYC IEM addressing wrong: {st}")
    # a Kalshi series prefix resolves to its curated station
    check(resolve_station("KXHIGHNY").icao == SERIES_STATION["KXHIGHNY"] == "KNYC",
          "series-prefix resolution failed")
    # a WeatherStation passes through unchanged
    check(resolve_station(st) is st, "WeatherStation should pass through")
    # unknown raises ValueError (no silent miss, no network)
    try:
        resolve_station("NOTASTATION")
        raise AssertionError("unknown station should raise ValueError")
    except ValueError as e:
        check("NOTASTATION" in str(e), f"error should name the bad station: {e}")


# ---------------------------------------------------------------------------
# forecasts — PIT keys from MOS runtime_utc/ftime_utc
# ---------------------------------------------------------------------------
def test_forecasts_parse_and_pit_keys():
    calls, restore = install_fixture_router(default_router)
    try:
        rows = WeatherSource().forecasts("KNYC")
    finally:
        restore()

    raw = _load("mos_knyc_nbs.json")["data"]
    check(len(rows) == len(raw), f"expected {len(raw)} forecast rows, got {len(rows)}")
    f = rows[0]
    check(f.issued_at == datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc),
          f"issued_at must come from runtime_utc: {f.issued_at}")
    check(f.valid_at == datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc),
          f"valid_at must come from ftime_utc: {f.valid_at}")
    check(f.station == "KNYC" and f.variable == "tmpf", f"station/variable wrong: {f}")
    check(f.value == 72.0, f"value must come from `tmp`: {f.value}")
    check(f.source == "iem-mos-nbs", f"source must be namespaced iem-mos-<model>: {f.source}")
    check(f.horizon_h == 6.0, f"horizon_h must be valid-issued in hours: {f.horizon_h}")
    # the load-bearing PIT invariant, on EVERY row
    check(all(r.issued_at < r.valid_at for r in rows),
          "every forecast row must have issued_at < valid_at (WP-6 acceptance)")


def test_forecasts_skip_null_tmp():
    """A MOS row with tmp=null carries no temperature to store — skipped, not an
    error and not a row with a bogus value."""
    def router(path, query):
        return {"data": [
            {"station": "KNYC", "runtime_utc": "2026-07-21T00:00:00.000",
             "ftime_utc": "2026-07-21T06:00:00.000", "tmp": None},
            {"station": "KNYC", "runtime_utc": "2026-07-21T00:00:00.000",
             "ftime_utc": "2026-07-21T12:00:00.000", "tmp": 75},
        ]}
    calls, restore = install_fixture_router(router)
    try:
        rows = WeatherSource().forecasts("KNYC")
    finally:
        restore()
    check(len(rows) == 1 and rows[0].value == 75.0,
          f"null-tmp row should be skipped, kept row value 75: {rows}")


def test_forecasts_runtime_selects_cycle():
    """A specific past runtime is passed through to IEM in ISO-Z form (verified
    accepted live 2026-07-20); None omits it (latest cycle)."""
    seen = []

    def router(path, query):
        seen.append(query.get("runtime"))
        return {"data": [{"station": "KNYC", "runtime_utc": "2026-07-20T12:00:00.000",
                          "ftime_utc": "2026-07-20T18:00:00.000", "tmp": 80}]}
    calls, restore = install_fixture_router(router)
    try:
        WeatherSource().forecasts("KNYC")  # latest — no runtime param
        WeatherSource().forecasts("KNYC", runtime=datetime(2026, 7, 20, 12, tzinfo=timezone.utc))
    finally:
        restore()
    check(seen[0] is None, f"latest-cycle call must not send runtime, got {seen[0]!r}")
    check(seen[1] == "2026-07-20T12:00:00Z",
          f"explicit runtime must be sent ISO-Z, got {seen[1]!r}")


def test_forecasts_naive_runtime_raises():
    calls, restore = install_fixture_router(default_router)
    try:
        try:
            WeatherSource().forecasts("KNYC", runtime=datetime(2026, 7, 20, 12))
            raise AssertionError("naive runtime should raise ValueError")
        except ValueError:
            pass
    finally:
        restore()


def test_load_forecasts_backfills_each_runtime():
    """load_forecasts with a list of runtimes pulls each cycle and upserts them
    all — the forecast-history backfill path."""
    def router(path, query):
        rt = query.get("runtime")  # ISO-Z; embed its hour into a distinct issued time
        hour = rt[11:13] if rt else "00"
        return {"data": [{"station": "KNYC",
                          "runtime_utc": f"2026-07-20T{hour}:00:00.000",
                          "ftime_utc": f"2026-07-20T{int(hour)+3:02d}:00:00.000",
                          "tmp": 70}]}
    calls, restore = install_fixture_router(router)
    upserted = []
    orig = store.upsert_forecasts
    store.upsert_forecasts = lambda conn, rows: upserted.extend(rows)
    try:
        rts = [datetime(2026, 7, 20, h, tzinfo=timezone.utc) for h in (6, 12, 18)]
        n = weather_ingest.load_forecasts(None, WeatherSource(), "KNYC", runtimes=rts)
    finally:
        restore()
        store.upsert_forecasts = orig
    check(n == 3, f"expected 3 rows (one per cycle), got {n}")
    issued_hours = sorted({r.issued_at.hour for r in upserted})
    check(issued_hours == [6, 12, 18],
          f"each requested cycle should be fetched and stored, got {issued_hours}")


def test_forecasts_model_namespaces_source():
    calls, restore = install_fixture_router(default_router)
    try:
        rows = WeatherSource().forecasts("KNYC", model="GFS")
    finally:
        restore()
    check(all(r.source == "iem-mos-gfs" for r in rows),
          f"source must reflect the model (iem-mos-gfs): {[r.source for r in rows][:1]}")
    check(("/mos.json", {"station": "KNYC", "model": "GFS"}) in calls,
          f"MOS request must pass station=ICAO and model: {calls}")


# ---------------------------------------------------------------------------
# forecasts — malformed responses must fail loud as WeatherAPIError
# ---------------------------------------------------------------------------
def test_forecasts_issued_not_before_valid_raises():
    """The PIT invariant is enforced, not assumed: a response where
    runtime_utc >= ftime_utc must fail loud rather than store a lookahead row."""
    def router(path, query):
        return {"data": [{"station": "KNYC",
                          "runtime_utc": "2026-07-21T12:00:00.000",
                          "ftime_utc": "2026-07-21T06:00:00.000", "tmp": 70}]}
    calls, restore = install_fixture_router(router)
    try:
        try:
            WeatherSource().forecasts("KNYC")
            raise AssertionError("issued_at >= valid_at should raise WeatherAPIError")
        except WeatherAPIError as e:
            check("point-in-time" in str(e) or "not before" in str(e),
                  f"error should explain the PIT violation: {e}")
    finally:
        restore()


def test_forecasts_out_of_range_temp_raises():
    def router(path, query):
        return {"data": [{"station": "KNYC", "runtime_utc": "2026-07-21T00:00:00.000",
                          "ftime_utc": "2026-07-21T06:00:00.000", "tmp": 999}]}
    calls, restore = install_fixture_router(router)
    try:
        try:
            WeatherSource().forecasts("KNYC")
            raise AssertionError("out-of-range temp should raise WeatherAPIError")
        except WeatherAPIError as e:
            check("999" in str(e) and "KNYC" in str(e),
                  f"error should name the bad value and station: {e}")
    finally:
        restore()


def test_forecasts_missing_key_raises():
    def router(path, query):
        return {"data": [{"station": "KNYC", "tmp": 70}]}  # no runtime_utc/ftime_utc
    calls, restore = install_fixture_router(router)
    try:
        try:
            WeatherSource().forecasts("KNYC")
            raise AssertionError("missing timestamp key should raise WeatherAPIError")
        except WeatherAPIError as e:
            check("KNYC" in str(e), f"error should name the station: {e}")
    finally:
        restore()


def test_non_object_body_raises():
    for body in (None, [1, 2, 3], "nope"):
        def router(path, query, body=body):
            return body
        calls, restore = install_fixture_router(router)
        try:
            try:
                WeatherSource(max_retries=2).forecasts("KNYC")
                raise AssertionError(f"top-level {body!r} should raise WeatherAPIError")
            except WeatherAPIError as e:
                check("JSON object" in str(e), f"error should describe the shape problem: {e}")
        finally:
            restore()


# ---------------------------------------------------------------------------
# observations — daily max/min, DST-correct observed_at, window filtering
# ---------------------------------------------------------------------------
def test_observations_parse_tmax_tmin_and_observed_at():
    calls, restore = install_fixture_router(default_router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2026, 6, 1), end=date(2026, 6, 2))
    finally:
        restore()

    # 2 days x (tmax, tmin) = 4 rows
    check(len(rows) == 4, f"expected 4 rows (2 days x tmax/tmin), got {len(rows)}")
    by = {(r.variable, r.observed_at.date().isoformat()): r for r in rows}
    tmax_d1 = by[("tmax", "2026-06-02")]  # observed_at = next local midnight in UTC
    check(tmax_d1.value == 71.0, f"tmax 2026-06-01 should be 71.0: {tmax_d1.value}")
    check(tmax_d1.station == "KNYC" and tmax_d1.source == "iem-asos",
          f"station/source wrong: {tmax_d1}")
    # NYC is EDT (UTC-4) on 2026-06-01, so end-of-day -> 2026-06-02 00:00 EDT = 04:00Z
    check(tmax_d1.observed_at == datetime(2026, 6, 2, 4, 0, tzinfo=timezone.utc),
          f"observed_at must be the end-of-local-day instant in UTC (DST-correct): "
          f"{tmax_d1.observed_at}")
    check(("tmin", "2026-06-02") in by and by[("tmin", "2026-06-02")].value == 53.0,
          f"tmin 2026-06-01 should be 53.0: {by.get(('tmin', '2026-06-02'))}")


def test_observations_window_filters_rows():
    """The fixture holds 2026-06-01..06; a narrower window returns only its days."""
    calls, restore = install_fixture_router(default_router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2026, 6, 3), end=date(2026, 6, 4))
    finally:
        restore()
    days = sorted({(r.observed_at.date()) for r in rows})
    # observed_at is next-local-midnight, so 06-03 -> 06-04, 06-04 -> 06-05
    check(len(rows) == 4, f"expected 4 rows for the 2-day window, got {len(rows)}")
    check(str(days[0]) == "2026-06-04" and str(days[-1]) == "2026-06-05",
          f"window filtering wrong: {days}")


def test_observations_skip_null_extreme():
    def router(path, query):
        return {"data": [
            {"station": "NYC", "date": "2026-06-01", "max_tmpf": 71.0, "min_tmpf": None},
        ]}
    calls, restore = install_fixture_router(router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2026, 6, 1), end=date(2026, 6, 1))
    finally:
        restore()
    check(len(rows) == 1 and rows[0].variable == "tmax",
          f"null min_tmpf should be skipped, only tmax kept: {rows}")


def test_observations_multi_month_queries_each_month():
    seen_months = []

    def router(path, query):
        seen_months.append((query.get("year"), query.get("month")))
        return {"data": []}
    calls, restore = install_fixture_router(router)
    try:
        WeatherSource().observations("KNYC", start=date(2026, 5, 28), end=date(2026, 7, 2))
    finally:
        restore()
    check(seen_months == [("2026", "5"), ("2026", "6"), ("2026", "7")],
          f"should query each month in the window once: {seen_months}")


def test_observations_bad_window_raises():
    try:
        WeatherSource().observations("KNYC", start=date(2026, 6, 5), end=date(2026, 6, 1))
        raise AssertionError("end < start should raise ValueError")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# graceful degradation — API/rate-limit failure -> clear, catchable error
# ---------------------------------------------------------------------------
def test_graceful_degradation_on_repeated_5xx():
    def failing_router(path, query):
        raise urllib.error.HTTPError("http://fake", 500, "Internal Server Error", {}, None)
    calls, restore = install_fixture_router(failing_router)
    try:
        try:
            WeatherSource(max_retries=2, backoff=0.01).forecasts("KNYC")
            raise AssertionError("repeated 5xx should raise WeatherAPIError")
        except WeatherAPIError as e:
            check("500" in str(e) or "unreachable" in str(e).lower(),
                  f"error should be clear about the failure: {e}")
    finally:
        restore()
    check(len(calls) == 2, f"expected exactly max_retries=2 attempts, got {len(calls)}")


def test_graceful_degradation_on_429():
    attempts = {"n": 0}

    def rate_limited(path, query):
        attempts["n"] += 1
        raise urllib.error.HTTPError("http://fake", 429, "Too Many Requests", {}, None)
    calls, restore = install_fixture_router(rate_limited)
    try:
        try:
            WeatherSource(max_retries=2, backoff=0.01).forecasts("KNYC")
            raise AssertionError("repeated 429 should raise WeatherAPIError")
        except WeatherAPIError:
            pass
    finally:
        restore()
    check(attempts["n"] == 2, f"429 should be retried, got {attempts['n']} attempt(s)")


# ---------------------------------------------------------------------------
# precipitation (MRAIN-1 / ADR-0028) — the variable Kalshi's monthly rain
# markets resolve against. Fixture daily_nyc_2025_12.json is a full real month
# captured live 2026-08-01, deliberately NOT trimmed to a few rows: its monthly
# SUM is the quantity ADR-0028 verified against Kalshi's own settlement, so the
# whole month is the ground truth being frozen.
# ---------------------------------------------------------------------------
def precip_router(path, query):
    if path == "/daily.json":
        return _load("daily_nyc_2025_12.json")
    raise AssertionError(f"unmocked IEM path in precip router: {path}")


def test_observations_parse_precip():
    calls, restore = install_fixture_router(precip_router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2025, 12, 1),
                                            end=date(2025, 12, 1))
    finally:
        restore()
    by_var = {r.variable: r for r in rows}
    check("precip" in by_var, f"a precip row must be emitted: {sorted(by_var)}")
    p = by_var["precip"]
    check(p.value == 0.0, f"2025-12-01 precip should be 0.0: {p.value}")
    check(p.station == "KNYC" and p.source == "iem-asos",
          f"precip row station/source wrong: {p}")
    # precip shares the observation PIT convention: observed_at = next local midnight
    check(p.observed_at == datetime(2025, 12, 2, 5, 0, tzinfo=timezone.utc),
          f"precip observed_at must be end-of-local-day UTC (EST, UTC-5): "
          f"{p.observed_at}")


def test_precip_monthly_sum_matches_kalshi_settlement():
    """The load-bearing regression on ADR-0028's central finding: summing the
    stored daily precip rows for Dec 2025 at KNYC must land inside (3, 4] —
    the bracket Kalshi's own KXRAINNYCM-25DEC ladder settled to (>1,>2,>3 YES;
    >4 NO). If a future change rounds traces, drops estimated days, or converts
    units, this test fails and the study's ground truth is known to have moved."""
    calls, restore = install_fixture_router(precip_router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2025, 12, 1),
                                            end=date(2025, 12, 31))
    finally:
        restore()
    precip_rows = [r for r in rows if r.variable == "precip"]
    check(len(precip_rows) == 31, f"expected 31 daily precip rows: {len(precip_rows)}")
    total = sum(r.value for r in precip_rows)
    check(3.0 < total <= 4.0,
          f"Dec 2025 KNYC precip total {total:.4f} must fall in Kalshi's settled "
          f"bracket (3, 4] — see ADR-0028")
    check(abs(total - 3.3802) < 1e-9,
          f"exact captured total changed: {total!r} (expected 3.3802)")


def test_precip_trace_values_preserved_not_rounded():
    """IEM encodes a trace (measurable but <0.01in) as 0.0001. Storing it as-is
    is what reproduces Kalshi's settlement; rounding to 0 would make the data
    disagree with the venue. Two such days exist in the real Dec-2025 fixture."""
    calls, restore = install_fixture_router(precip_router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2025, 12, 1),
                                            end=date(2025, 12, 31))
    finally:
        restore()
    traces = [r for r in rows if r.variable == "precip" and r.value == 0.0001]
    check(len(traces) == 2,
          f"the real fixture carries 2 trace days; got {len(traces)} — traces "
          f"must not be rounded away")


def test_observations_skip_null_precip():
    def router(path, query):
        return {"data": [
            {"station": "NYC", "date": "2026-06-01", "max_tmpf": 71.0,
             "min_tmpf": 53.0, "precip": None},
        ]}
    calls, restore = install_fixture_router(router)
    try:
        rows = WeatherSource().observations("KNYC", start=date(2026, 6, 1),
                                            end=date(2026, 6, 1))
    finally:
        restore()
    check({r.variable for r in rows} == {"tmax", "tmin"},
          f"null precip must be skipped, temps kept: {[r.variable for r in rows]}")


def test_precip_out_of_range_raises():
    """Negative precip is physically impossible and would silently shrink a
    monthly sum (pushing a market's true bracket down); an absurd positive is
    the signature of a unit-confusion bug. Both must fail loud, not store."""
    for bad in (-0.5, 1000.0):
        def router(path, query, _bad=bad):
            return {"data": [{"station": "NYC", "date": "2026-06-01", "precip": _bad}]}
        calls, restore = install_fixture_router(router)
        try:
            WeatherSource().observations("KNYC", start=date(2026, 6, 1),
                                         end=date(2026, 6, 1))
            raise AssertionError(f"precip={bad} should raise WeatherAPIError")
        except WeatherAPIError as e:
            check("precip" in str(e), f"error should name the field: {e}")
        finally:
            restore()


def test_precip_bounds_do_not_reuse_temperature_bounds():
    """A guard against the tempting refactor of sharing one validator: -20 is a
    perfectly ordinary tmpf and an impossible precip. If precip ever starts
    using the temperature range, this passes silently in production and
    corrupts every monthly sum — so pin it here."""
    def router(path, query):
        return {"data": [{"station": "NYC", "date": "2026-06-01", "precip": -20.0}]}
    calls, restore = install_fixture_router(router)
    try:
        WeatherSource().observations("KNYC", start=date(2026, 6, 1),
                                     end=date(2026, 6, 1))
        raise AssertionError("precip=-20.0 must be rejected (it is a valid tmpf)")
    except WeatherAPIError:
        pass
    finally:
        restore()


# ---------------------------------------------------------------------------
# station registry + series mapping for MRAIN-1 (ADR-0028)
# ---------------------------------------------------------------------------
def test_rain_series_station_mapping():
    """Every KXRAIN*M series in SERIES_STATION resolves to a registered station.
    The specific city-airport choices are the part that silently corrupts a
    study if wrong (a city can have two ASOS sites), so the CLI-code-derived
    ones are pinned explicitly — all validated in ADR-0028 against 20 real
    settled Kalshi months."""
    rain = {s: st for s, st in SERIES_STATION.items() if s.startswith("KXRAIN")}
    check(len(rain) == 10, f"expected 10 mapped rain series, got {len(rain)}: {sorted(rain)}")
    for series, icao in rain.items():
        check(icao in STATIONS, f"{series} maps to unregistered station {icao!r}")
        check(resolve_station(series).icao == icao,
              f"resolve_station({series!r}) should reach {icao!r}")
    # the ambiguous-airport cases, pinned by CLI code cited in Kalshi's rules
    check(rain["KXRAINCHIM"] == "KMDW", "Chicago rain resolves at Midway (CLIMDW), not O'Hare")
    check(rain["KXRAINHOUM"] == "KHOU", "Houston rain resolves at Hobby (CLIHOU), not KIAH")
    check(rain["KXRAINDALM"] == "KDFW", "Dallas rain resolves at DFW (CLIDFW), not Love Field")
    # KXRAINSTPM has zero resolved history (ADR-0024) — mapping it would imply
    # a study population that does not exist
    check("KXRAINSTPM" not in SERIES_STATION,
          "KXRAINSTPM has no resolved history and must not be mapped")


def test_new_rain_stations_have_sane_timezones():
    """A wrong tz shifts observed_at by hours, which moves a day across the
    month boundary and changes which month's total a day lands in."""
    expected = {"KSEA": "America/Los_Angeles", "KHOU": "America/Chicago",
                "KSFO": "America/Los_Angeles", "KDFW": "America/Chicago"}
    for icao, tz in expected.items():
        check(icao in STATIONS, f"{icao} missing from STATIONS")
        check(STATIONS[icao].tz == tz,
              f"{icao} tz should be {tz}, got {STATIONS[icao].tz}")


# ---------------------------------------------------------------------------
# load_* orchestrators — fetch + upsert wiring, idempotent re-run
# ---------------------------------------------------------------------------
def test_load_forecasts_and_observations_upsert():
    """load_forecasts/load_observations fetch via the source and upsert via store;
    a second identical run writes the same rows again (store's ON CONFLICT makes
    that idempotent at the DB layer — here we assert the row SET is identical across
    runs, the property the DB upsert relies on)."""
    calls, restore = install_fixture_router(default_router)

    fc_batches, obs_batches = [], []
    orig_fc, orig_obs = store.upsert_forecasts, store.upsert_observations
    store.upsert_forecasts = lambda conn, rows: fc_batches.append(list(rows))
    store.upsert_observations = lambda conn, rows: obs_batches.append(list(rows))
    try:
        src = WeatherSource()
        n_fc1 = weather_ingest.load_forecasts(None, src, "KNYC")
        n_obs1 = weather_ingest.load_observations(None, src, "KNYC",
                                                  start=date(2026, 6, 1), end=date(2026, 6, 2))
        n_fc2 = weather_ingest.load_forecasts(None, src, "KNYC")
        n_obs2 = weather_ingest.load_observations(None, src, "KNYC",
                                                  start=date(2026, 6, 1), end=date(2026, 6, 2))
    finally:
        restore()
        store.upsert_forecasts, store.upsert_observations = orig_fc, orig_obs

    check(n_fc1 == n_fc2 == 6, f"forecast count should be stable at 6: {n_fc1}/{n_fc2}")
    check(n_obs1 == n_obs2 == 4, f"observation count should be stable at 4: {n_obs1}/{n_obs2}")
    # idempotency property the DB upsert keys on: re-run produces an identical row set
    check(fc_batches[0] == fc_batches[1],
          "a re-run must produce an identical forecast row set (upsert idempotency)")
    check(obs_batches[0] == obs_batches[1],
          "a re-run must produce an identical observation row set (upsert idempotency)")


# ---------------------------------------------------------------------------
# CLI entry point — graceful non-zero exit, no bare traceback
# ---------------------------------------------------------------------------
def test_cli_returns_nonzero_on_api_failure():
    class _DummyConn:
        def execute(self, *a, **kw):
            return None

        def close(self):
            pass

    class _FailingSource:
        def __init__(self, *a, **kw):
            pass

        def forecasts(self, *a, **kw):
            raise WeatherAPIError("simulated rate-limit exhaustion")

        def observations(self, *a, **kw):
            raise WeatherAPIError("simulated rate-limit exhaustion")

    orig_connect = store.connect
    orig_source = run_weather_ingest.WeatherSource
    store.connect = lambda: _DummyConn()
    run_weather_ingest.WeatherSource = _FailingSource
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            rc = run_weather_ingest.main(["--station", "KNYC", "--days", "3"])
    finally:
        store.connect = orig_connect
        run_weather_ingest.WeatherSource = orig_source
    check(rc == 1, f"main() should return 1 on WeatherAPIError, got {rc}")
    check("IEM API failure" in captured.getvalue(),
          f"stderr should carry a clear failure message: {captured.getvalue()!r}")


def test_cli_returns_nonzero_on_unexpected_error():
    class _DummyConn:
        def execute(self, *a, **kw):
            return None

        def close(self):
            pass

    def _boom(*a, **kw):
        raise RuntimeError("simulated store failure / untested field")

    orig_connect = store.connect
    orig_run = run_weather_ingest.run
    store.connect = lambda: _DummyConn()
    run_weather_ingest.run = _boom
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            rc = run_weather_ingest.main(["--station", "KNYC", "--days", "3"])
    finally:
        store.connect = orig_connect
        run_weather_ingest.run = orig_run
    check(rc == 1, f"main() should return 1 on an unexpected exception, got {rc}")
    txt = captured.getvalue()
    check("unexpected" in txt and "RuntimeError" in txt and "Traceback" in txt,
          f"stderr should name it unexpected, name the type, and keep the traceback: {txt!r}")


def test_run_backfills_daily_cycles_over_window():
    """run() pulls one MOS cycle per day across the window (forecast history), and
    skips cycles in the future (no data). Uses a fixture-backed source + fake
    store, no DB."""
    requested_runtimes = []

    def router(path, query):
        if path == "/mos.json":
            requested_runtimes.append(query.get("runtime"))
            rt = query.get("runtime") or "2026-06-01T12:00:00Z"
            return {"data": [{"station": "KNYC", "runtime_utc": rt.replace("Z", ".000"),
                              "ftime_utc": rt.replace("12:00:00Z", "18:00:00.000"),
                              "tmp": 70}]}
        if path == "/daily.json":
            return {"data": []}
        raise AssertionError(path)

    calls, restore = install_fixture_router(router)
    orig_fc, orig_obs = store.upsert_forecasts, store.upsert_observations
    store.upsert_forecasts = lambda conn, rows: None
    store.upsert_observations = lambda conn, rows: None
    try:
        # a 3-day past window -> 3 daily cycles
        n_fc, n_obs = run_weather_ingest.run(
            WeatherSource(), None, stations=["KNYC"], model="NBS",
            start=date(2026, 6, 1), end=date(2026, 6, 3), cycle_hour=12)
    finally:
        restore()
        store.upsert_forecasts, store.upsert_observations = orig_fc, orig_obs
    check(len(requested_runtimes) == 3,
          f"expected one MOS cycle per day (3), got {requested_runtimes}")
    check(all(rt and rt.endswith("T12:00:00Z") for rt in requested_runtimes),
          f"each cycle must be a 12Z runtime, got {requested_runtimes}")
    check(n_fc == 3, f"expected 3 forecast rows (one per cycle), got {n_fc}")


def test_run_observations_only_skips_forecast_calls():
    """--observations-only (ADR-0028) must make ZERO MOS calls. This is not
    cosmetic: MRAIN-1's benchmark is climatological and reads no forecast, so a
    multi-year ten-station backfill would otherwise issue thousands of API
    calls whose results nothing consumes."""
    paths = []

    def router(path, query):
        paths.append(path)
        if path == "/daily.json":
            return {"data": [{"station": "NYC", "date": "2026-06-01", "precip": 0.5}]}
        raise AssertionError(f"unexpected call to {path} under --observations-only")

    calls, restore = install_fixture_router(router)
    orig_fc, orig_obs = store.upsert_forecasts, store.upsert_observations
    store.upsert_forecasts = lambda conn, rows: None
    store.upsert_observations = lambda conn, rows: None
    try:
        n_fc, n_obs = run_weather_ingest.run(
            WeatherSource(), None, stations=["KNYC"], model="NBS",
            start=date(2026, 6, 1), end=date(2026, 6, 3), cycle_hour=12,
            observations_only=True)
    finally:
        restore()
        store.upsert_forecasts, store.upsert_observations = orig_fc, orig_obs
    check("/mos.json" not in paths, f"no MOS call may be made: {paths}")
    check(n_fc == 0, f"forecast count must be 0, got {n_fc}")
    check(n_obs == 1, f"observations must still be ingested, got {n_obs}")


def test_cli_bad_date_window_returns_nonzero():
    orig_connect = store.connect
    store.connect = lambda: (_ for _ in ()).throw(AssertionError("should not connect"))
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            rc = run_weather_ingest.main(["--station", "KNYC", "--start", "not-a-date",
                                          "--end", "2026-06-30"])
    finally:
        store.connect = orig_connect
    check(rc == 1, f"a malformed --start should return 1 before connecting, got {rc}")


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_resolve_station_icao_series_and_unknown,
        test_forecasts_parse_and_pit_keys,
        test_forecasts_skip_null_tmp,
        test_forecasts_runtime_selects_cycle,
        test_forecasts_naive_runtime_raises,
        test_load_forecasts_backfills_each_runtime,
        test_forecasts_model_namespaces_source,
        test_forecasts_issued_not_before_valid_raises,
        test_forecasts_out_of_range_temp_raises,
        test_forecasts_missing_key_raises,
        test_non_object_body_raises,
        test_observations_parse_tmax_tmin_and_observed_at,
        test_observations_window_filters_rows,
        test_observations_skip_null_extreme,
        test_observations_multi_month_queries_each_month,
        test_observations_bad_window_raises,
        test_observations_parse_precip,
        test_precip_monthly_sum_matches_kalshi_settlement,
        test_precip_trace_values_preserved_not_rounded,
        test_observations_skip_null_precip,
        test_precip_out_of_range_raises,
        test_precip_bounds_do_not_reuse_temperature_bounds,
        test_rain_series_station_mapping,
        test_new_rain_stations_have_sane_timezones,
        test_run_observations_only_skips_forecast_calls,
        test_graceful_degradation_on_repeated_5xx,
        test_graceful_degradation_on_429,
        test_load_forecasts_and_observations_upsert,
        test_cli_returns_nonzero_on_api_failure,
        test_cli_returns_nonzero_on_unexpected_error,
        test_run_backfills_daily_cycles_over_window,
        test_cli_bad_date_window_returns_nonzero,
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
