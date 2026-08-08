"""
scripts/lead_stratified_study.py — does lead-stratifying the error model reopen
the WP-7 gate?

ADR-0014 recorded a NO-GO for Track B using ADR-0012's pre-registered benchmark.
That benchmark has a structural asymmetry worth testing before the gate is
treated as final:

  * To price a market at `as_of`, it takes the forecast daily high for the
    market's (future) target date -- a forecast with a lead of 1-4 days.
  * To get the sigma it maps that forecast through, `_error_stats` pairs each
    PAST observation with "the latest cycle issued before as_of valid on that
    date". For a date already in the past, that is always the final ~16h-lead
    nowcast.

So sigma is estimated at ~16h lead and applied at 40-88h lead. Measured on this
station's own data, that understates the spread by more than 2x:

    lead      n    bias   sigma
    12-24h   83   -0.45    2.45     <- what the benchmark estimates
    36-48h   82   -0.67    2.84
    48-72h   81   -0.80    3.25
    72-120h  80   +9.25    5.76     <- where it is actually applied

An over-tight sigma makes the Gaussian overconfident, which inflates Brier
score precisely where most samples sit. A NO-GO produced that way is a
statement about the benchmark, not about the market.

This script changes ONE thing and holds everything else fixed: the error model
is estimated at the SAME lead the forecast is being used at. For a market with
lead L, each historical date D' contributes a residual built from the forecast
knowable at `end_of_local_day(D') - L` -- the same vantage point, one date
earlier. Point-in-time integrity is preserved: that synthetic decision time is
required to precede `as_of`, and the observation must already be readable.

Everything else -- market set, as_of grid, _forecast_prob, the strike parsing,
the aggregation, the 5% margin, exclude_date -- is reused unchanged from
calibration.py, so the two verdicts are directly comparable.

    python3 scripts/lead_stratified_study.py --start 2026-05-17 --end 2026-07-26

Reads only. Does not modify the shipped gate: ADR-0012's benchmark is
pre-registered and stays as it is regardless of what this finds.
"""
from __future__ import annotations
import argparse
import bisect
import math
import os
import sys
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import calibration  # noqa: E402
import store  # noqa: E402
import weather_ingest  # noqa: E402
from calibration import (  # noqa: E402
    FORECAST_VARIABLE, OBS_VARIABLE, Sample, CalibrationReport,
    _aggregate, _as_of_grid, _forecast_high, _forecast_prob, _local_date,
)
from store import Candle, WeatherForecastRow, WeatherObservationRow  # noqa: E402


class PreloadingReader:
    """Reader that loads each series once and answers `*_before(as_of)` by
    bisecting the already-sorted list.

    The whole dataset is ~78k rows, so holding it is trivial; the alternative
    is tens of thousands of network round trips. This moves WHERE the `< as_of`
    filter runs, not what it means: store.py's readers are
    `WHERE <ts> < as_of ORDER BY <ts>`, and bisect_left on the same column in
    the same order yields the same rows. Validated end-to-end -- with this
    reader the unmodified gate reproduces ADR-0014's published numbers exactly
    (see --validate)."""

    def __init__(self, conn, station: str):
        self._c: dict[str, tuple[list, list]] = {}
        rows = conn.execute(
            "SELECT ot.token_id, c.ts, c.open, c.high, c.low, c.close, c.volume "
            "FROM candlestick c JOIN outcome_token ot ON ot.outcome_id = c.outcome_id "
            "ORDER BY ot.token_id, c.ts").fetchall()
        for tok, ts, o, h, lo, cl, v in rows:
            self._c.setdefault(tok, ([], []))
            keys, vals = self._c[tok]
            keys.append(ts)
            vals.append(Candle(ts, tok, float(o), float(h), float(lo), float(cl),
                               float(v) if v is not None else None))

        f = conn.execute(
            "SELECT issued_at, valid_at, value, source, horizon_h FROM weather_forecast "
            "WHERE station = %s AND variable = %s ORDER BY issued_at",
            (station, FORECAST_VARIABLE)).fetchall()
        self._f = [WeatherForecastRow(i, va, station, FORECAST_VARIABLE, float(val),
                                      src, float(hh) if hh is not None else None)
                   for i, va, val, src, hh in f]
        self._fk = [r.issued_at for r in self._f]

        o = conn.execute(
            "SELECT observed_at, value, source FROM weather_observation "
            "WHERE station = %s AND variable = %s ORDER BY observed_at",
            (station, OBS_VARIABLE)).fetchall()
        self._o = [WeatherObservationRow(oa, station, OBS_VARIABLE, float(v), src)
                   for oa, v, src in o]
        self._ok = [r.observed_at for r in self._o]

    def candles_before(self, token_id: str, as_of: datetime) -> list:
        keys, vals = self._c.get(token_id, ([], []))
        return vals[:bisect.bisect_left(keys, as_of)]

    def forecasts_before(self, station: str, variable: str, as_of: datetime) -> list:
        return self._f[:bisect.bisect_left(self._fk, as_of)]

    def observations_before(self, station: str, variable: str, as_of: datetime) -> list:
        return self._o[:bisect.bisect_left(self._ok, as_of)]


