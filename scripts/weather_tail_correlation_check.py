"""
scripts/weather_tail_correlation_check.py — does temperature volatility
co-move across the FLB-1 ladder cities, and what happened on the two dates
that produced FLB-1's only observed losses?

Follows ADR-0020: the decile study (ADR-0019) found all 3 losses in the
[0.90,0.99] weather-ladder bucket land on `KXLOWTBOS`, and two of the three
share ONE date (2026-05-26). Two readings were left open, indistinguishable
from Kalshi data alone: (1) KXLOWTBOS is just thin/noisy, or (2) that date was
a real synoptic event whose blast radius the 5 "zero-loss" cities' short
window never happened to test. This script checks reading (2) directly
against NOAA/IEM data this project already ingests (WP-6, ADR-0011) — no new
Kalshi history needed, and unlike Kalshi's settled-market endpoints (ADR-0016/
0018's ~68-day ceiling), IEM's observation archive has no such limit, so this
can look at more days than the Kalshi-side study ever could.

Two checks, cheap and targeted rather than a full historical forecast-error
rebuild (which would need one MOS API call per station per day):

  1. CROSS-CITY ANOMALY CORRELATION over the full ~90-day window the Kalshi
     study covered. Daily tmax, deseasonalized against a trailing 14-day
     rolling mean (so correlation reflects synoptic swings, not the shared
     May->July warming trend every city has regardless of weather systems).
     Pairwise Pearson correlation across all 6 stations. This is a proxy for
     "do these cities share weather regimes," not forecast error directly —
     flagged as such in the output; a well-forecast regional heat wave would
     also show up here without implying correlated BUSTS. It's a lower bound
     on the mechanism, not the mechanism itself.
  2. TARGETED CASE STUDY on the two dates that actually broke a Kalshi
     position (2026-05-26, 2026-06-07): MOS forecast issued ~24-30h before
     each date, actual realized error (observed - forecast) at every station,
     not just Boston. Directly answers "was this a Boston-only surprise or
     a wider one" for the two events that matter, without needing a full
     forecast-error time series.

KBOS (Boston Logan) is not in weather_ingest.STATIONS (only KNYC/KLAX/KMDW/
KMIA/KDEN/KAUS/KPHL are curated there) -- constructed here ad hoc following
the same IEM `<STATE>_ASOS` + 3-letter-id convention the existing entries use,
and spot-checked live rather than assumed, per that module's own documented
caveat for uncurated stations.

KMDW (Chicago Midway) is used as the KXHIGHCHI proxy per the existing
STATIONS registry -- this is a diagnostic script about weather correlation,
not a claim about which station Kalshi's rules actually resolve KXHIGHCHI
against (that mapping is explicitly flagged in weather_ingest.py as needing
confirmation before production use).

    python3 scripts/weather_tail_correlation_check.py
"""
from __future__ import annotations
import statistics
import sys
import os
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from weather_ingest import WeatherSource, WeatherStation, WeatherAPIError, OBS_TMAX  # noqa: E402

WINDOW_START = date(2026, 5, 1)
WINDOW_END = date(2026, 7, 27)
BUST_DATES = [date(2026, 5, 26), date(2026, 6, 7)]
ROLLING_DAYS = 14

STATIONS: dict[str, WeatherStation] = {
    "KNYC": WeatherStation("KNYC", "NY_ASOS", "NYC", "America/New_York"),
    "KLAX": WeatherStation("KLAX", "CA_ASOS", "LAX", "America/Los_Angeles"),
    "KMDW": WeatherStation("KMDW", "IL_ASOS", "MDW", "America/Chicago"),
    "KMIA": WeatherStation("KMIA", "FL_ASOS", "MIA", "America/New_York"),
    "KDEN": WeatherStation("KDEN", "CO_ASOS", "DEN", "America/Denver"),
    "KBOS": WeatherStation("KBOS", "MA_ASOS", "BOS", "America/New_York"),
}


def fetch_tmax_series(src: WeatherSource, icao: str, st: WeatherStation) -> dict[date, float]:
    rows = src.observations(st, start=WINDOW_START, end=WINDOW_END)
    return {r.observed_at.date(): r.value for r in rows if r.variable == OBS_TMAX}


def anomaly_series(tmax: dict[date, float]) -> dict[date, float]:
    """tmax(d) minus the trailing ROLLING_DAYS mean strictly before d --
    removes the shared May->July seasonal trend so correlation reflects
    synoptic swings, not "every city gets hotter in summer" pseudo-correlation."""
    days = sorted(tmax)
    out: dict[date, float] = {}
    for d in days:
        window = [tmax[d2] for d2 in days if d2 < d and (d - d2).days <= ROLLING_DAYS]
        if len(window) < 5:      # need a real baseline before computing an anomaly
            continue
        out[d] = tmax[d] - statistics.mean(window)
    return out


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    sa = (sum((x - ma) ** 2 for x in a)) ** 0.5
    sb = (sum((y - mb) ** 2 for y in b)) ** 0.5
    return cov / (sa * sb) if sa > 0 and sb > 0 else float("nan")


