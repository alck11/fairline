"""
tests/test_climatology.py — MRAIN-1's climatological residual benchmark
(src/climatology.py, ADR-0028 piece C).

Standalone, no pytest, no network, no database (repo convention:
`python3 tests/test_climatology.py`). Every fixture is a hand-built daily
precipitation history with a known answer, so each probability below is
checked against arithmetic done by hand rather than against whatever the
code happens to produce.

The properties under test, in the order they would hurt if broken:

  1. the target year is excluded from its own climatology (the leak that
     makes a benchmark score itself — ADR-0013's `exclude_date` bug, in the
     shape it takes here)
  2. probabilities never reach exactly 0 or 1 (a sample-size artifact would
     otherwise take the maximum Brier penalty)
  3. gap-ridden years are dropped, not counted short (a systematic bias
     toward NO on every market)
  4. observation dates follow WP-6's next-local-midnight convention
"""
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import climatology  # noqa: E402
from climatology import (  # noqa: E402
    accumulation_to_date, collect_daily_precip, prob_exceeds,
    residual_probability, residual_samples,
)

TZ = ZoneInfo("America/New_York")


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


@dataclass(frozen=True)
class _Obs:
    """Minimal stand-in for store.WeatherObservationRow (only the two fields
    climatology reads)."""
    observed_at: datetime
    value: float


def _obs_at(d: date, tz=TZ) -> datetime:
    """WP-6's convention: a day's value becomes knowable at the start of the
    NEXT local day, stored in UTC."""
    nd = d + timedelta(days=1)
    return datetime(nd.year, nd.month, nd.day, tzinfo=tz).astimezone(timezone.utc)


def _history(per_year: dict[int, dict[int, float]], month: int) -> dict[date, float]:
    """{year: {day: inches}} -> the {date: inches} mapping the module takes."""
    out: dict[date, float] = {}
    for year, days in per_year.items():
        for day, inches in days.items():
            out[date(year, month, day)] = inches
    return out


# ---------------------------------------------------------------------------
# observation -> calendar date (WP-6 next-local-midnight convention)
# ---------------------------------------------------------------------------
def test_collect_daily_precip_uses_previous_local_day():
    """An observation stamped 2025-12-02T05:00Z (midnight EST on Dec 2)
    describes Dec 1. Getting this backwards shifts every day by one, which
    moves rain across month boundaries and silently mis-sums both the
    accumulation and every climatology sample."""
    obs = [_Obs(_obs_at(date(2025, 12, 1)), 0.25),
           _Obs(_obs_at(date(2025, 12, 2)), 0.50)]
    daily = collect_daily_precip(obs, TZ)
    check(daily == {date(2025, 12, 1): 0.25, date(2025, 12, 2): 0.50},
          f"dates must map back one local day: {daily}")


# ---------------------------------------------------------------------------
# accumulation to date
# ---------------------------------------------------------------------------
def test_accumulation_sums_only_through_the_given_day():
    daily = _history({2025: {d: 0.1 for d in range(1, 32)}}, month=12)
    total, present = accumulation_to_date(daily, year=2025, month=12, through_day=10)
    check(abs(total - 1.0) < 1e-9, f"10 days x 0.1in = 1.0in, got {total}")
    check(present == 10, f"expected 10 days present, got {present}")


def test_accumulation_day_zero_is_empty():
    """Standing before the month starts, nothing is accumulated — and this
    must not raise, since markets are listed weeks ahead of their month."""
    daily = _history({2025: {d: 0.1 for d in range(1, 32)}}, month=12)
    total, present = accumulation_to_date(daily, year=2025, month=12, through_day=0)
    check(total == 0.0 and present == 0, f"expected (0.0, 0), got ({total}, {present})")


def test_accumulation_tolerates_missing_days():
    daily = _history({2025: {1: 0.5, 3: 0.5}}, month=12)   # day 2 missing
    total, present = accumulation_to_date(daily, year=2025, month=12, through_day=3)
    check(abs(total - 1.0) < 1e-9, f"present days only: {total}")
    check(present == 2, f"expected 2 days present, got {present}")


# ---------------------------------------------------------------------------
# residual samples — the PIT-critical part
# ---------------------------------------------------------------------------
def test_target_year_excluded_from_its_own_climatology():
    """THE leak this module is built to avoid. If 2025 appears among its own
    prior-year samples, the benchmark is partly scoring itself against the
    answer — the same class of bug ADR-0013 caught in WP-7's error stats."""
    per_year = {y: {d: 0.1 for d in range(1, 32)} for y in (2021, 2022, 2023, 2024)}
    per_year[2025] = {d: 9.9 for d in range(1, 32)}   # wildly unlike the others
    daily = _history(per_year, month=12)
    samples = residual_samples(daily, target_year=2025, month=12, from_day=16)
    years = sorted(s.year for s in samples)
    check(2025 not in years, f"target year must be excluded, got {years}")
    check(years == [2021, 2022, 2023, 2024], f"all prior years expected: {years}")
    check(all(abs(s.total - 1.6) < 1e-9 for s in samples),
          f"Dec 16-31 = 16 days x 0.1 = 1.6in: {[s.total for s in samples]}")


