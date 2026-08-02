"""
scripts/mrain1_settlement_check.py — does our station mapping actually
reproduce Kalshi's own settlements? (ADR-0028's mandatory pre-check, run
per city rather than spot-checked.)

This is the single point where an error would be most expensive and least
visible. Every number MRAIN-1's gate produces is conditioned on
`SERIES_STATION` pointing each Kalshi series at the right NWS/IEM station,
and the mappings are ambiguous in exactly the way that hides: Chicago's rain
market settles on Midway, not O'Hare; Houston's on Hobby, not Bush; Dallas's
on DFW. Pick the wrong airport and the benchmark is scored against a
different city's rain, which does not raise anything — it just quietly
produces a bad Brier score and an unearned NO-GO.

So: for every resolved market in the store, sum our stored IEM precipitation
over its target month and check that `total > strike` reproduces the outcome
Kalshi actually settled. A correct mapping agrees on essentially all of them;
a wrong one disagrees on the roughly half of strikes that sit near the
month's total.

Disagreements are printed with the numbers, not just counted, because the two
innocent causes (a total sitting within rounding distance of the strike, and a
month the store has incomplete data for) are distinguishable by eye and a real
mis-mapping is not subtle.
"""
from __future__ import annotations
import calendar
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

_FOREVER = datetime(2100, 1, 1, tzinfo=timezone.utc)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import climatology  # noqa: E402
import rain_calibration  # noqa: E402
import store  # noqa: E402
import weather_ingest  # noqa: E402


def main() -> int:
    conn = store.connect()
    markets = rain_calibration.load_rain_markets(conn)
    print(f"{len(markets)} resolved rain market(s) with a parseable spec\n")

    # one precip pull per station, then month sums in process
    daily: dict[str, dict[date, float]] = {}
    for st in sorted({m.spec.station for m in markets}):
        tz = ZoneInfo(weather_ingest.STATIONS[st].tz)
        # No PIT horizon here on purpose: this script is not a study, it is a
        # check that settled outcomes are reproducible after the fact, so it
        # wants every row the store has. A horizon anchored to `resolves_at`
        # would shave the target month's final day (WP-6 stamps it at the
        # start of the next local day, which is when these markets resolve)
        # and manufacture a "missing day" on every single market.
        rows = store.observations_before(
            conn, st, climatology.PRECIP_VARIABLE, _FOREVER)
        daily[st] = climatology.collect_daily_precip(rows, tz)
    conn.close()

    # "we have no data for that month" and "our data says the opposite of what
    # Kalshi settled" are different findings and must not be added together.
    # The first is an ingest gap and says nothing about the mapping; the second
    # is the mapping being wrong. Pooling them made every un-backfilled station
    # read as a mis-mapping, which is the sort of false alarm that trains you
    # to ignore the check.
    agree: dict[str, int] = defaultdict(int)
    checkable: dict[str, int] = defaultdict(int)
    nodata: dict[str, int] = defaultdict(int)
    total: dict[str, int] = defaultdict(int)
    series_of: dict[str, set] = defaultdict(set)
    mismatches = []
    for m in markets:
        s = m.spec
        d = daily.get(s.station, {})
        n_days = calendar.monthrange(s.year, s.month)[1]
        present = [d[date(s.year, s.month, k)] for k in range(1, n_days + 1)
                   if date(s.year, s.month, k) in d]
        total[s.station] += 1
        series_of[s.station].add(s.external_id.split("-")[0])
        if len(present) < n_days:
            nodata[s.station] += 1
            continue
        checkable[s.station] += 1
        month_total = sum(present)
        if s.yes_outcome(month_total) == m.resolved_y:
            agree[s.station] += 1
        else:
            mismatches.append((s, month_total, m.resolved_y))

    print(f"{'station':<8} {'series':<14} {'reproduced':>16}  {'no data':>8}")
    print("-" * 52)
    n_ok = n_chk = 0
    suspect = []
    for st in sorted(total):
        n_ok += agree[st]
        n_chk += checkable[st]
        c = checkable[st]
        if c == 0:
            note = "   (not backfilled yet)"
            shown = f"{'-':>7}/{'-':<5}"
        else:
            pct = agree[st] / c
            note = "" if pct >= 0.98 else "   <-- CHECK THIS MAPPING"
            if pct < 0.98:
                suspect.append(st)
            shown = f"{agree[st]:>7}/{c:<5} {pct:>5.1%}"
        print(f"{st:<8} {'/'.join(sorted(series_of[st])):<14} {shown}  "
              f"{nodata[st]:>8}{note}")
    print("-" * 52)
    print(f"{'TOTAL':<23} {n_ok:>5}/{n_chk:<5} "
          f"{(n_ok/n_chk if n_chk else 0):>5.1%}")

    if mismatches:
        print(f"\n{len(mismatches)} market(s) with full data did NOT reproduce:")
        for s, tot, y in mismatches[:40]:
            print(f"  {s.external_id:<24} strike {s.threshold_in:>5.2f}  "
                  f"IEM total {tot:>6.2f}  -> we say "
                  f"{'YES' if tot > s.threshold_in else 'NO':<3}  "
                  f"Kalshi settled {'YES' if y else 'NO'}")
        if len(mismatches) > 40:
            print(f"  ... and {len(mismatches)-40} more")

    if suspect:
        print(f"\nSUSPECT MAPPINGS: {', '.join(suspect)}")
        return 1
    if n_chk < len(markets):
        print(f"\n{len(markets)-n_chk} market(s) skipped for missing precip "
              f"data -- backfill those stations before running the gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