def main() -> int:
    src = WeatherSource()
    print(f"Weather tail-correlation check — window {WINDOW_START} .. {WINDOW_END}\n")

    print("Fetching daily tmax observations...")
    tmax_by_station: dict[str, dict[date, float]] = {}
    for icao, st in STATIONS.items():
        try:
            tmax_by_station[icao] = fetch_tmax_series(src, icao, st)
            print(f"  {icao:<6} {len(tmax_by_station[icao])} daily tmax rows")
        except WeatherAPIError as e:
            print(f"  {icao:<6} FAILED: {e}")
            return 1

    # -- check 1: cross-city anomaly correlation -----------------------------
    print(f"\n{'=' * 78}\nCHECK 1 — cross-city tmax-anomaly correlation "
          f"(deseasonalized, {ROLLING_DAYS}d trailing mean)\n{'=' * 78}")
    anomalies = {icao: anomaly_series(t) for icao, t in tmax_by_station.items()}
    common_dates = sorted(set.intersection(*(set(a) for a in anomalies.values())))
    print(f"dates with a valid anomaly at all 6 stations: {len(common_dates)}\n")

    icaos = list(STATIONS)
    header = "         " + "".join(f"{c:>7}" for c in icaos)
    print(header)
    for a in icaos:
        row = [anomalies[a][d] for d in common_dates]
        cells = []
        for b in icaos:
            rowb = [anomalies[b][d] for d in common_dates]
            r = pearson(row, rowb)
            cells.append(f"{r:>7.2f}")
        print(f"{a:<9}" + "".join(cells))

    # -- check 2: the two actual bust dates, every station ------------------
    print(f"\n{'=' * 78}\nCHECK 2 — the two dates that broke a KXLOWTBOS position: "
          f"tmax anomaly, all 6 cities\n{'=' * 78}")
    print(f"{'date':<14}" + "".join(f"{c:>8}" for c in icaos))
    for d in BUST_DATES:
        cells = []
        for icao in icaos:
            v = anomalies[icao].get(d)
            cells.append(f"{v:>+8.1f}" if v is not None else f"{'—':>8}")
        print(f"{str(d):<14}" + "".join(cells))
    print(f"\n(anomaly = actual tmax minus trailing {ROLLING_DAYS}-day mean, degrees F. "
          f"KBOS is the city whose Kalshi ladder actually lost on these two dates.)")

    # -- targeted forecast-error case study on the two bust dates -----------
    print(f"\n{'=' * 78}\nCHECK 3 — realized ~24-30h-lead forecast error on the two bust "
          f"dates, all 6 cities\n{'=' * 78}")
    print(f"{'date':<14}{'station':<8}{'forecast':>10}{'observed':>10}{'error':>8}")
    for d in BUST_DATES:
        # a runtime the previous afternoon puts ftime_utc for this date's
        # afternoon (when daily tmax is typically set) at roughly 24-30h lead
        # -- comparable to the lead a Kalshi ladder trades at near its close
        # (ADR-0016: ~42h listing window).
        runtime = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(hours=30)
        for icao, st in STATIONS.items():
            try:
                fc = src.forecasts(st, runtime=runtime)
            except WeatherAPIError as e:
                print(f"{str(d):<14}{icao:<8}FAILED: {str(e)[:60]}")
                continue
            # among this cycle's rows, the one valid for the target date whose
            # hour is closest to local mid-afternoon (a rough daily-max proxy,
            # matching FORECAST_VARIABLE's hourly tmpf -- WP-8's concern is the
            # precise daily-max derivation; this is a diagnostic approximation)
            same_day = [r for r in fc if r.valid_at.date() == d]
            if not same_day:
                print(f"{str(d):<14}{icao:<8}(no same-day forecast row at this runtime)")
                continue
            best = max(same_day, key=lambda r: r.value)
            obs = tmax_by_station[icao].get(d)
            if obs is None:
                print(f"{str(d):<14}{icao:<8}(no observation)")
                continue
            err = obs - best.value
            print(f"{str(d):<14}{icao:<8}{best.value:>10.1f}{obs:>10.1f}{err:>+8.1f}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WeatherAPIError as e:
        print(f"IEM API failure: {e}")
        sys.exit(1)