def test_residual_window_starts_at_from_day_inclusive():
    per_year = {2023: {d: 1.0 for d in range(1, 32)}}
    daily = _history(per_year, month=12)
    samples = residual_samples(daily, target_year=2025, month=12, from_day=30)
    check(len(samples) == 1, f"one prior year expected: {samples}")
    # days 30 and 31 inclusive -> 2.0in
    check(abs(samples[0].total - 2.0) < 1e-9,
          f"from_day must be inclusive (days 30+31 = 2.0in): {samples[0].total}")


def test_low_coverage_years_are_dropped():
    """A year missing most of its window would contribute a too-small total,
    biasing the benchmark toward NO on every single market."""
    per_year = {
        2022: {d: 0.1 for d in range(16, 32)},          # complete: 16/16 days
        2023: {16: 0.1, 17: 0.1},                        # 2/16 days — a gap year
    }
    daily = _history(per_year, month=12)
    samples = residual_samples(daily, target_year=2025, month=12, from_day=16)
    check([s.year for s in samples] == [2022],
          f"only the well-covered year may be used: {[s.year for s in samples]}")


def test_coverage_threshold_is_a_ratio_not_a_count():
    """A short window (few remaining days) must not be penalised for having
    few days — coverage is proportional."""
    per_year = {2022: {30: 0.5, 31: 0.5}}   # 2/2 days of the Dec 30-31 window
    daily = _history(per_year, month=12)
    samples = residual_samples(daily, target_year=2025, month=12, from_day=30)
    check(len(samples) == 1, f"a fully-covered 2-day window is usable: {samples}")


def test_february_leap_year_window_length():
    """Window length comes from each sample year's own calendar, so a leap
    year contributes its 29th and a common year does not."""
    per_year = {2020: {d: 1.0 for d in range(1, 30)},    # leap: 29 days
                2021: {d: 1.0 for d in range(1, 29)}}    # common: 28 days
    daily = _history(per_year, month=2)
    samples = {s.year: s for s in residual_samples(daily, target_year=2025,
                                                    month=2, from_day=28)}
    check(abs(samples[2020].total - 2.0) < 1e-9,
          f"2020 Feb 28-29 = 2.0in: {samples[2020].total}")
    check(abs(samples[2021].total - 1.0) < 1e-9,
          f"2021 Feb 28 only = 1.0in: {samples[2021].total}")


# ---------------------------------------------------------------------------
# prob_exceeds — the (0,1) guarantee
# ---------------------------------------------------------------------------
def test_prob_exceeds_never_returns_zero_or_one():
    """A strike outside the entire observed range is common for these ladders
    (a 7-inch strike where nothing on record exceeds 4). The raw empirical
    rate would be exactly 0.0; scoring that against a YES outcome takes the
    maximum possible Brier penalty on a sample-size artifact."""
    samples = [1.0, 2.0, 3.0]
    p_never = prob_exceeds(samples, 99.0)
    p_always = prob_exceeds(samples, 0.0)
    check(0.0 < p_never < 1.0, f"below-range must stay inside (0,1): {p_never}")
    check(0.0 < p_always < 1.0, f"above-range must stay inside (0,1): {p_always}")
    check(abs(p_never - 0.125) < 1e-9, f"(0+0.5)/(3+1) = 0.125, got {p_never}")
    check(abs(p_always - 0.875) < 1e-9, f"(3+0.5)/(3+1) = 0.875, got {p_always}")


def test_prob_exceeds_is_strict_inequality():
    """Kalshi's rules say 'strictly greater than N inches' (verified across
    every KXRAIN*M market in ADR-0028), so a sample exactly equal to the
    strike is a NO, not a YES."""
    p = prob_exceeds([2.0, 2.0, 2.0], 2.0)
    check(abs(p - 0.125) < 1e-9,
          f"samples equal to the threshold must not count as exceeding: {p}")


def test_prob_exceeds_midrange_is_sensible():
    p = prob_exceeds([1.0, 2.0, 3.0, 4.0], 2.5)   # 2 of 4 exceed
    check(abs(p - 0.5) < 1e-9, f"(2+0.5)/(4+1) = 0.5, got {p}")