def _end_of_local_day(d: date, tz: ZoneInfo) -> datetime:
    """The instant a date's daily high is final -- midnight starting the next
    local day. WP-6 stores `observed_at` on exactly this convention, so a
    market's lead and a historical date's lead are measured the same way."""
    return datetime.combine(d + timedelta(days=1), dtime(0, 0), tzinfo=tz)


def _lead_error_stats(reader, station: str, as_of: datetime, tz: ZoneInfo,
                      lead: timedelta, min_pairs: int,
                      exclude_date: date | None, memo) -> tuple[float, float] | None:
    """(bias, sigma) of forecast error **at the same lead the forecast is being
    used at**, from history knowable strictly before `as_of`.

    The pooled version pairs each past date with its final nowcast. This pairs
    each past date D' with the forecast that was knowable at the equivalent
    vantage point -- `end_of_local_day(D') - lead` -- so the residuals describe
    the same forecasting problem the market is being priced on.

    PIT: the synthetic vantage point must precede `as_of` (a later one would be
    unknowable), and observations come from the `< as_of` reader. `exclude_date`
    drops the market's own date exactly as in calibration._error_stats."""
    residuals: list[float] = []
    for obs in reader.observations_before(station, OBS_VARIABLE, as_of):
        obs_date = (obs.observed_at.astimezone(tz) - timedelta(days=1)).date()
        if obs_date == exclude_date:
            continue
        vantage = _end_of_local_day(obs_date, tz) - lead
        if vantage >= as_of:
            continue                    # not knowable yet
        f = _forecast_high(reader, station, obs_date, vantage, tz, memo)
        if f is not None:
            residuals.append(obs.value - f)
    n = len(residuals)
    if n < min_pairs or n < 2:
        return None
    bias = sum(residuals) / n
    var = sum((r - bias) ** 2 for r in residuals) / (n - 1)
    if var <= 0.0:
        return None
    return bias, math.sqrt(var)


