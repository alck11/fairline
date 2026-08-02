"""
rain_calibration.py — MRAIN-1's edge-room gate (ADR-0028 piece D).

Asks of monthly precipitation markets exactly what WP-7/ADR-0014 asked of
daily temperature markets: **does Kalshi's price already track what a naive
public-data benchmark knows, or is there room for a model to beat it?** GO
iff the benchmark's Brier score beats the price's by the pre-registered
margin. A NO-GO is a valid, capital-saving result — it was for temperature.

Why this is a separate module from `calibration.py` rather than a branch
inside it: the *benchmark* differs completely (a climatological
remaining-rain distribution, not a Gaussian on forecast error), while the
*scoring* is identical. So the scoring primitives are imported from
calibration and reused unchanged — `_as_of_grid`, `Sample`, `_aggregate`,
`CalibrationReport` — and only the probability model is new. Nothing in
calibration.py is modified, so WP-7's existing NO-GO cannot be disturbed by
this file.

The benchmark (see climatology.py for the statistics):

    total = accumulation_already_observed + residual_over_remaining_days
    P(YES) = P(residual > strike - accumulation_to_date)

Both terms are read strictly through the `< as_of` PIT readers, so at every
decision instant the benchmark sees only what was knowable then.

Two resolution facts, verified live in ADR-0028 rather than assumed, that
this parsing depends on:
  * every KXRAIN*M market phrases its strike as "strictly greater than N
    inches" — so the comparison is `>`, never `>=`, and there are no
    between/less-than variants to handle (unlike temperature ladders).
  * Kalshi settles these on the NWS CLI site named in each series' rules,
    and IEM's daily `precip` for the mapped station reproduces that
    settlement on 20/20 checked station-months.

Demo: `python3 src/rain_calibration.py` runs the study over a synthetic
in-memory reader — no network, no Postgres.
"""
from __future__ import annotations
import bisect
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import climatology
import weather_ingest
from calibration import (CalibrationReport, DEFAULT_MARGIN, Sample, _aggregate,
                         _as_of_grid)
from prob_fn import Reader, StoreReader
from store import Connection

OBS_VARIABLE = climatology.PRECIP_VARIABLE

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
     "NOV", "DEC"], 1)}
_MONTH_NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


@dataclass(frozen=True)
class RainMarketSpec:
    """A monthly-precipitation market's resolution parameters.

    YES resolves when the month's total precipitation at `station` is
    **strictly** greater than `threshold_in` inches."""
    external_id: str
    station: str
    year: int
    month: int
    threshold_in: float

    def yes_outcome(self, observed_total: float) -> float:
        return 1.0 if observed_total > self.threshold_in else 0.0


def _series_prefix(external_id: str) -> str:
    return external_id.split("-", 1)[0]


def _station_for_series(series: str) -> str | None:
    """Kalshi renamed these series at some point: the archive carries both
    `KXRAINNYCM-25DEC-4` and the older `RAINNYCM-24FEB-6` for the same
    market family (confirmed live). Try the ticker as-is, then with the `KX`
    prefix restored, so pre-rename history is not silently dropped from the
    study population."""
    station = weather_ingest.SERIES_STATION.get(series)
    if station is not None:
        return station
    if not series.startswith("KX"):
        return weather_ingest.SERIES_STATION.get(f"KX{series}")
    return None


def _parse_year_month(external_id: str, resolution_text: str | None
                      ) -> tuple[int, int] | None:
    """(year, month) for the market's target month.

    Preferred source is the rules text, which names the month and a **full**
    year ("in Dec 2024"). The ticker only carries two digits, and a 2-digit
    year has to be guessed into a century; where both are available they are
    cross-checked, and a disagreement returns None (skip the market) rather
    than picking one — a wrong month would score the benchmark against a
    different month's rainfall entirely."""
    from_rules = None
    if resolution_text:
        m = re.search(r"\bin\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})\b", resolution_text)
        if m and m.group(1).lower() in _MONTH_NAMES:
            from_rules = (int(m.group(2)), _MONTH_NAMES[m.group(1).lower()])

    from_ticker = None
    for seg in external_id.split("-"):
        m = re.fullmatch(r"(\d{2})([A-Z]{3})", seg.upper())
        if m and m.group(2) in _MONTHS:
            from_ticker = (2000 + int(m.group(1)), _MONTHS[m.group(2)])
            break

    if from_rules and from_ticker and from_rules != from_ticker:
        return None
    return from_rules or from_ticker