def test_prob_exceeds_empty_raises():
    try:
        prob_exceeds([], 1.0)
        raise AssertionError("an empty sample must raise, not return a number")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# residual_probability — the composed benchmark
# ---------------------------------------------------------------------------
def test_residual_probability_returns_none_when_underpowered():
    """Too few prior years must yield None so the caller SKIPS the sample.
    Returning a number here would quietly let a 2-year climatology into a
    study whose whole purpose is measuring whether the model beats a price."""
    per_year = {2023: {d: 0.1 for d in range(1, 32)},
                2024: {d: 0.1 for d in range(1, 32)}}
    daily = _history(per_year, month=12)
    p = residual_probability(daily, target_year=2025, month=12, as_of_day=15,
                             threshold_remaining=1.0)
    check(p is None, f"2 prior years is below the floor; expected None, got {p}")


def test_residual_probability_known_arithmetic():
    """Six prior Decembers, three wet (3.2in over Dec 16-31) and three dry
    (1.6in). A remaining-threshold of 2.0in is exceeded by exactly the three
    wet years -> (3 + 0.5) / (6 + 1) = 0.5."""
    per_year = {}
    for i, year in enumerate(range(2019, 2025)):
        rate = 0.2 if i % 2 == 0 else 0.1
        per_year[year] = {d: rate for d in range(1, 32)}
    daily = _history(per_year, month=12)
    p = residual_probability(daily, target_year=2025, month=12, as_of_day=15,
                             threshold_remaining=2.0)
    check(p is not None and abs(p - 0.5) < 1e-9, f"expected 0.5, got {p}")


def test_already_decided_market_is_near_certain_not_certain():
    """When accumulated rain alone already clears the strike, the answer is
    'as close to 1 as this module ever gets' — never exactly 1.0, because the
    store could still be missing a day and a hard 1.0 is unrecoverable under
    Brier scoring."""
    per_year = {y: {d: 0.1 for d in range(1, 32)} for y in range(2018, 2025)}
    daily = _history(per_year, month=12)
    p = residual_probability(daily, target_year=2025, month=12, as_of_day=20,
                             threshold_remaining=-0.5)   # already over the strike
    check(p is not None, "an already-decided market must still produce a number")
    check(p < 1.0, f"must never be exactly 1.0, got {p}")
    check(p > 0.8, f"but should be near-certain, got {p}")


def test_end_of_month_leaves_no_residual_window():
    """On the last day, `from_day` runs past month end for every sample year,
    so there are no samples and the benchmark declines to answer rather than
    inventing one."""
    per_year = {y: {d: 0.1 for d in range(1, 32)} for y in range(2018, 2025)}
    daily = _history(per_year, month=12)
    p = residual_probability(daily, target_year=2025, month=12, as_of_day=31,
                             threshold_remaining=1.0)
    check(p is None, f"no remaining days -> no climatology sample: {p}")


def test_probability_is_monotonic_in_threshold():
    """A higher remaining-rain requirement can never be MORE likely. Cheap to
    state, and it catches an inverted comparison that unit values alone
    might not."""
    per_year = {}
    for i, year in enumerate(range(2015, 2025)):
        per_year[year] = {d: 0.05 * (i + 1) for d in range(1, 32)}
    daily = _history(per_year, month=12)
    probs = [residual_probability(daily, target_year=2025, month=12, as_of_day=15,
                                  threshold_remaining=t)
             for t in (0.5, 1.5, 3.0, 6.0, 12.0)]
    check(all(p is not None for p in probs), f"all should be answerable: {probs}")
    check(all(a >= b for a, b in zip(probs, probs[1:])),
          f"probability must be non-increasing in threshold: {probs}")


# ---------------------------------------------------------------------------
def main() -> int:
    tests = [
        test_collect_daily_precip_uses_previous_local_day,
        test_accumulation_sums_only_through_the_given_day,
        test_accumulation_day_zero_is_empty,
        test_accumulation_tolerates_missing_days,
        test_target_year_excluded_from_its_own_climatology,
        test_residual_window_starts_at_from_day_inclusive,
        test_low_coverage_years_are_dropped,
        test_coverage_threshold_is_a_ratio_not_a_count,
        test_february_leap_year_window_length,
        test_prob_exceeds_never_returns_zero_or_one,
        test_prob_exceeds_is_strict_inequality,
        test_prob_exceeds_midrange_is_sensible,
        test_prob_exceeds_empty_raises,
        test_residual_probability_returns_none_when_underpowered,
        test_residual_probability_known_arithmetic,
        test_already_decided_market_is_near_certain_not_certain,
        test_end_of_month_leaves_no_residual_window,
        test_probability_is_monotonic_in_threshold,
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
