"""
climatology.py — the point-in-time precipitation benchmark behind MRAIN-1's
calibration gate (ADR-0028 piece C).

The question a monthly rain market asks is *"will station S accumulate more
than N inches during calendar month M?"*, and the useful thing about it —
the reason ADR-0024 called the mechanism sound where daily-temperature
markets failed — is that the outcome is **partially observed**. Standing
inside the month on day k:

    total = accumulation_already_observed + residual_over_remaining_days

The first term is arithmetic over data already in hand. Only the second is
uncertain. So the benchmark does not need a subseasonal forecast (which does
not usefully exist at these lead times); it needs a distribution for "how
much rain falls at this station between day k and month end", which is a
climatological question answerable from the station's own history.

    P(YES) = P(residual > N - accumulation_to_date)

Method: **empirical, not parametric.** For each prior year the store has
data for, sum that year's precipitation over the *same calendar window*
(day k+1 .. month end, same month), then read the exceedance probability
straight off those samples. Using the identical calendar window across years
handles within-month seasonality and the shrinking number of remaining days
for free, with no distributional assumption. ADR-0028 chose this over
fitting a gamma/lognormal because IEM's per-station history is deep enough
(decades) to support it, and because this project has repeatedly preferred
verified-simple to modelled-elegant (fees.py, the FLB-1 decile studies).

Two properties this module is careful about, both of which would quietly
wreck a Brier-scored study:

**Point-in-time honesty.** Every read goes through the `< as_of` observation
reader, and the year being predicted is excluded from its own climatology.
A benchmark that peeks at the outcome it is predicting scores brilliantly
and means nothing — the same leak ADR-0013 caught in WP-7's error-statistics
path (`exclude_date`), arriving here as "exclude the target year".

**Never returning exactly 0 or 1.** An empirical CDF over n samples has no
resolution beyond 1/n, so a strike outside the observed range reads as
0.000 or 1.000. Brier-scoring a confident 0 against an outcome of 1 is the
single most expensive mistake such a study can make, and it would be an
artifact of sample size rather than a real belief. `prob_exceeds` applies a
Laplace-style correction, so probabilities live in (0, 1) and shrink toward
the achievable resolution as n falls.

Reader-based (never conn-based), mirroring prob_fn/calibration, so it is
testable against a synthetic in-memory history with no database.
"""
from __future__ import annotations
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

PRECIP_VARIABLE = "precip"

# A year is only usable as a climatology sample if it actually has (nearly)
# every day of the window. A year missing half its December days would
# contribute a systematically too-small total and bias the benchmark toward
# "it will not rain enough", i.e. toward NO on every market. 0.9 tolerates the
# occasional ASOS outage without admitting a badly-gapped year.
DEFAULT_MIN_COVERAGE = 0.9

# Minimum distinct prior years before this module will claim a probability at
# all. Below it, `residual_probability` returns None and the caller must skip
# the sample rather than score a number nobody should trust. Five is already
# thin — it is a floor, not a target.
DEFAULT_MIN_YEARS = 5


@dataclass(frozen=True)
class ResidualSample:
    """One prior year's realized precipitation over the target window."""
    year: int
    total: float
    days_covered: int
    days_in_window: int


def _obs_local_date(observed_at: datetime, tz: ZoneInfo) -> date:
    """The calendar date an observation describes.

    WP-6 stores `observed_at` as the start of the *next* local day (so the
    value is never timestamped earlier than it was knowable), so the date it
    describes is one local day back. Same convention calibration.py uses; if
    these two ever disagree the study silently pairs each day's rain with the
    wrong day's market."""
    return (observed_at.astimezone(tz) - timedelta(days=1)).date()


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def collect_daily_precip(observations, tz: ZoneInfo) -> dict[date, float]:
    """Observation rows -> {local calendar date: inches}. Later rows win on a
    duplicate date, which is what the store's own upsert semantics imply."""
    out: dict[date, float] = {}
    for o in observations:
        out[_obs_local_date(o.observed_at, tz)] = float(o.value)
    return out


def accumulation_to_date(daily: dict[date, float], *, year: int, month: int,
                         through_day: int) -> tuple[float, int]:
    """(inches accumulated, days present) for days 1..through_day of the target
    month. `through_day` is inclusive and may be 0 (nothing observed yet)."""
    total = 0.0
    present = 0
    for day in range(1, through_day + 1):
        v = daily.get(date(year, month, day))
        if v is not None:
            total += v
            present += 1
    return total, present


