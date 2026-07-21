"""
run_calibration.py — WP-7 entry point: run the edge-room GO/NO-GO study over the
stored Kalshi weather data and print a per-market-type verdict.

    python3 src/run_calibration.py --start 2026-06-01 --end 2026-07-01 --step-hours 12
    python3 src/run_calibration.py --start 2026-06-01 --end 2026-07-01 --margin 0.05

Reads only stored tables (candlestick / weather_forecast / weather_observation /
market — WP-1/WP-3/WP-6), point-in-time honest via store.py's `< as_of` readers.
Builds a naive forecast->probability benchmark and scores it against the market
price by Brier skill; GO if the forecast is more accurate than the price by at
least `--margin` (default 0.05 relative skill), else NO-GO — a valid, non-blocking
outcome that stops Track B before WP-8 (plan.md WP-7).

Needs a real Postgres reachable via $DATABASE_URL (README -> "Database setup").
Degrades gracefully (clear stderr, non-zero exit) if it is unavailable — never a
bare traceback. Read-only: no ingestion, no EV/sizing, no orders, no writes.
"""
from __future__ import annotations
import argparse
import sys
import traceback
from datetime import datetime, time, timedelta, timezone

import calibration
import store


def _parse_day(s: str, *, end: bool = False) -> datetime:
    d = datetime.fromisoformat(s).date()
    t = time(23, 59, 59) if end else time(0, 0)
    return datetime.combine(d, t, tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the WP-7 edge-room GO/NO-GO calibration study.")
    parser.add_argument("--category", default="weather",
                        help="market category to study (default weather)")
    parser.add_argument("--start", required=True, help="study window start (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="study window end (YYYY-MM-DD)")
    parser.add_argument("--step-hours", type=int, default=12,
                        help="as_of decision-step granularity in hours (default 12)")
    parser.add_argument("--margin", type=float, default=calibration.DEFAULT_MARGIN,
                        help="pre-registered relative-Brier-skill GO threshold "
                             f"(default {calibration.DEFAULT_MARGIN})")
    parser.add_argument("--min-error-pairs", type=int,
                        default=calibration.DEFAULT_MIN_ERROR_PAIRS,
                        help="min forecast/obs pairs to estimate forecast error σ "
                             f"(default {calibration.DEFAULT_MIN_ERROR_PAIRS})")
    args = parser.parse_args(argv)

    try:
        start = _parse_day(args.start)
        end = _parse_day(args.end, end=True)
    except ValueError as e:
        print(f"invalid --start/--end date: {e}", file=sys.stderr)
        return 1
    if end <= start:
        print("--end must be after --start", file=sys.stderr)
        return 1
    if args.step_hours <= 0:
        # A non-positive step never advances the as_of grid — it would hang
        # calibration._as_of_grid indefinitely — so reject it here, before we
        # open a connection (reviewer 2026-07-21).
        print("--step-hours must be a positive integer", file=sys.stderr)
        return 1
    if args.min_error_pairs < 2:
        # Need at least 2 residual pairs for a sample variance (n-1); 1 would
        # divide by zero deep in _error_stats (reviewer 2026-07-21).
        print("--min-error-pairs must be at least 2", file=sys.stderr)
        return 1

    try:
        conn = store.connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print(f"could not reach Postgres via $DATABASE_URL (see README -> "
              f"'Database setup'): {type(e).__name__}: {e}", file=sys.stderr)
        try:
            conn.close()   # may not be bound if connect() itself raised
        except Exception:
            pass
        return 1

    try:
        report = calibration.run_study(
            conn, category=args.category, start=start, end=end,
            step=timedelta(hours=args.step_hours), margin=args.margin,
            min_error_pairs=args.min_error_pairs)
    except Exception as e:
        print(f"unexpected error during calibration study: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(report.format())
    if report.n_samples == 0:
        print("\n(no samples — no resolved weather markets with parseable specs "
              "and sufficient forecast/observation history in the window; ingest "
              "more via run_kalshi_ingest / run_weather_ingest first)",
              file=sys.stderr)
    # exit code encodes the verdict for scripting: 0 = GO, 2 = NO-GO, 1 = error.
    return 0 if report.overall_verdict == "GO" else 2


if __name__ == "__main__":
    sys.exit(main())
