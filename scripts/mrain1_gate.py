"""
scripts/mrain1_gate.py — runs MRAIN-1's edge-room gate and prints the report
(ADR-0028 piece E).

    python3 scripts/mrain1_gate.py --start 2024-01-01 --end 2026-07-01

Two numbers matter and they are not the same number:

  * `n_samples` — every (market, instant) pair scored. Thousands.
  * `n_clusters` — distinct **station-months**. Dozens.

A monthly rain ladder is the same weather event priced at a dozen strikes,
sampled every few hours; the samples inside one station-month are almost
perfectly dependent. Reporting significance off `n_samples` is the ladder
trap that ADR-0018/0025 built family clustering to avoid, and it inflates
a t-statistic by roughly sqrt(samples per cluster) — here, ~sqrt(300) ≈ 17x.
So this script reports the Brier gap **per station-month** and tests those
cluster means, not the raw samples.
"""
from __future__ import annotations
import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import rain_calibration  # noqa: E402
import store  # noqa: E402
from calibration import DEFAULT_MARGIN, Sample, _as_of_grid  # noqa: E402
from prob_fn import StoreReader  # noqa: E402


def _day(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _collect(reader, markets, *, start, end, step, min_years, lookback):
    """Same walk as rain_calibration.evaluate, but keeping each Sample's
    station-month so the clustering below can be done honestly. Reusing
    evaluate() would throw that key away and leave only the aggregate."""
    from zoneinfo import ZoneInfo
    import weather_ingest

    memo = rain_calibration._DailyMemo()
    histories = {}
    for mkt in markets:
        st = mkt.spec.station
        if st not in histories:
            histories[st] = rain_calibration._StationHistory(
                reader, st, ZoneInfo(weather_ingest.STATIONS[st].tz), end)

    out = []
    for mkt in markets:
        spec = mkt.spec
        tz = ZoneInfo(weather_ingest.STATIONS[spec.station].tz)
        cluster = f"{spec.station}-{spec.year:04d}-{spec.month:02d}"
        market_start = max(start, mkt.resolves_at - lookback)
        prices = rain_calibration._TokenCandles(reader, mkt.yes_token_id, end)
        for as_of in _as_of_grid(market_start, end, step, mkt.resolves_at):
            candle = prices.latest_before(as_of)
            if candle is None:
                continue
            price = float(candle.close)
            p = rain_calibration.rain_probability(
                reader, spec, as_of, tz, min_years=min_years, memo=memo,
                history=histories[spec.station])
            if p is None:
                continue
            out.append((cluster, Sample(
                external_id=spec.external_id, market_type="rain:precip:greater",
                as_of=as_of,
                lead_h=(mkt.resolves_at - as_of).total_seconds() / 3600.0,
                price=price, p_forecast=p, y=mkt.resolved_y)))
    return out


def _brier(p: float, y: float) -> float:
    return (p - y) ** 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=_day, default=_day("2024-01-01"))
    ap.add_argument("--end", type=_day, default=_day("2026-07-01"))
    ap.add_argument("--step-hours", type=int, default=24)
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN)
    ap.add_argument("--min-years", type=int, default=5)
    ap.add_argument("--lookback-days", type=int, default=75)
    args = ap.parse_args(argv)

    conn = store.connect()
    markets = rain_calibration.load_rain_markets(conn)
    print(f"loaded {len(markets)} resolved rain market(s)")
    reader = StoreReader(conn)
    tagged = _collect(reader, markets, start=args.start, end=args.end,
                      step=timedelta(hours=args.step_hours),
                      min_years=args.min_years,
                      lookback=timedelta(days=args.lookback_days))
    conn.close()

    if not tagged:
        print("no scorable samples")
        return 1

    bp = [_brier(s.price, s.y) for _, s in tagged]
    bf = [_brier(s.p_forecast, s.y) for _, s in tagged]
    n = len(tagged)
    mean_bp, mean_bf = sum(bp) / n, sum(bf) / n
    skill = (mean_bp - mean_bf) / mean_bp if mean_bp > 0 else 0.0

    print(f"\nn_samples          {n}")
    print(f"brier(price)       {mean_bp:.5f}")
    print(f"brier(benchmark)   {mean_bf:.5f}")
    print(f"skill              {skill:+.4f}   (gate: >= {args.margin:+.2f})")

    # --- clustered test: one observation per station-month --------------
    per: dict[str, list[float]] = defaultdict(list)
    for (cluster, s) in tagged:
        per[cluster].append(_brier(s.price, s.y) - _brier(s.p_forecast, s.y))
    gaps = [sum(v) / len(v) for v in per.values()]
    k = len(gaps)
    mean_gap = sum(gaps) / k
    if k > 1:
        var = sum((g - mean_gap) ** 2 for g in gaps) / (k - 1)
        se = math.sqrt(var / k)
        t = mean_gap / se if se > 0 else float("nan")
    else:
        se, t = float("nan"), float("nan")

    print(f"\nn_clusters         {k}   (station-months)")
    print(f"mean cluster gap   {mean_gap:+.5f}   (brier_price - brier_benchmark)")
    print(f"se                 {se:.5f}")
    print(f"t                  {t:+.3f}")
    wins = sum(1 for g in gaps if g > 0)
    print(f"clusters won       {wins}/{k}")

    print("\nper-cluster gap (sorted):")
    for c, v in sorted(per.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print(f"  {c}  {sum(v)/len(v):+.5f}  n={len(v)}")

    verdict = "GO" if (skill >= args.margin and t > 2.0) else "NO-GO"
    print(f"\nVERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
