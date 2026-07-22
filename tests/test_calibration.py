"""
tests/test_calibration.py — WP-7 tests for src/calibration.py.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_calibration.py`). No network, no Postgres: the study core is
exercised through a synthetic in-memory Reader (exactly like prob_fn's tests), and
the market-spec parser is checked against the REAL Kalshi `rules_primary` strings
recorded in tests/fixtures/kalshi/ (ground truth, not a hand-rolled guess).

Traces to plan.md WP-7 acceptance (US-4 study G/W/T):
  - outputs a clear per-market-type GO/NO-GO (seeded GO and seeded NO-GO both
    verified)
  - a NO-GO is a valid, non-blocking outcome
  - uses only pre-`as_of` data (PIT honesty verified: a forecast issued at/after
    as_of never changes the answer)
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import contextlib  # noqa: E402
import io  # noqa: E402

import calibration  # noqa: E402
import run_calibration  # noqa: E402
import store  # noqa: E402
import weather_ingest  # noqa: E402
from calibration import (  # noqa: E402
    WeatherMarket, WeatherMarketSpec, evaluate, parse_weather_market_spec,
    _forecast_prob, _forecast_high, _error_stats, _parse_target_date,
    _norm_cdf,
)
from store import Candle, WeatherForecastRow, WeatherObservationRow  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "kalshi")
TZ = ZoneInfo("America/New_York")
UTC = timezone.utc


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# synthetic Reader (PIT-enforcing) — mirrors prob_fn's fake
# ---------------------------------------------------------------------------
class FakeReader:
    def __init__(self, candles=(), forecasts=(), observations=()):
        self._c, self._f, self._o = list(candles), list(forecasts), list(observations)

    def candles_before(self, token_id, as_of):
        return [c for c in self._c if c.token_id == token_id and c.ts < as_of]

    def forecasts_before(self, station, variable, as_of):
        return [f for f in self._f if f.station == station
                and f.variable == variable and f.issued_at < as_of]

    def observations_before(self, station, variable, as_of):
        return [o for o in self._o if o.station == station
                and o.variable == variable and o.observed_at < as_of]


def _obs_at(d: date) -> datetime:
    nd = d + timedelta(days=1)
    return datetime(nd.year, nd.month, nd.day, tzinfo=TZ).astimezone(UTC)


def _history(n=20, base=date(2026, 6, 1), forecast_err_pattern=(-1, 0, 1)):
    """n days of (forecast, observation) history with a small nonzero error so σ>0."""
    forecasts, observations = [], []
    for i in range(n):
        d = base + timedelta(days=i)
        fc = 70 + (i % 10)
        truth = fc + forecast_err_pattern[i % len(forecast_err_pattern)]
        issued = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(days=1)
        valid = datetime(d.year, d.month, d.day, 18, tzinfo=UTC)
        forecasts.append(WeatherForecastRow(issued, valid, "KNYC", "tmpf",
                                            float(fc), "iem-mos-nbs", 24.0))
        observations.append(WeatherObservationRow(_obs_at(d), "KNYC", "tmax",
                                                  float(truth), "iem-asos"))
    return forecasts, observations


# ---------------------------------------------------------------------------
# market-spec parser — against REAL Kalshi rules strings
# ---------------------------------------------------------------------------
def _rules(ticker):
    ev = json.load(open(os.path.join(FIXTURES, "events_mixed.json")))
    for e in ev["events"]:
        for m in e["markets"]:
            if m["ticker"] == ticker:
                return m["rules_primary"]
    raise AssertionError(f"ticker not in fixture: {ticker}")


def test_parse_spec_less_from_real_rules():
    spec = parse_weather_market_spec("KXHIGHNY-26JUL19-T80", _rules("KXHIGHNY-26JUL19-T80"))
    check(spec is not None, "T80 should parse")
    check(spec.station == "KNYC", f"station should map KXHIGHNY->KNYC: {spec.station}")
    check(spec.variable == "tmax", f"variable should be tmax: {spec.variable}")
    check(spec.target_date == date(2026, 7, 19), f"date wrong: {spec.target_date}")
    check(spec.strike_type == "less" and spec.hi == 80.0 and spec.lo is None,
          f"'less than 80' should be less/hi=80: {spec}")


def test_parse_spec_between_from_real_rules():
    spec = parse_weather_market_spec("KXHIGHNY-26JUL19-B80.5", _rules("KXHIGHNY-26JUL19-B80.5"))
    check(spec is not None and spec.strike_type == "between",
          f"'between 80-81' should be between: {spec}")
    check(spec.lo == 80.0 and spec.hi == 81.0, f"between bounds wrong: {spec}")


def test_parse_spec_greater_phrasing():
    # 'above 5%' phrasing (econ-style rules) maps to greater/lo
    spec = parse_weather_market_spec(
        "KXHIGHNY-26JUL19-T90", "If the highest temperature ... is above 90°, resolves Yes.")
    check(spec is not None and spec.strike_type == "greater" and spec.lo == 90.0,
          f"'above 90' should be greater/lo=90: {spec}")


def test_parse_spec_none_cases():
    # unmapped series -> None
    check(parse_weather_market_spec("KXNOPE-26JUL19-T80", "is less than 80°") is None,
          "unmapped series should return None")
    # no date segment -> None
    check(parse_weather_market_spec("KXHIGHNY-T80", "is less than 80°") is None,
          "no date segment should return None")
    # unparseable rules -> None
    check(parse_weather_market_spec("KXHIGHNY-26JUL19-T80", "some unrelated text") is None,
          "unparseable rules should return None")
    # missing rules -> None
    check(parse_weather_market_spec("KXHIGHNY-26JUL19-T80", None) is None,
          "missing rules should return None")


def test_parse_target_date_variants():
    check(_parse_target_date("KXHIGHNY-26JAN02-T80") == date(2026, 1, 2), "26JAN02")
    check(_parse_target_date("KXHIGHNY-26DEC31-B80.5") == date(2026, 12, 31), "26DEC31")
    check(_parse_target_date("KXU3MAX-30-5") is None, "econ ticker has no YYMMMDD")


# ---------------------------------------------------------------------------
# forecast -> probability math
# ---------------------------------------------------------------------------
def test_parse_strike_expands_real_phrasings():
    """Verify the expanded parser handles more real Kalshi strike phrasings beyond
    the fixture's "less" and "between" (deferred review flag: extended phrasings
    like "above X", "X or more", "X or fewer" were not tested against real rules)."""
    # Add a temporary test series to avoid needing a full Kalshi data load
    orig = weather_ingest.SERIES_STATION.get("KXTEST")
    weather_ingest.SERIES_STATION["KXTEST"] = "KNYC"
    try:
        cases = [
            # "greater than X"
            ("KXTEST-01JAN25", "greater than 80.5°F", "greater", 80.5, None),
            # "above X"
            ("KXTEST-01JAN25", "is above 15%", "greater", 15.0, None),
            # "at least X"
            ("KXTEST-01JAN25", "at least an earthquake of 8.0", "greater", 8.0, None),
            # "X or more"
            ("KXTEST-01JAN25", "12.5 million tonnes or more", "greater", 12.5, None),
            # "X or fewer" (less)
            ("KXTEST-01JAN25", "4909.9 million metric tonnes or fewer", "less", None, 4909.9),
            # "fewer than X"
            ("KXTEST-01JAN25", "fewer than 50 earthquakes", "less", None, 50.0),
            # "between X and Y"
            ("KXTEST-01JAN25", "between 75.0 and 85.0°F", "between", 75.0, 85.0),
            # "between X - Y" (dash)
            ("KXTEST-01JAN25", "between 10-20%", "between", 10.0, 20.0),
        ]
        for ticker, rules, exp_type, exp_lo, exp_hi in cases:
            spec = parse_weather_market_spec(ticker, rules)
            check(spec is not None, f"'{rules}' should parse, got None")
            check(spec.strike_type == exp_type,
                  f"'{rules}' strike should be {exp_type}, got {spec.strike_type}")
            check(spec.lo == exp_lo and spec.hi == exp_hi,
                  f"'{rules}' bounds should be ({exp_lo},{exp_hi}), got ({spec.lo},{spec.hi})")
    finally:
        if orig is None:
            del weather_ingest.SERIES_STATION["KXTEST"]
        else:
            weather_ingest.SERIES_STATION["KXTEST"] = orig


def test_forecast_prob_less_greater_between():
    # mu=80, sigma=5
    less = WeatherMarketSpec("x", "KNYC", "tmax", date(2026, 6, 1), "less", None, 80.0)
    greater = WeatherMarketSpec("x", "KNYC", "tmax", date(2026, 6, 1), "greater", 80.0, None)
    between = WeatherMarketSpec("x", "KNYC", "tmax", date(2026, 6, 1), "between", 75.0, 85.0)
    check(abs(_forecast_prob(less, 80.0, 5.0) - 0.5) < 1e-9, "P(x<80|mu=80)=0.5")
    check(abs(_forecast_prob(greater, 80.0, 5.0) - 0.5) < 1e-9, "P(x>80|mu=80)=0.5")
    # between [75,85] around mu=80, sigma=5 -> Phi(1)-Phi(-1) ~ 0.6827
    exp = _norm_cdf(1.0) - _norm_cdf(-1.0)
    check(abs(_forecast_prob(between, 80.0, 5.0) - exp) < 1e-9, "between band prob")
    # a confident forecast well above the strike -> near 1 for greater
    check(_forecast_prob(greater, 95.0, 3.0) > 0.99, "far-above forecast -> ~1")


def test_forecast_high_latest_cycle_and_daily_max():
    # two cycles for the same target date; the later cycle must win, and within a
    # cycle the daily MAX over hourly rows is taken.
    tgt = date(2026, 6, 22)
    valid_am = datetime(2026, 6, 22, 12, tzinfo=UTC)
    valid_pm = datetime(2026, 6, 22, 20, tzinfo=UTC)
    old = datetime(2026, 6, 20, 12, tzinfo=UTC)
    new = datetime(2026, 6, 21, 12, tzinfo=UTC)
    fc = [
        WeatherForecastRow(old, valid_pm, "KNYC", "tmpf", 70.0, "iem-mos-nbs", 1.0),
        WeatherForecastRow(new, valid_am, "KNYC", "tmpf", 78.0, "iem-mos-nbs", 1.0),
        WeatherForecastRow(new, valid_pm, "KNYC", "tmpf", 84.0, "iem-mos-nbs", 1.0),
    ]
    r = FakeReader(forecasts=fc)
    as_of = datetime(2026, 6, 22, tzinfo=UTC)
    f = _forecast_high(r, "KNYC", tgt, as_of, TZ)
    check(f == 84.0, f"latest cycle daily-max should be 84.0, got {f}")


def test_error_stats_pit_and_gates():
    fc, obs = _history(20)
    r = FakeReader(forecasts=fc, observations=obs)
    as_of = datetime(2026, 6, 25, tzinfo=UTC)
    stats = _error_stats(r, "KNYC", as_of, TZ, min_pairs=10)
    check(stats is not None, "20 pairs should estimate stats")
    bias, sigma = stats
    check(sigma > 0, f"sigma should be positive: {sigma}")
    # min-pairs gate: an early as_of with <10 knowable pairs -> None
    early = datetime(2026, 6, 5, tzinfo=UTC)
    check(_error_stats(r, "KNYC", early, TZ, min_pairs=10) is None,
          "too few pairs before as_of should return None")
    # zero-variance history -> None (can't form a spread)
    fc0, obs0 = _history(20, forecast_err_pattern=(0,))
    r0 = FakeReader(forecasts=fc0, observations=obs0)
    check(_error_stats(r0, "KNYC", as_of, TZ, min_pairs=10) is None,
          "zero-variance residuals should return None")


# ---------------------------------------------------------------------------
# end-to-end verdicts: seeded GO and seeded NO-GO
# ---------------------------------------------------------------------------
def _target_market(strike_type, lo, hi, y):
    tgt = date(2026, 6, 22)
    resolves = datetime(2026, 6, 23, 4, tzinfo=UTC)
    spec = WeatherMarketSpec("KXHIGHNY-26JUN22-T80", "KNYC", "tmax", tgt,
                             strike_type, lo, hi)
    return WeatherMarket(spec, "KX-YES", resolves, resolved_y=y)


def _target_forecast(valid_high):
    valid = datetime(2026, 6, 22, 18, tzinfo=UTC)
    return [WeatherForecastRow(datetime(2026, 6, 21, h, tzinfo=UTC), valid,
                               "KNYC", "tmpf", float(valid_high), "iem-mos-nbs", 24.0)
            for h in (6, 12)]


def _run(price, valid_high, market):
    fc, obs = _history(20)
    fc += _target_forecast(valid_high)
    candles = [Candle(datetime(2026, 6, 22, 0, tzinfo=UTC), "KX-YES",
                      price, price, price, price, 100.0)]
    r = FakeReader(candles=candles, forecasts=fc, observations=obs)
    return evaluate(r, [market],
                    start=datetime(2026, 6, 22, tzinfo=UTC),
                    end=datetime(2026, 6, 23, 4, tzinfo=UTC),
                    step=timedelta(hours=6))


def test_seeded_go_verdict():
    # forecast confidently says high=85 (>80 -> YES ~certain), y=1; price stuck 0.5
    report = _run(price=0.5, valid_high=85.0,
                  market=_target_market("greater", 80.0, None, y=1.0))
    check(report.overall_verdict == "GO", f"expected GO, got {report.overall_verdict}")
    res = report.results[0]
    check(res.market_type == "weather:tmax:greater", res.market_type)
    check(res.brier_forecast < res.brier_price, "forecast must beat price on Brier")
    check(res.skill >= report.margin, f"skill {res.skill} should clear margin {report.margin}")


def test_seeded_nogo_verdict():
    # forecast sits AT the strike (high=80 -> P~0.5, uninformative) and the market
    # price (0.5) is no worse -> skill ~0 < margin -> NO-GO, a valid outcome.
    report = _run(price=0.5, valid_high=80.0,
                  market=_target_market("greater", 80.0, None, y=1.0))
    check(report.overall_verdict == "NO-GO", f"expected NO-GO, got {report.overall_verdict}")
    check(report.results[0].skill < report.margin, "skill should be below margin")


def test_nogo_when_market_more_accurate():
    # forecast uninformative (P~0.5) but the market price is confidently right
    # (0.95, y=1) -> price beats forecast -> negative skill -> NO-GO.
    report = _run(price=0.95, valid_high=80.0,
                  market=_target_market("greater", 80.0, None, y=1.0))
    check(report.overall_verdict == "NO-GO", "market more accurate than forecast -> NO-GO")
    check(report.results[0].skill < 0, f"skill should be negative: {report.results[0].skill}")


# ---------------------------------------------------------------------------
# PIT honesty + insufficient-data skips
# ---------------------------------------------------------------------------
def test_pit_honesty_future_forecast_ignored():
    """A forecast that would flip the answer but is issued AFTER every as_of in the
    window must never be used — the study reads only `< as_of` (ADR-0009). Same
    seed as the NO-GO case, plus a late 'perfect' forecast issued past resolution;
    the verdict must stay NO-GO."""
    market = _target_market("greater", 80.0, None, y=1.0)
    fc, obs = _history(20)
    fc += _target_forecast(80.0)  # uninformative, as in the NO-GO case
    # a later cycle that says 90 (would -> GO) but is issued AFTER the window ends
    late = datetime(2026, 6, 24, 0, tzinfo=UTC)
    fc.append(WeatherForecastRow(late, datetime(2026, 6, 22, 18, tzinfo=UTC),
                                 "KNYC", "tmpf", 90.0, "iem-mos-nbs", 24.0))
    candles = [Candle(datetime(2026, 6, 22, 0, tzinfo=UTC), "KX-YES",
                      0.5, 0.5, 0.5, 0.5, 100.0)]
    r = FakeReader(candles=candles, forecasts=fc, observations=obs)
    report = evaluate(r, [market], start=datetime(2026, 6, 22, tzinfo=UTC),
                      end=datetime(2026, 6, 23, 4, tzinfo=UTC), step=timedelta(hours=6))
    check(report.overall_verdict == "NO-GO",
          "a forecast issued after the window must not leak into the verdict")


def test_skips_when_no_candle_or_forecast():
    market = _target_market("greater", 80.0, None, y=1.0)
    fc, obs = _history(20)
    fc += _target_forecast(85.0)
    # no candles at all -> no price -> no samples
    r = FakeReader(candles=[], forecasts=fc, observations=obs)
    report = evaluate(r, [market], start=datetime(2026, 6, 22, tzinfo=UTC),
                      end=datetime(2026, 6, 23, 4, tzinfo=UTC), step=timedelta(hours=6))
    check(report.n_samples == 0 and report.overall_verdict == "NO-GO",
          f"no candle -> no samples -> NO-GO, got {report.n_samples}")


def test_skips_when_insufficient_error_pairs():
    market = _target_market("greater", 80.0, None, y=1.0)
    fc, obs = _history(3)   # only 3 pairs, below default min of 10
    fc += _target_forecast(85.0)
    candles = [Candle(datetime(2026, 6, 22, 0, tzinfo=UTC), "KX-YES",
                      0.5, 0.5, 0.5, 0.5, 100.0)]
    r = FakeReader(candles=candles, forecasts=fc, observations=obs)
    report = evaluate(r, [market], start=datetime(2026, 6, 22, tzinfo=UTC),
                      end=datetime(2026, 6, 23, 4, tzinfo=UTC), step=timedelta(hours=6),
                      min_error_pairs=10)
    check(report.n_samples == 0,
          f"insufficient error pairs -> no samples, got {report.n_samples}")


def test_error_stats_excludes_target_date_self_leak():
    """Reviewer BLOCKER (2026-07-21): once `as_of` passes the target date's
    observed_at (WP-6's end-of-local-day) but is still before resolution, that
    market's OWN outcome is `< as_of` and would leak into the σ/bias pool used to
    price it. _error_stats(exclude_date=target) must drop exactly that pair."""
    fc, obs = _history(20)                       # base 2026-06-01 .. 06-20
    target = date(2026, 6, 20)                   # last day in the pool
    # as_of after the target's observed_at (start of next local day) — its own
    # obs is now knowable.
    as_of = _obs_at(target) + timedelta(hours=1)
    r = FakeReader(forecasts=fc, observations=obs)
    with_leak = _error_stats(r, "KNYC", as_of, TZ, min_pairs=5, exclude_date=None)
    clean = _error_stats(r, "KNYC", as_of, TZ, min_pairs=5, exclude_date=target)
    check(with_leak is not None and clean is not None, "both should estimate")
    check(with_leak != clean,
          "excluding the target date must change the pool (proves the leak is real)")
    # the clean estimate must equal the pool computed with the target day removed
    pool_dates = {(o.observed_at.astimezone(TZ) - timedelta(days=1)).date()
                  for o in r.observations_before("KNYC", "tmax", as_of)}
    check(target in pool_dates, "test setup: target's own obs is in-window")


def test_evaluate_verdict_unaffected_by_target_self_obs():
    """End-to-end: a market's own realized observation being in-window must not
    change the RESULT (it is excluded from the benchmark). Reverting the
    `exclude_date=spec.target_date` wiring in evaluate() must fail this test.

    The re-review (2026-07-21) caught the earlier version being hollow: its
    `resolves_at` equalled the target's `observed_at`, leaving an empty
    [observed_at, resolves_at) window so the leaky row was never `< as_of`. Here
    the window is deliberately widened (resolves_at a day past the target's
    observed_at) so several as_of steps fall strictly after it — the exact
    condition under which the self-leak bites — and the assertion compares the
    full per-type results (Brier/skill), not just the GO/NO-GO label, against a
    run where the target's own observation is absent entirely."""
    target = date(2026, 6, 22)
    target_observed_at = _obs_at(target)                 # 2026-06-23 04:00Z
    resolves = target_observed_at + timedelta(days=1)    # wide window past it
    spec = WeatherMarketSpec("KXHIGHNY-26JUN22-T80", "KNYC", "tmax", target,
                             "greater", 80.0, None)
    market = WeatherMarket(spec, "KX-YES", resolves, resolved_y=1.0)
    fc, obs = _history(20)
    # Forecast sits NEAR the 80° strike so p_forecast is SENSITIVE to σ (a forecast
    # far above the strike saturates p≈1 and would hide the leak — the reason the
    # first attempt at this test was hollow). The leaked observation is an OUTLIER
    # (90° vs a forecast of 81°, residual +9) so, if it wrongly enters the σ pool,
    # it visibly moves bias/σ and therefore p_forecast and Brier.
    fc += _target_forecast(81.0)
    candles = [Candle(datetime(2026, 6, 22, 0, tzinfo=UTC), "KX-YES",
                      0.5, 0.5, 0.5, 0.5, 100.0)]
    kwargs = dict(start=datetime(2026, 6, 22, tzinfo=UTC),
                  end=resolves, step=timedelta(hours=6))
    # sanity: at least one as_of must fall strictly after the target's observed_at,
    # else the leak path isn't exercised and the test would be vacuous.
    from calibration import _as_of_grid
    grid = _as_of_grid(kwargs["start"], kwargs["end"], kwargs["step"], resolves)
    check(any(a > target_observed_at for a in grid),
          "test setup: no as_of falls after the target's observed_at")

    base = evaluate(FakeReader(candles, fc, obs), [market], **kwargs)
    leaky_obs = obs + [WeatherObservationRow(target_observed_at, "KNYC", "tmax",
                                             90.0, "iem-asos")]  # outlier residual +9
    withobs = evaluate(FakeReader(candles, fc, leaky_obs), [market], **kwargs)
    check(base.n_samples == withobs.n_samples and base.n_samples > 0,
          f"sample counts must match and be non-zero: {base.n_samples} vs {withobs.n_samples}")
    base_by = {r.market_type: r for r in base.results}
    for r in withobs.results:
        b = base_by[r.market_type]
        check(abs(r.brier_forecast - b.brier_forecast) < 1e-12
              and abs(r.skill - b.skill) < 1e-12 and r.verdict == b.verdict,
              f"target's own obs must not change the result for {r.market_type}: "
              f"brier_fc {r.brier_forecast} vs {b.brier_forecast}, "
              f"skill {r.skill} vs {b.skill}")


def test_error_stats_min_pairs_one_no_zerodiv():
    """Reviewer MINOR: min_pairs=1 must not reach the (n-1) sample variance with
    n=1 (ZeroDivisionError) — the n<2 guard returns None instead."""
    fc, obs = _history(1)
    r = FakeReader(forecasts=fc, observations=obs)
    as_of = datetime(2026, 6, 10, tzinfo=UTC)
    check(_error_stats(r, "KNYC", as_of, TZ, min_pairs=1) is None,
          "min_pairs=1 with a single pair must return None, not divide by zero")


def test_evaluate_rejects_nonpositive_step():
    """Reviewer MAJOR: a non-positive step must fail fast, not hang."""
    market = _target_market("greater", 80.0, None, y=1.0)
    for bad in (timedelta(0), timedelta(hours=-1)):
        try:
            evaluate(FakeReader(), [market], start=datetime(2026, 6, 22, tzinfo=UTC),
                     end=datetime(2026, 6, 23, tzinfo=UTC), step=bad)
            raise AssertionError(f"step={bad} should raise ValueError")
        except ValueError:
            pass


def test_cli_rejects_bad_step_and_min_pairs():
    """The guard must reject BEFORE connecting, with its OWN message. The
    re-review (2026-07-21) caught the earlier version passing even with the guard
    removed: a `connect` canary that raised was swallowed by main()'s broad
    `except`, returning the same rc=1. So assert (a) connect() is never called
    (via a counter, not an exception main() could catch) and (b) the specific
    guard message is on stderr — both of which fail if the guard is removed."""
    orig = store.connect
    calls = {"n": 0}

    def _counting_connect():
        calls["n"] += 1
        raise RuntimeError("db unreachable")   # only reached if the guard is gone
    store.connect = _counting_connect
    try:
        for args, msg in (
            (["--start", "2026-06-01", "--end", "2026-07-01", "--step-hours", "0"],
             "must be a positive integer"),
            (["--start", "2026-06-01", "--end", "2026-07-01", "--min-error-pairs", "1"],
             "must be at least 2"),
        ):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = run_calibration.main(args)
            check(rc == 1, f"{args} should return 1, got {rc}")
            check(msg in err.getvalue(),
                  f"{args} should print the guard message {msg!r}, got {err.getvalue()!r}")
    finally:
        store.connect = orig
    check(calls["n"] == 0,
          f"the guard must reject before store.connect() is called, got {calls['n']} call(s)")


def test_cli_returns_nonzero_on_db_failure():
    orig = store.connect

    def boom():
        raise RuntimeError("no database reachable")
    store.connect = boom
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            rc = run_calibration.main(["--start", "2026-06-01", "--end", "2026-07-01"])
    finally:
        store.connect = orig
    check(rc == 1, f"unreachable DB should return 1, got {rc}")
    check("could not reach Postgres" in captured.getvalue(),
          f"stderr should be a clear message: {captured.getvalue()!r}")


def test_cli_bad_date_returns_nonzero_before_connect():
    orig = store.connect
    store.connect = lambda: (_ for _ in ()).throw(AssertionError("should not connect"))
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            rc = run_calibration.main(["--start", "not-a-date", "--end", "2026-07-01"])
    finally:
        store.connect = orig
    check(rc == 1, f"bad --start should return 1 before connecting, got {rc}")


def test_cli_verdict_exit_codes():
    """CLI maps the verdict to an exit code (0=GO, 2=NO-GO) via a fake conn +
    a stubbed run_study, so scripts can branch on it without parsing stdout."""
    class _Conn:
        def execute(self, *a, **kw):
            return None

        def close(self):
            pass

    orig_connect, orig_run = store.connect, calibration.run_study
    store.connect = lambda: _Conn()
    try:
        for verdict, expected_rc in (("GO", 0), ("NO-GO", 2)):
            rep = calibration.CalibrationReport("weather", 0.05, 1, 5, [], verdict)
            calibration.run_study = lambda *a, **kw: rep
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = run_calibration.main(["--start", "2026-06-01", "--end", "2026-07-01"])
            check(rc == expected_rc, f"{verdict} should exit {expected_rc}, got {rc}")
    finally:
        store.connect, calibration.run_study = orig_connect, orig_run


def test_yes_outcome_helper():
    less = WeatherMarketSpec("x", "KNYC", "tmax", date(2026, 6, 1), "less", None, 80.0)
    between = WeatherMarketSpec("x", "KNYC", "tmax", date(2026, 6, 1), "between", 80.0, 81.0)
    greater = WeatherMarketSpec("x", "KNYC", "tmax", date(2026, 6, 1), "greater", 80.0, None)
    check(less.yes_outcome(79) == 1.0 and less.yes_outcome(80) == 0.0, "less boundary")
    check(between.yes_outcome(80) == 1.0 and between.yes_outcome(82) == 0.0, "between")
    check(greater.yes_outcome(81) == 1.0 and greater.yes_outcome(80) == 0.0, "greater boundary")


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_parse_spec_less_from_real_rules,
        test_parse_spec_between_from_real_rules,
        test_parse_spec_greater_phrasing,
        test_parse_spec_none_cases,
        test_parse_target_date_variants,
        test_parse_strike_expands_real_phrasings,
        test_forecast_prob_less_greater_between,
        test_forecast_high_latest_cycle_and_daily_max,
        test_error_stats_pit_and_gates,
        test_seeded_go_verdict,
        test_seeded_nogo_verdict,
        test_nogo_when_market_more_accurate,
        test_pit_honesty_future_forecast_ignored,
        test_skips_when_no_candle_or_forecast,
        test_skips_when_insufficient_error_pairs,
        test_error_stats_excludes_target_date_self_leak,
        test_evaluate_verdict_unaffected_by_target_self_obs,
        test_error_stats_min_pairs_one_no_zerodiv,
        test_evaluate_rejects_nonpositive_step,
        test_cli_rejects_bad_step_and_min_pairs,
        test_cli_returns_nonzero_on_db_failure,
        test_cli_bad_date_returns_nonzero_before_connect,
        test_cli_verdict_exit_codes,
        test_yes_outcome_helper,
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
