"""
tests/test_rain_calibration.py — MRAIN-1's gate wiring (src/rain_calibration.py,
ADR-0028 piece D).

Standalone, no pytest, no network, no database. The emphasis is on the two
places a silent error would corrupt every downstream number rather than
raise: **strike parsing** and **which month the market is about** (ADR-0012's
mis-parsed-strike caution, which the MRAIN-1 pre-registration explicitly
inherited), plus the point-in-time boundary.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rain_calibration  # noqa: E402
import weather_ingest  # noqa: E402
from rain_calibration import (  # noqa: E402
    RainMarket, RainMarketSpec, evaluate, parse_rain_market_spec,
    rain_probability,
)
from store import Candle, WeatherObservationRow  # noqa: E402

TZ = ZoneInfo("America/New_York")
RULES = ("If the total precipitation at Central Park, New York City in "
         "{month} {year} is strictly greater than {n} inches, then the market "
         "resolves to Yes.")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _obs_at(d: date) -> datetime:
    nd = d + timedelta(days=1)
    return datetime(nd.year, nd.month, nd.day, tzinfo=TZ).astimezone(timezone.utc)


class _FakeReader:
    def __init__(self, observations=(), candles=()):
        self._o, self._c = list(observations), list(candles)

    def candles_before(self, token_id, as_of):
        return [c for c in self._c if c.token_id == token_id and c.ts < as_of]

    def forecasts_before(self, station, variable, as_of):
        return []

    def observations_before(self, station, variable, as_of):
        return [o for o in self._o if o.station == station
                and o.variable == variable and o.observed_at < as_of]


def _precip_history(years, month, per_day, station="KNYC"):
    rows = []
    for year in years:
        last = 31 if month == 12 else 30
        for day in range(1, last + 1):
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            rows.append(WeatherObservationRow(_obs_at(d), station, "precip",
                                              per_day, "iem-asos"))
    return rows


# ---------------------------------------------------------------------------
# spec parsing — strike and target month
# ---------------------------------------------------------------------------
def test_parse_basic_market():
    spec = parse_rain_market_spec(
        "KXRAINNYCM-25DEC-4", RULES.format(month="Dec", year=2025, n=4))
    check(spec is not None, "a well-formed market must parse")
    check(spec.station == "KNYC", f"station: {spec.station}")
    check((spec.year, spec.month) == (2025, 12), f"target month: {spec}")
    check(spec.threshold_in == 4.0, f"threshold: {spec.threshold_in}")


def test_parse_legacy_ticker_prefix():
    """The archive carries both `KXRAINNYCM-...` and the older
    `RAINNYCM-...` for the same family (confirmed live). Dropping the legacy
    prefix would silently discard the deepest, oldest history — exactly the
    data MRAIN-1 was reopened to use."""
    spec = parse_rain_market_spec(
        "RAINNYCM-24FEB-6", RULES.format(month="Feb", year=2024, n=6))
    check(spec is not None, "legacy-prefixed tickers must still parse")
    check(spec.station == "KNYC" and (spec.year, spec.month) == (2024, 2),
          f"legacy ticker parsed wrong: {spec}")


def test_parse_decimal_threshold():
    """Real tickers carry fractional strikes (RAINNYCM-##APR-#.#)."""
    spec = parse_rain_market_spec(
        "RAINNYCM-24APR-2.5", RULES.format(month="Apr", year=2024, n="2.5"))
    check(spec is not None and spec.threshold_in == 2.5,
          f"decimal strike must parse exactly: {spec}")


def test_strike_is_strictly_greater():
    """Kalshi's phrasing is 'strictly greater than N' on every KXRAIN*M market
    (ADR-0028). A total exactly equal to the strike is a NO."""
    spec = RainMarketSpec("X", "KNYC", 2025, 12, 4.0)
    check(spec.yes_outcome(4.0) == 0.0, "total == strike must resolve NO")
    check(spec.yes_outcome(4.0001) == 1.0, "total just above strike is YES")
    check(spec.yes_outcome(3.99) == 0.0, "total below strike is NO")


def test_unparseable_rules_are_skipped_not_guessed():
    """A phrasing this parser does not understand must yield None. Guessing a
    strike silently corrupts every sample drawn from that market."""
    for rules in ("If it rains a lot in Dec 2025, resolves Yes.",
                  "If precipitation is between 2 and 3 inches in Dec 2025...",
                  "If the total is at least 4 inches in Dec 2025...",
                  None):
        spec = parse_rain_market_spec("KXRAINNYCM-25DEC-4", rules)
        check(spec is None, f"unrecognized rules must be skipped, got {spec}")


def test_unmapped_series_is_skipped():
    spec = parse_rain_market_spec("KXRAINXXXM-25DEC-4",
                                  RULES.format(month="Dec", year=2025, n=4))
    check(spec is None, f"an unmapped series must be skipped: {spec}")


def test_ticker_rules_month_disagreement_is_skipped():
    """If the ticker and the rules name different months, the market is
    ambiguous. Picking one would score the benchmark against a different
    month's rainfall than the market settled on."""
    spec = parse_rain_market_spec("KXRAINNYCM-25DEC-4",
                                  RULES.format(month="Nov", year=2025, n=4))
    check(spec is None, f"a month disagreement must be skipped: {spec}")


def test_full_month_name_in_rules_parses():
    spec = parse_rain_market_spec("KXRAINNYCM-25DEC-4",
                                  RULES.format(month="December", year=2025, n=4))
    check(spec is not None and spec.month == 12,
          f"a full month name must parse: {spec}")


# ---------------------------------------------------------------------------
# rain_probability — PIT behaviour
# ---------------------------------------------------------------------------
def test_probability_uses_only_pre_as_of_observations():
    """The decisive PIT check. Two identical calls differing only in `as_of`
    must see different accumulations — and the later one must never be able
    to see rain that had not fallen yet."""
    history = _precip_history(range(2013, 2025), 12, 0.10)
    target = [WeatherObservationRow(_obs_at(date(2025, 12, d)), "KNYC",
                                    "precip", 1.0, "iem-asos")
              for d in range(1, 32)]
    reader = _FakeReader(history + target)
    spec = RainMarketSpec("KXRAINNYCM-25DEC-9", "KNYC", 2025, 12, 9.0)

    early = rain_probability(reader, spec, datetime(2025, 12, 6, 12,
                                                    tzinfo=timezone.utc), TZ)
    late = rain_probability(reader, spec, datetime(2025, 12, 26, 12,
                                                   tzinfo=timezone.utc), TZ)
    check(early is not None and late is not None,
          f"both instants should be answerable: {early}, {late}")
    # by Dec 26, ~25in has fallen against a 9in strike -> effectively certain;
    # on Dec 6 only ~5in has, with the rest still uncertain
    check(late > early,
          f"a market accumulating past its strike must become MORE likely: "
          f"early={early}, late={late}")


def test_probability_none_when_station_history_too_short():
    """Two prior Decembers is not a climatology. None means the caller skips
    the sample rather than scoring a number nobody should trust."""
    reader = _FakeReader(_precip_history(range(2023, 2025), 12, 0.10))
    spec = RainMarketSpec("KXRAINNYCM-25DEC-4", "KNYC", 2025, 12, 4.0)
    p = rain_probability(reader, spec,
                         datetime(2025, 12, 15, tzinfo=timezone.utc), TZ)
    check(p is None, f"expected None on a 2-year history, got {p}")


def test_probability_never_zero_or_one():
    """Even an absurd strike must stay inside (0,1) — a hard 0.0 that turns
    out YES takes the maximum Brier penalty on a sample-size artifact."""
    reader = _FakeReader(_precip_history(range(2010, 2025), 12, 0.10))
    spec = RainMarketSpec("KXRAINNYCM-25DEC-99", "KNYC", 2025, 12, 99.0)
    p = rain_probability(reader, spec,
                         datetime(2025, 12, 15, tzinfo=timezone.utc), TZ)
    check(p is not None and 0.0 < p < 1.0,
          f"probability must stay strictly inside (0,1): {p}")


def test_probability_before_month_starts_uses_full_month_climatology():
    """Markets are listed weeks ahead of their month. With nothing accumulated
    the benchmark must still answer, from the whole-month climatology."""
    reader = _FakeReader(_precip_history(range(2010, 2025), 12, 0.10))
    spec = RainMarketSpec("KXRAINNYCM-25DEC-2", "KNYC", 2025, 12, 2.0)
    p = rain_probability(reader, spec,
                         datetime(2025, 11, 20, tzinfo=timezone.utc), TZ)
    check(p is not None, "a market listed before its month must be scorable")
    # prior Decembers total 3.1in each, comfortably over a 2in strike
    check(p > 0.5, f"3.1in typical vs a 2in strike should be likely: {p}")


# ---------------------------------------------------------------------------
# evaluate — end-to-end scoring
# ---------------------------------------------------------------------------
def test_evaluate_scores_price_against_benchmark():
    history = _precip_history(range(2010, 2025), 12, 0.20)   # 6.2in typical
    target = [WeatherObservationRow(_obs_at(date(2025, 12, d)), "KNYC",
                                    "precip", 0.20, "iem-asos")
              for d in range(1, 32)]
    candles = [Candle(datetime(2025, 12, d, tzinfo=timezone.utc), "R-YES",
                      0.5, 0.5, 0.5, 0.5, 10.0) for d in (5, 10, 15, 20, 25)]
    reader = _FakeReader(history + target, candles)
    spec = RainMarketSpec("KXRAINNYCM-25DEC-4", "KNYC", 2025, 12, 4.0)
    resolves = datetime(2026, 1, 1, 5, tzinfo=timezone.utc)
    report = evaluate(reader, [RainMarket(spec, "R-YES", resolves, 1.0)],
                      start=datetime(2025, 12, 1, tzinfo=timezone.utc),
                      end=resolves, step=timedelta(days=5))
    check(report.n_samples > 0, "samples must be produced")
    check(report.n_markets == 1, f"one market studied: {report.n_markets}")
    r = report.results[0]
    check(r.market_type == "rain:precip:greater", f"type: {r.market_type}")
    # the benchmark knows 6.2in > 4in; the price sits at 0.50 and is wrong
    check(r.brier_forecast < r.brier_price,
          f"benchmark should beat a stale 0.50 price: fc={r.brier_forecast} "
          f"px={r.brier_price}")


def test_evaluate_skips_markets_without_candles():
    """No price at an instant means no comparison — the sample is skipped,
    not scored against a fabricated price."""
    reader = _FakeReader(_precip_history(range(2010, 2025), 12, 0.20), [])
    spec = RainMarketSpec("KXRAINNYCM-25DEC-4", "KNYC", 2025, 12, 4.0)
    resolves = datetime(2026, 1, 1, 5, tzinfo=timezone.utc)
    report = evaluate(reader, [RainMarket(spec, "R-YES", resolves, 1.0)],
                      start=datetime(2025, 12, 1, tzinfo=timezone.utc),
                      end=resolves, step=timedelta(days=5))
    check(report.n_samples == 0, f"no candles -> no samples: {report.n_samples}")
    check(report.n_markets == 0, f"and no market counted as studied")


def test_evaluate_never_samples_past_resolution():
    """`_as_of_grid` must not walk past resolves_at — a sample taken after
    settlement would price a market whose answer is public."""
    history = _precip_history(range(2010, 2025), 12, 0.20)
    target = [WeatherObservationRow(_obs_at(date(2025, 12, d)), "KNYC",
                                    "precip", 0.20, "iem-asos")
              for d in range(1, 32)]
    candles = [Candle(datetime(2026, 1, d, tzinfo=timezone.utc), "R-YES",
                      0.5, 0.5, 0.5, 0.5, 10.0) for d in (2, 3, 4)]
    reader = _FakeReader(history + target, candles)
    spec = RainMarketSpec("KXRAINNYCM-25DEC-4", "KNYC", 2025, 12, 4.0)
    resolves = datetime(2026, 1, 1, 5, tzinfo=timezone.utc)
    report = evaluate(reader, [RainMarket(spec, "R-YES", resolves, 1.0)],
                      start=datetime(2025, 12, 1, tzinfo=timezone.utc),
                      end=datetime(2026, 1, 10, tzinfo=timezone.utc),
                      step=timedelta(days=5))
    check(report.n_samples == 0,
          f"candles only exist after resolution, so nothing may be scored: "
          f"{report.n_samples}")


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_parse_basic_market,
        test_parse_legacy_ticker_prefix,
        test_parse_decimal_threshold,
        test_strike_is_strictly_greater,
        test_unparseable_rules_are_skipped_not_guessed,
        test_unmapped_series_is_skipped,
        test_ticker_rules_month_disagreement_is_skipped,
        test_full_month_name_in_rules_parses,
        test_probability_uses_only_pre_as_of_observations,
        test_probability_none_when_station_history_too_short,
        test_probability_never_zero_or_one,
        test_probability_before_month_starts_uses_full_month_climatology,
        test_evaluate_scores_price_against_benchmark,
        test_evaluate_skips_markets_without_candles,
        test_evaluate_never_samples_past_resolution,
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
    print(f"\n{len(tests)} passed, 0 failed — ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