def evaluate_stratified(reader, markets, *, start, end, step,
                        category="weather", margin=calibration.DEFAULT_MARGIN,
                        min_error_pairs=calibration.DEFAULT_MIN_ERROR_PAIRS,
                        lead_quantum_h: int = 24) -> CalibrationReport:
    """calibration.evaluate() with the error model swapped for the
    lead-matched one. Deliberately a copy rather than a flag on the shipped
    function: ADR-0012's benchmark is pre-registered and must not acquire a
    mode that changes what the gate measures."""
    reader = calibration._MemoReader(reader)
    memo = calibration._StudyMemo()
    stats_memo: dict = {}
    samples: list[Sample] = []
    studied = 0
    for mkt in markets:
        spec = mkt.spec
        tz = ZoneInfo(weather_ingest.STATIONS[spec.station].tz)
        market_type = f"{category}:{spec.variable}:{spec.strike_type}"
        final = _end_of_local_day(spec.target_date, tz)
        used = False
        for as_of in _as_of_grid(start, end, step, mkt.resolves_at):
            candles = reader.candles_before(mkt.yes_token_id, as_of)
            if not candles:
                continue
            price = max(candles, key=lambda c: c.ts).close
            f_hat = _forecast_high(reader, spec.station, spec.target_date, as_of,
                                   tz, memo)
            if f_hat is None:
                continue
            # Quantise the lead so residuals aggregate over the daily MOS cycle
            # grid instead of splintering into one-sample buckets.
            lead_h = (final - as_of).total_seconds() / 3600.0
            if lead_h <= 0:
                continue
            q = max(1, round(lead_h / lead_quantum_h))
            lead = timedelta(hours=q * lead_quantum_h)

            key = (spec.station, as_of, lead, spec.target_date, min_error_pairs)
            if key not in stats_memo:
                stats_memo[key] = _lead_error_stats(
                    reader, spec.station, as_of, tz, lead, min_error_pairs,
                    spec.target_date, memo)
            stats = stats_memo[key]
            if stats is None:
                continue
            bias, sigma = stats
            p_forecast = _forecast_prob(spec, f_hat + bias, sigma)
            samples.append(Sample(
                external_id=spec.external_id, market_type=market_type, as_of=as_of,
                lead_h=lead_h, price=float(price), p_forecast=p_forecast,
                y=mkt.resolved_y))
            used = True
        studied += 1 if used else 0

    results = _aggregate(samples, margin)
    overall = "GO" if any(r.verdict == "GO" for r in results) else "NO-GO"
    return CalibrationReport(category=category, margin=margin, n_markets=studied,
                             n_samples=len(samples), results=results,
                             overall_verdict=overall)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--start", default="2026-05-17")
    ap.add_argument("--end", default="2026-07-26")
    ap.add_argument("--step-hours", type=int, default=6)
    ap.add_argument("--station", default="KNYC")
    ap.add_argument("--lead-quantum-h", type=int, default=24)
    args = ap.parse_args(argv)

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    step = timedelta(hours=args.step_hours)

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach Postgres via $DATABASE_URL: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1

    markets = calibration.load_weather_markets(conn, "weather")
    reader = PreloadingReader(conn, args.station)
    conn.close()
    print(f"markets: {len(markets)}   window {start.date()}..{end.date()}   "
          f"step {args.step_hours}h\n")

    pooled = calibration.evaluate(reader, markets, start=start, end=end, step=step,
                                  category="weather")
    print("=" * 78)
    print("A. POOLED error model — ADR-0012's pre-registered benchmark (the gate)")
    print("=" * 78)
    print(pooled.format())

    strat = evaluate_stratified(reader, markets, start=start, end=end, step=step,
                                lead_quantum_h=args.lead_quantum_h)
    print("\n" + "=" * 78)
    print(f"B. LEAD-STRATIFIED error model (lead quantum {args.lead_quantum_h}h)")
    print("=" * 78)
    print(strat.format())

    print("\n" + "=" * 78)
    print("DELTA (B - A), by market type")
    print("=" * 78)
    a = {r.market_type: r for r in pooled.results}
    print(f"  {'market type':<22} {'skill A':>9} {'skill B':>9} {'change':>10}")
    print("  " + "-" * 54)
    for r in strat.results:
        base = a.get(r.market_type)
        if base is None:
            continue
        print(f"  {r.market_type:<22} {base.skill:>8.1%} {r.skill:>9.1%} "
              f"{r.skill - base.skill:>+10.1%}")
    print(f"\n  overall: {pooled.overall_verdict} -> {strat.overall_verdict}")
    return 0 if strat.overall_verdict == "GO" else 2


if __name__ == "__main__":
    sys.exit(main())