def _parse_threshold(resolution_text: str | None) -> float | None:
    """The strike in inches, from the rules text (the resolution ground
    truth). Only the "strictly greater than N" phrasing is accepted: ADR-0028
    confirmed it is the only one these series use, so anything else is a
    market this parser does not understand and must skip rather than guess
    at — a mis-parsed strike silently corrupts every sample drawn from it
    (ADR-0012)."""
    if not resolution_text:
        return None
    m = re.search(r"strictly greater than\s+(\d+(?:\.\d+)?)\s*inch",
                  resolution_text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def parse_rain_market_spec(external_id: str, resolution_text: str | None
                           ) -> RainMarketSpec | None:
    """Reconstruct a RainMarketSpec, or None if the market cannot be placed
    with confidence. None always means "skip this market", never a guess."""
    station = _station_for_series(_series_prefix(external_id))
    if station is None:
        return None
    ym = _parse_year_month(external_id, resolution_text)
    if ym is None:
        return None
    threshold = _parse_threshold(resolution_text)
    if threshold is None:
        return None
    year, month = ym
    return RainMarketSpec(external_id, station, year, month, threshold)


@dataclass(frozen=True)
class RainMarket:
    spec: RainMarketSpec
    yes_token_id: str
    resolves_at: datetime
    resolved_y: float


class _StationHistory:
    """One station's precipitation history, fetched **once** and sliced by
    `as_of` in process.

    Why not just call the PIT reader per instant, as calibration.py does? The
    per-instant call re-reads the station's entire history from the database
    every time. WP-7's temperature study could afford that over a 68-day
    window; this one spans 17 years of daily rows across ~2,100 decision
    instants, which is ~13 million rows over the wire — the study ran for ten
    minutes using 36 seconds of CPU, i.e. almost entirely waiting on the
    network, and is the same data-transfer wall ADR-0012 hit.

    **This does not loosen the point-in-time boundary.** `daily_before`
    applies exactly the predicate the reader's SQL applies — `observed_at <
    as_of`, strict — via a bisect on the sorted timestamps. The rows are
    fetched once with a horizon at or past the study end and then *filtered
    down* per instant; no caller can see a row whose `observed_at` is at or
    after its `as_of`. The one real obligation this shifts onto us is that
    the predicate lives here rather than in store.py, so it is pinned by its
    own test (`test_station_history_slice_matches_reader`)."""

    __slots__ = ("_times", "_entries")

    def __init__(self, reader: Reader, station: str, tz: ZoneInfo,
                 horizon: datetime):
        rows = reader.observations_before(station, OBS_VARIABLE, horizon)
        entries = sorted(
            ((o.observed_at,
              climatology._obs_local_date(o.observed_at, tz),
              float(o.value))
             for o in rows),
            key=lambda t: t[0])
        self._times = [t[0] for t in entries]
        self._entries = entries

    def daily_before(self, as_of: datetime) -> dict[date, float]:
        """{local date: inches} for every observation strictly before `as_of`."""
        # bisect_left gives the first index whose timestamp is >= as_of, so the
        # prefix before it is exactly the rows with observed_at < as_of.
        i = bisect.bisect_left(self._times, as_of)
        return {d: v for _, d, v in self._entries[:i]}


class _DailyMemo:
    """Per-run cache of the two *derived* quantities a rain probability needs:
    how much has accumulated in the target month so far, and the prior-year
    residual totals to compare against.

    Keyed on (station, as_of, year, month) — the complete input set for both,
    with the market's own threshold deliberately excluded, because every
    strike in a month's ladder shares this work and differs only in the final
    comparison. So a 13-strike December ladder computes it once, not 13 times.

    Caching the derived numbers rather than the intermediate {date: inches}
    dict is the point. A first version cached the dict and grew past 1.2GB
    before finishing: ~2,100 distinct (station, as_of) keys each holding a
    ~6,000-entry dict. These two values are a float and a list of ~16 floats,
    so the same coverage costs kilobytes. Same lesson as ADR-0012 (whole-
    history rescans are structural here), one level further in: memoize what
    the caller actually consumes, not what happened to be expensive to
    build."""
    __slots__ = ("state",)

    def __init__(self) -> None:
        self.state: dict[tuple, tuple[float, list[float]] | None] = {}


def rain_probability(reader: Reader, spec: RainMarketSpec, as_of: datetime,
                     tz: ZoneInfo, *,
                     min_years: int = climatology.DEFAULT_MIN_YEARS,
                     memo: "_DailyMemo | None" = None,
                     history: "_StationHistory | None" = None) -> float | None:
    """P(YES) for one market at one decision instant, or None when the
    benchmark cannot honestly answer (too little station history, or no
    remaining-days window left).

    Everything here flows from `observations_before(..., as_of)`, so the
    accumulation and the climatology are both restricted to what was
    knowable at `as_of` — and `residual_samples` additionally drops the
    market's own year from its climatology."""
    state = _month_state(reader, spec.station, spec.year, spec.month, as_of, tz,
                         memo=memo, history=history)
    if state is None:
        return None
    accumulated, residual_totals = state
    if len(residual_totals) < min_years:
        return None
    return climatology.prob_exceeds(residual_totals,
                                    spec.threshold_in - accumulated)


def _month_state(reader: Reader, station: str, year: int, month: int,
                 as_of: datetime, tz: ZoneInfo, *,
                 memo: "_DailyMemo | None" = None,
                 history: "_StationHistory | None" = None
                 ) -> tuple[float, list[float]] | None:
    """(accumulated inches so far, prior-year residual totals) for one
    station-month at one instant, or None if there is no usable history or no
    remaining-days window. Everything every strike in that month's ladder
    shares — hence the memo key excluding the threshold.

    `history`, when supplied, serves the same `observed_at < as_of` slice from
    a single up-front fetch instead of one database round trip per instant;
    without it this falls back to the reader directly, which is what the
    unit tests exercise."""
    key = (station, as_of, year, month)
    if memo is not None and key in memo.state:
        return memo.state[key]

    if history is not None:
        daily = history.daily_before(as_of)
    else:
        observations = reader.observations_before(station, OBS_VARIABLE, as_of)
        daily = climatology.collect_daily_precip(observations, tz)
    out: tuple[float, list[float]] | None
    if not daily:
        out = None
    else:
        # How far into the target month is knowable at `as_of`?
        #
        # Derived from the data rather than recomputed from the clock: the
        # reader has already applied the `< as_of` cut, so the target-month
        # days present in `daily` are exactly the days knowable at `as_of`, by
        # construction. Re-deriving this from timezone arithmetic (which local
        # midnight has passed, across DST, across month ends) would be a second
        # implementation of the same boundary that could silently disagree with
        # the first — and disagreeing permissively would be lookahead.
        present = [d.day for d in daily if d.year == year and d.month == month]
        as_of_day = max(present) if present else 0
        accumulated, _ = climatology.accumulation_to_date(
            daily, year=year, month=month, through_day=as_of_day)
        samples = climatology.residual_samples(
            daily, target_year=year, month=month, from_day=as_of_day + 1)
        out = (accumulated, [s.total for s in samples])

    if memo is not None:
        memo.state[key] = out
    return out


def evaluate(reader: Reader, markets: list[RainMarket], *, start: datetime,
             end: datetime, step: timedelta, category: str = "rain",
             margin: float = DEFAULT_MARGIN,
             min_years: int = climatology.DEFAULT_MIN_YEARS,
             lookback: timedelta = timedelta(days=75)) -> CalibrationReport:
    """Score price vs the climatological benchmark over a real or synthetic
    reader. Reader-based, mirroring calibration.evaluate, so the whole study
    is testable with no database.

    `lookback` caps how far before its own resolution each market is sampled.
    Without it every market is walked from the global `start`, so a market
    resolving in 2026 is probed across two years of instants at which it did
    not yet exist — thousands of candle queries per market that can only
    return nothing. 75 days comfortably covers these markets' real lifetime
    (listed roughly two months before their month ends) while removing the
    dead prefix. It cannot bias the result: the instants it drops are ones
    with no price to score against."""
    # Deliberately NOT wrapped in calibration._MemoReader. That wrapper caches
    # whole raw row-lists per (station, variable, as_of), which is the right
    # trade for WP-7's 68-day temperature window but not here: 17 years of
    # daily history times ~2,100 distinct instants is millions of retained row
    # objects, and it drove this study past 1.4GB without finishing. `memo`
    # below already collapses the same repeated reads one level further in, on
    # the derived numbers, so the wrapper would add memory and no saved I/O.
    memo = _DailyMemo()
    # One history fetch per station for the whole study (see _StationHistory
    # for why, and for why this does not weaken the PIT boundary). The horizon
    # is the study end, so no row past the window is ever loaded at all.
    histories: dict[str, _StationHistory] = {}
    for mkt in markets:
        st = mkt.spec.station
        if st not in histories:
            histories[st] = _StationHistory(
                reader, st, ZoneInfo(weather_ingest.STATIONS[st].tz), end)

    samples: list[Sample] = []
    studied = 0
    for mkt in markets:
        spec = mkt.spec
        tz = ZoneInfo(weather_ingest.STATIONS[spec.station].tz)
        market_type = f"{category}:precip:greater"
        used = False
        market_start = max(start, mkt.resolves_at - lookback)
        for as_of in _as_of_grid(market_start, end, step, mkt.resolves_at):
            candles = reader.candles_before(mkt.yes_token_id, as_of)
            if not candles:
                continue
            price = max(candles, key=lambda c: c.ts).close
            p_forecast = rain_probability(reader, spec, as_of, tz,
                                          min_years=min_years, memo=memo,
                                          history=histories[spec.station])
            if p_forecast is None:
                continue
            samples.append(Sample(
                external_id=spec.external_id, market_type=market_type,
                as_of=as_of,
                lead_h=(mkt.resolves_at - as_of).total_seconds() / 3600.0,
                price=float(price), p_forecast=p_forecast, y=mkt.resolved_y))
            used = True
        studied += 1 if used else 0

    results = _aggregate(samples, margin)
    overall = "GO" if any(r.verdict == "GO" for r in results) else "NO-GO"
    return CalibrationReport(category=category, margin=margin,
                             n_markets=studied, n_samples=len(samples),
                             results=results, overall_verdict=overall)


def load_rain_markets(conn: Connection, category: str = "weather"
                      ) -> list[RainMarket]:
    """Resolved rain markets whose spec parses and whose YES outcome has a
    settled value. Mirrors calibration.load_weather_markets; the RAIN filter
    is on the ticker, since both the `KXRAIN*` and legacy `RAIN*` prefixes
    exist in the archive."""
    rows = conn.execute(
        """
        SELECT m.external_id, m.resolution_text, m.resolves_at,
               o.resolved_value, ot.token_id
        FROM market m
        JOIN outcome o        ON o.market_id  = m.market_id
        JOIN outcome_token ot ON ot.outcome_id = o.outcome_id
        WHERE m.venue = 'kalshi' AND m.category = %s
          AND m.resolved = true AND o.idx = 0 AND o.resolved_value IS NOT NULL
          AND m.external_id LIKE '%%RAIN%%'
        ORDER BY m.external_id
        """,
        (category,),
    ).fetchall()
    out: list[RainMarket] = []
    for external_id, rules, resolves_at, resolved_value, token_id in rows:
        spec = parse_rain_market_spec(external_id, rules)
        if spec is None or resolves_at is None:
            continue
        out.append(RainMarket(spec=spec, yes_token_id=token_id,
                              resolves_at=resolves_at,
                              resolved_y=float(resolved_value)))
    return out


def run_study(conn: Connection, *, category: str = "weather",
              start: datetime, end: datetime, step: timedelta,
              margin: float = DEFAULT_MARGIN,
              min_years: int = climatology.DEFAULT_MIN_YEARS
              ) -> CalibrationReport:
    markets = load_rain_markets(conn, category)
    reader = StoreReader(conn)
    return evaluate(reader, markets, start=start, end=end, step=step,
                    margin=margin, min_years=min_years)


if __name__ == "__main__":
    from datetime import timezone
    from store import Candle, WeatherObservationRow

    tz = ZoneInfo("America/New_York")

    def obs_at(d):
        nd = d + timedelta(days=1)
        return datetime(nd.year, nd.month, nd.day, tzinfo=tz).astimezone(timezone.utc)

    # 12 prior Decembers of steady rain, then a wet Dec 2025 under study.
    observations = []
    for year in range(2013, 2025):
        for day in range(1, 32):
            observations.append(WeatherObservationRow(
                obs_at(date(year, 12, day)), "KNYC", "precip", 0.12, "iem-asos"))
    for day in range(1, 32):
        observations.append(WeatherObservationRow(
            obs_at(date(2025, 12, day)), "KNYC", "precip", 0.20, "iem-asos"))

    resolves = datetime(2026, 1, 1, 5, tzinfo=timezone.utc)
    candles = [Candle(datetime(2025, 12, d, tzinfo=timezone.utc), "RAIN-YES",
                      0.5, 0.5, 0.5, 0.5, 10.0) for d in (5, 10, 15, 20, 25)]

    class _FakeReader:
        def candles_before(self, token_id, as_of):
            return [c for c in candles if c.token_id == token_id and c.ts < as_of]

        def forecasts_before(self, station, variable, as_of):
            return []

        def observations_before(self, station, variable, as_of):
            return [o for o in observations if o.station == station
                    and o.variable == variable and o.observed_at < as_of]

    # Dec 2025 totals 6.2in; a 4-inch strike resolves YES.
    spec = RainMarketSpec("KXRAINNYCM-25DEC-4", "KNYC", 2025, 12, 4.0)
    market = RainMarket(spec, "RAIN-YES", resolves, resolved_y=1.0)
    report = evaluate(_FakeReader(), [market],
                      start=datetime(2025, 12, 1, tzinfo=timezone.utc),
                      end=resolves, step=timedelta(days=5))
    print(report.format())
