"""
run_weather_ingest.py — WP-6 entry point: pulls IEM MOS forecasts + ASOS daily
observations for one or more stations into the store (WP-1's schema/upserts).

    python3 src/run_weather_ingest.py --station KNYC --days 30
    python3 src/run_weather_ingest.py --station KXHIGHNY --start 2026-06-01 --end 2026-06-30
    python3 src/run_weather_ingest.py --station KNYC --station KLAX --model NBS --days 14

`--station` accepts a canonical ICAO (KNYC) or a Kalshi series prefix (KXHIGHNY,
mapped via SERIES_STATION); repeat it for several stations. Point the window
(`--days`, or explicit `--start`/`--end`) at the dates covering the Kalshi weather
markets already loaded by run_kalshi_ingest — the observations then cover those
markets' resolution dates (WP-6 acceptance). Auto-deriving stations/dates from the
loaded markets is a documented follow-up (ADR-0011: market->station is curated).

For every station: `weather_ingest.load_forecasts` (MOS -> weather_forecast) and
`weather_ingest.load_observations` (ASOS daily -> weather_observation), both
idempotent via store's ON CONFLICT upserts (re-running does not duplicate rows).

Needs a real Postgres reachable via $DATABASE_URL (README -> "Database setup") and
live network to IEM's public API (no auth). Degrades gracefully on either being
unavailable: a clear message on stderr and a non-zero exit (mirrors
run_kalshi_ingest / US-2), never a bare traceback. Data-only: never computes EV,
sizing, a signal, or places an order.
"""
from __future__ import annotations
import argparse
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import store
import weather_ingest
from weather_ingest import WeatherAPIError, WeatherSource


def _forecast_cycles(start: date, end: date, cycle_hour: int) -> list[datetime]:
    """One MOS model cycle per day at `cycle_hour` UTC across [start, end], but
    never in the future (a runtime past 'now' has no data). Empty list -> caller
    pulls only IEM's latest cycle. Each is a real, past publication instant, so the
    forecast history it backfills is point-in-time honest by construction."""
    now = datetime.now(timezone.utc)
    cycles: list[datetime] = []
    d = start
    while d <= end:
        rt = datetime(d.year, d.month, d.day, cycle_hour, tzinfo=timezone.utc)
        if rt <= now:
            cycles.append(rt)
        d += timedelta(days=1)
    return cycles


def run(src: WeatherSource, conn, *, stations: list[str], model: str,
        start: date, end: date, cycle_hour: int = 12) -> tuple[int, int]:
    """Ingest forecasts + observations for every station over [start, end].
    Forecasts are backfilled one MOS cycle per day (at `cycle_hour` UTC) across the
    window, so a single run captures forecast *history*, not just the latest cycle.
    Returns (total_forecast_rows, total_observation_rows). Raises WeatherAPIError
    / whatever store.py raises on a genuine failure; does no printing beyond
    per-station progress, so it stays easy to call from a test."""
    runtimes = _forecast_cycles(start, end, cycle_hour)
    total_fc = total_obs = 0
    for station in stations:
        n_fc = weather_ingest.load_forecasts(conn, src, station, model=model,
                                             runtimes=runtimes or None)
        n_obs = weather_ingest.load_observations(conn, src, station,
                                                 start=start, end=end)
        total_fc += n_fc
        total_obs += n_obs
        print(f"  {station}: {n_fc} forecast row(s) over {len(runtimes)} cycle(s), "
              f"{n_obs} observation row(s)")
    return total_fc, total_obs


def _parse_window(args) -> tuple[date, date]:
    if args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit("--start and --end must be given together")
        return date.fromisoformat(args.start), date.fromisoformat(args.end)
    end = datetime.now(timezone.utc).date()
    return end - timedelta(days=args.days), end


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull IEM MOS forecasts + ASOS daily observations into the "
                    "store (WP-6).")
    parser.add_argument("--station", action="append", dest="stations", default=None,
                        help="canonical ICAO (KNYC) or Kalshi series prefix "
                             "(KXHIGHNY); repeat for several stations")
    parser.add_argument("--model", default=weather_ingest.DEFAULT_MOS_MODEL,
                        help=f"MOS model id (default {weather_ingest.DEFAULT_MOS_MODEL})")
    parser.add_argument("--days", type=int, default=30,
                        help="trailing observation window in days (default 30); "
                             "ignored if --start/--end given")
    parser.add_argument("--start", default=None, help="observation window start (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="observation window end (YYYY-MM-DD)")
    parser.add_argument("--cycle-hour", type=int, default=12,
                        help="UTC hour of the daily MOS forecast cycle to backfill "
                             "across the window (default 12 = 12Z)")
    args = parser.parse_args(argv)

    stations = args.stations or ["KNYC"]
    try:
        start, end = _parse_window(args)
    except ValueError as e:
        print(f"invalid --start/--end date: {e}", file=sys.stderr)
        return 1

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach Postgres via $DATABASE_URL (see README -> "
              f"'Database setup'): {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    src = WeatherSource()
    try:
        n_fc, n_obs = run(src, conn, stations=stations, model=args.model,
                          start=start, end=end, cycle_hour=args.cycle_hour)
    except WeatherAPIError as e:
        print(f"IEM API failure: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Structural backstop mirroring run_kalshi_ingest.main(): WeatherSource is
        # meant to translate every malformed IEM response into WeatherAPIError, but
        # a store-layer failure (e.g. a psycopg error) or an untested field could
        # still escape run() as a bare exception. Turn it into the same clear
        # message + non-zero exit rather than a bare uncaught traceback (US-2).
        print(f"unexpected error during weather ingest (not a WeatherAPIError -- "
              f"likely a store failure or untested malformed-field case; see "
              f"traceback below): {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"ingested {n_fc} forecast row(s) + {n_obs} observation row(s) across "
          f"{len(stations)} station(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