def residual_samples(daily: dict[date, float], *, target_year: int, month: int,
                     from_day: int, min_coverage: float = DEFAULT_MIN_COVERAGE
                     ) -> list[ResidualSample]:
    """Prior years' precipitation over [from_day .. month end] of `month`.

    The target year is excluded: it is the quantity being predicted, and
    including it would let the benchmark score itself against its own answer.
    Years whose coverage of the window falls below `min_coverage` are dropped
    rather than counted short — a gap-driven undercount biases every market in
    the same direction (toward NO), which is exactly the kind of systematic
    error a Brier comparison would misread as skill."""
    years = {d.year for d in daily if d.month == month}
    samples: list[ResidualSample] = []
    for year in sorted(years):
        if year == target_year:
            continue
        last = _days_in_month(year, month)
        if from_day > last:
            continue
        window = range(from_day, last + 1)
        n_window = len(window)
        total = 0.0
        covered = 0
        for day in window:
            v = daily.get(date(year, month, day))
            if v is not None:
                total += v
                covered += 1
        if n_window == 0 or covered / n_window < min_coverage:
            continue
        samples.append(ResidualSample(year=year, total=total,
                                      days_covered=covered,
                                      days_in_window=n_window))
    return samples


def prob_exceeds(samples: list[float], threshold: float) -> float:
    """P(residual > threshold) from an empirical sample, kept strictly inside
    (0, 1).

    The correction is Laplace's rule of succession — (k + 0.5) / (n + 1) —
    rather than the raw k/n. With n prior years, the raw estimate can only
    take n+1 distinct values and pins to exactly 0 or 1 whenever the threshold
    sits outside the observed range, which for these markets is common (a
    strike far above anything on record). Scoring a 0.000 that turns out to be
    1 contributes the maximum possible Brier penalty on the strength of a
    sample-size artifact; this keeps the estimate honest about its own
    resolution instead."""
    n = len(samples)
    if n == 0:
        raise ValueError("prob_exceeds needs at least one sample")
    k = sum(1 for s in samples if s > threshold)
    return (k + 0.5) / (n + 1.0)


def residual_probability(daily: dict[date, float], *, target_year: int,
                         month: int, as_of_day: int, threshold_remaining: float,
                         min_coverage: float = DEFAULT_MIN_COVERAGE,
                         min_years: int = DEFAULT_MIN_YEARS) -> float | None:
    """P(remaining-month precipitation > `threshold_remaining`), or None when
    too few prior years qualify to say anything.

    `as_of_day` is the last day already observed; the residual window is
    `as_of_day + 1 .. month end`. A threshold at or below zero means the
    market is already decided YES on accumulated rain alone — returned as a
    near-certainty rather than 1.0, since the store could still be missing a
    day (and a hard 1.0 would be unrecoverable if it were)."""
    samples = residual_samples(daily, target_year=target_year, month=month,
                               from_day=as_of_day + 1,
                               min_coverage=min_coverage)
    if len(samples) < min_years:
        return None
    if threshold_remaining < 0.0:
        # Already over the strike with observed rain alone. Still routed
        # through the same correction so no probability in this module can
        # ever be exactly 1.0 (see prob_exceeds).
        return prob_exceeds([s.total for s in samples], -1.0)
    return prob_exceeds([s.total for s in samples], threshold_remaining)


if __name__ == "__main__":
    # Synthetic demo: no network, no database. Ten prior Decembers of known
    # rainfall, then a mid-month position in the eleventh.
    tz = ZoneInfo("America/New_York")
    daily: dict[date, float] = {}
    for i, year in enumerate(range(2014, 2024)):
        for day in range(1, 32):
            # each prior year deposits a steady 0.1-0.2in/day
            daily[date(year, 12, day)] = 0.1 + (i % 2) * 0.1
    # the year under study: a wet first half
    for day in range(1, 16):
        daily[date(2024, 12, day)] = 0.2

    acc, present = accumulation_to_date(daily, year=2024, month=12, through_day=15)
    print(f"accumulated through Dec 15 2024: {acc:.2f}in over {present} day(s)")
    samples = residual_samples(daily, target_year=2024, month=12, from_day=16)
    print(f"prior-year residual samples (Dec 16-31): "
          f"{[round(s.total, 2) for s in samples]}")
    for strike in (3.0, 4.0, 6.0, 9.0):
        p = residual_probability(daily, target_year=2024, month=12, as_of_day=15,
                                 threshold_remaining=strike - acc)
        print(f"  P(total > {strike:.1f}in) = {p:.3f}"
              if p is not None else f"  P(total > {strike:.1f}in) = None")
