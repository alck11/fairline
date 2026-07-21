"""
calibration.py — the edge-room GO/NO-GO study (WP-7, B2, US-4 study).

The one question this answers, per market type: **does Kalshi's weather price
already track the public forecast, or is there room for a forecast-based model to
beat it?** It is the GO/NO-GO gate for WP-8 — a NO-GO is a valid, capital-saving
outcome that stops Track B before the expensive model build (plan.md WP-7).

Method (all point-in-time honest, via prob_fn.Reader's `< as_of` readers):

  1. For each resolved Kalshi weather market, reconstruct its resolution spec —
     (station, variable, target_date, strike_type, lo/hi) — from stored fields.
     `market.resolution_text` (the Kalshi rules) is unambiguous ground truth
     ("... is less than 80°" / "... is between 80-81°"); the ticker carries the
     date; `weather_ingest.SERIES_STATION` maps the series to a station. Nothing
     is stored structurally for this yet (backtest.py sets MarketRef.params={},
     "WP-8's concern"), so WP-7 parses it — without touching Track A (WP-7
     boundary).
  2. Build a **naive, non-trained** forecast->probability benchmark (NOT WP-8's
     model): the forecast daily-high for the target date (max of hourly `tmpf`
     from the latest MOS cycle strictly before `as_of`), mapped through a Gaussian
     whose error mean/σ come from the station's PIT forecast-vs-observation history
     (only pairs knowable before `as_of`). P(YES) follows from the strike.
  3. At each `as_of` step before resolution, sample the market price (last candle
     `< as_of`), this `p_forecast`, and the realized label `y` (the market's
     settled `resolved_value`).
  4. Per market type, score Brier(price) vs Brier(forecast). **Edge room exists
     iff the naive forecast is more ACCURATE than the price** — GO if the relative
     Brier skill `(brier_price - brier_forecast)/brier_price` meets a
     pre-registered margin (default 0.05), else NO-GO. Fee-free by design: this
     measures edge *room*, not net profitability (that is the WP-4/WP-5 backtest's
     job).

Boundaries (WP-7): does NOT build the predictive model (WP-8) — the Gaussian error
transform is a deliberately naive benchmark, a lower bound on edge room, not a
model. Does NOT gate Track A. Reads only stored tables through the PIT readers.

Demo: `python3 src/calibration.py` runs the study over a synthetic in-memory
Reader (no network, no Postgres), printing a per-type GO/NO-GO report.
"""
from __future__ import annotations
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from prob_fn import Reader, StoreReader
from store import Connection
import weather_ingest

# The variable a high-temp market resolves on. WP-6 stores forecasts as hourly
# `tmpf` and observations as daily `tmax`; the study derives a forecast daily-high
# from the hourly rows (see _forecast_high).
FORECAST_VARIABLE = "tmpf"
OBS_VARIABLE = "tmax"

DEFAULT_MARGIN = 0.05          # pre-registered relative-Brier-skill GO threshold
DEFAULT_MIN_ERROR_PAIRS = 10   # min forecast/obs pairs to estimate σ honestly

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
     "NOV", "DEC"], 1)}


# ---------------------------------------------------------------------------
# market-spec parsing — from stored ticker + rules (ground truth)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WeatherMarketSpec:
    """A weather market's resolution parameters, reconstructed from stored text.

    strike_type ∈ {'less','greater','between'}. YES resolves when the observed
    daily high `x` satisfies: less -> x < hi ; greater -> x > lo ; between ->
    lo <= x <= hi. (`lo`/`hi` are the strike bounds in °F; the unused side is
    None for less/greater.)"""
    external_id: str
    station: str
    variable: str
    target_date: date
    strike_type: str
    lo: float | None
    hi: float | None

    def yes_outcome(self, observed_high: float) -> float:
        """The realized YES label for an observed daily high (1.0/0.0). Used only
        to sanity-check against the market's settled resolved_value."""
        if self.strike_type == "less":
            return 1.0 if observed_high < self.hi else 0.0
        if self.strike_type == "greater":
            return 1.0 if observed_high > self.lo else 0.0
        return 1.0 if self.lo <= observed_high <= self.hi else 0.0


def _parse_target_date(external_id: str) -> date | None:
    """The target date from a Kalshi ticker's date segment, e.g.
    'KXHIGHNY-26JUL19-T80' -> 2026-07-19. Returns None if no YYMMMDD segment is
    present (not a dated weather market this study can place in time)."""
    for seg in external_id.split("-"):
        m = re.fullmatch(r"(\d{2})([A-Z]{3})(\d{2})", seg.upper())
        if m and m.group(2) in _MONTHS:
            yy, mon, dd = m.groups()
            try:
                return date(2000 + int(yy), _MONTHS[mon], int(dd))
            except ValueError:
                return None
    return None


def _parse_strike(rules: str) -> tuple[str, float | None, float | None] | None:
    """(strike_type, lo, hi) from the Kalshi `rules_primary` text — the resolution
    ground truth. Returns None if no recognized strike phrasing is found (skip the
    market rather than guess)."""
    r = rules.lower()
    m = re.search(r"between\s+(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)", r)
    if m:
        return "between", float(m.group(1)), float(m.group(2))
    m = re.search(r"less than\s+(\d+(?:\.\d+)?)", r)
    if m:
        return "less", None, float(m.group(1))
    m = re.search(r"(?:greater than|above)\s+(\d+(?:\.\d+)?)", r)
    if m:
        return "greater", float(m.group(1)), None
    return None


def parse_weather_market_spec(external_id: str, resolution_text: str | None
                              ) -> WeatherMarketSpec | None:
    """Reconstruct a WeatherMarketSpec from a stored market, or None if it can't be
    placed (unmapped station, no date segment, unparseable rules). None means
    "skip this market", never a guess — a mis-parsed threshold would silently
    corrupt the whole study."""
    series = external_id.split("-", 1)[0]
    station = weather_ingest.SERIES_STATION.get(series)
    if station is None:
        return None
    target_date = _parse_target_date(external_id)
    if target_date is None or not resolution_text:
        return None
    strike = _parse_strike(resolution_text)
    if strike is None:
        return None
    strike_type, lo, hi = strike
    # variable is the market's resolution variable (daily high = tmax); the
    # forecast side derives a daily high from hourly `tmpf` (see _forecast_high).
    return WeatherMarketSpec(external_id, station, OBS_VARIABLE, target_date,
                             strike_type, lo, hi)


# ---------------------------------------------------------------------------
# the naive forecast -> probability benchmark (non-trained; not WP-8's model)
# ---------------------------------------------------------------------------
def _norm_cdf(z: float) -> float:
    """Standard normal CDF Φ via stdlib math.erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _local_date(dt: datetime, tz: ZoneInfo) -> date:
    return dt.astimezone(tz).date()


def _forecast_high(reader: Reader, station: str, target_date: date,
                   as_of: datetime, tz: ZoneInfo) -> float | None:
    """The forecast daily high for `target_date` knowable at `as_of`: from the
    LATEST MOS cycle issued strictly before `as_of`, the max of its hourly `tmpf`
    rows valid on the target date. None if no such forecast exists."""
    rows = [r for r in reader.forecasts_before(station, FORECAST_VARIABLE, as_of)
            if _local_date(r.valid_at, tz) == target_date]
    if not rows:
        return None
    latest_cycle = max(r.issued_at for r in rows)
    return max(r.value for r in rows if r.issued_at == latest_cycle)


def _error_stats(reader: Reader, station: str, as_of: datetime, tz: ZoneInfo,
                 min_pairs: int, exclude_date: date | None = None
                 ) -> tuple[float, float] | None:
    """(bias, σ) of the forecast daily-high error (observed − forecast) from the
    station's history knowable strictly before `as_of` — the spread the naive
    Gaussian benchmark needs. Fully PIT: both the observations and the forecasts
    it pairs them with come from the `< as_of` readers.

    `exclude_date` drops the pair for the market currently being priced. Without
    it, once `as_of` sits in the window [observed_at(target_date), resolves_at),
    that market's own realized outcome — already `< as_of` under WP-6's
    end-of-local-day `observed_at` convention — would leak into the very Gaussian
    used to generate its `p_forecast`, i.e. the benchmark would peek at the
    quantity it is predicting (reviewer BLOCKER, 2026-07-21). It is the *only*
    date that can leak: any later date's observation is not yet knowable at
    `as_of`. A fair benchmark must never use the object under study, so `evaluate`
    always passes the market's `target_date` here.

    None if fewer than `max(2, min_pairs)` usable pairs (need ≥2 for a sample
    variance) or zero variance."""
    residuals: list[float] = []
    for obs in reader.observations_before(station, OBS_VARIABLE, as_of):
        # WP-6 stores observed_at as the start of the NEXT local day, so the
        # observed calendar date is one local day earlier.
        obs_date = (obs.observed_at.astimezone(tz) - timedelta(days=1)).date()
        if obs_date == exclude_date:
            continue
        f = _forecast_high(reader, station, obs_date, as_of, tz)
        if f is not None:
            residuals.append(obs.value - f)
    n = len(residuals)
    if n < min_pairs or n < 2:      # n < 2 also guards the (n-1) sample variance
        return None
    bias = sum(residuals) / n
    var = sum((r - bias) ** 2 for r in residuals) / (n - 1)
    if var <= 0.0:
        return None
    return bias, math.sqrt(var)


def _forecast_prob(spec: WeatherMarketSpec, mu: float, sigma: float) -> float:
    """P(YES) under high ~ Normal(mu, sigma) for the market's strike, clamped to
    [0,1]."""
    if spec.strike_type == "less":       # x < hi
        p = _norm_cdf((spec.hi - mu) / sigma)
    elif spec.strike_type == "greater":  # x > lo
        p = 1.0 - _norm_cdf((spec.lo - mu) / sigma)
    else:                                # lo <= x <= hi
        p = _norm_cdf((spec.hi - mu) / sigma) - _norm_cdf((spec.lo - mu) / sigma)
    return min(1.0, max(0.0, p))


# ---------------------------------------------------------------------------
# study data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WeatherMarket:
    """A resolved market to study: its spec, the YES-side token, and the settled
    label. `resolved_y` is the market's `resolved_value` (Kalshi settlement) —
    the study's ground-truth outcome."""
    spec: WeatherMarketSpec
    yes_token_id: str
    resolves_at: datetime
    resolved_y: float


@dataclass(frozen=True)
class Sample:
    external_id: str
    market_type: str
    as_of: datetime
    lead_h: float
    price: float
    p_forecast: float
    y: float


@dataclass(frozen=True)
class TypeResult:
    market_type: str
    n: int
    brier_price: float
    brier_forecast: float
    skill: float          # (brier_price - brier_forecast) / brier_price
    mean_gap: float       # mean |price - p_forecast|
    mean_lead_h: float
    verdict: str          # 'GO' | 'NO-GO'


@dataclass(frozen=True)
class CalibrationReport:
    category: str
    margin: float
    n_markets: int
    n_samples: int
    results: list[TypeResult]
    overall_verdict: str

    def format(self) -> str:
        lines = [
            f"Calibration study — category={self.category}  "
            f"(GO margin = {self.margin:.0%} relative Brier skill)",
            f"markets studied: {self.n_markets}   samples: {self.n_samples}",
            "",
            f"  {'market type':<22} {'n':>5} {'Brier(px)':>10} "
            f"{'Brier(fc)':>10} {'skill':>8} {'gap':>7}  verdict",
            "  " + "-" * 74,
        ]
        for r in self.results:
            lines.append(
                f"  {r.market_type:<22} {r.n:>5} {r.brier_price:>10.4f} "
                f"{r.brier_forecast:>10.4f} {r.skill:>8.1%} {r.mean_gap:>7.3f}  "
                f"{r.verdict}")
        lines += ["", f"OVERALL: {self.overall_verdict}"]
        if self.overall_verdict == "NO-GO":
            lines.append("  -> no exploitable edge room found; Track B stops "
                         "here (do not build WP-8). A valid, capital-saving result.")
        else:
            go_types = [r.market_type for r in self.results if r.verdict == "GO"]
            lines.append(f"  -> edge room on: {', '.join(go_types)} — WP-8 is "
                         f"justified for those type(s).")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# the study
# ---------------------------------------------------------------------------
def _as_of_grid(start: datetime, end: datetime, step: timedelta,
                resolves_at: datetime) -> list[datetime]:
    """Decision instants for one market: every `step` in [start, end] strictly
    before its resolution (no post-resolution lookahead)."""
    if step <= timedelta(0):
        # A non-positive step never advances `t`, so the loop below would spin
        # forever / grow an unbounded list (reviewer MAJOR, 2026-07-21). Fail
        # fast here so a direct evaluate() caller with a bad step gets a clear
        # error, not a hang — the CLI validates this too, before we reach here.
        raise ValueError(f"step must be positive, got {step!r}")
    out, t = [], start
    horizon = min(end, resolves_at)
    while t < horizon:
        out.append(t)
        t += step
    return out


def evaluate(reader: Reader, markets: list[WeatherMarket], *,
             start: datetime, end: datetime, step: timedelta,
             category: str = "weather", margin: float = DEFAULT_MARGIN,
             min_error_pairs: int = DEFAULT_MIN_ERROR_PAIRS) -> CalibrationReport:
    """The pure study core: score price vs the naive forecast benchmark over a
    fake or real `reader`. Kept reader-based (not conn-based) so it is testable
    with a synthetic in-memory Reader, exactly like prob_fn."""
    samples: list[Sample] = []
    studied = 0
    for mkt in markets:
        spec = mkt.spec
        tz = ZoneInfo(weather_ingest.STATIONS[spec.station].tz)
        market_type = f"{category}:{spec.variable}:{spec.strike_type}"
        used = False
        for as_of in _as_of_grid(start, end, step, mkt.resolves_at):
            candles = reader.candles_before(mkt.yes_token_id, as_of)
            if not candles:
                continue
            price = max(candles, key=lambda c: c.ts).close
            f_hat = _forecast_high(reader, spec.station, spec.target_date, as_of, tz)
            if f_hat is None:
                continue
            stats = _error_stats(reader, spec.station, as_of, tz, min_error_pairs,
                                 exclude_date=spec.target_date)
            if stats is None:
                continue
            bias, sigma = stats
            p_forecast = _forecast_prob(spec, f_hat + bias, sigma)
            samples.append(Sample(
                external_id=spec.external_id, market_type=market_type, as_of=as_of,
                lead_h=(mkt.resolves_at - as_of).total_seconds() / 3600.0,
                price=float(price), p_forecast=p_forecast, y=mkt.resolved_y))
            used = True
        studied += 1 if used else 0

    results = _aggregate(samples, margin)
    overall = "GO" if any(r.verdict == "GO" for r in results) else "NO-GO"
    return CalibrationReport(category=category, margin=margin, n_markets=studied,
                             n_samples=len(samples), results=results,
                             overall_verdict=overall)


def _aggregate(samples: list[Sample], margin: float) -> list[TypeResult]:
    by_type: dict[str, list[Sample]] = {}
    for s in samples:
        by_type.setdefault(s.market_type, []).append(s)
    results: list[TypeResult] = []
    for market_type, group in sorted(by_type.items()):
        n = len(group)
        bp = sum((s.price - s.y) ** 2 for s in group) / n
        bf = sum((s.p_forecast - s.y) ** 2 for s in group) / n
        skill = (bp - bf) / bp if bp > 0 else 0.0
        gap = sum(abs(s.price - s.p_forecast) for s in group) / n
        lead = sum(s.lead_h for s in group) / n
        verdict = "GO" if skill >= margin else "NO-GO"
        results.append(TypeResult(market_type, n, bp, bf, skill, gap, lead, verdict))
    return results


def load_weather_markets(conn: Connection, category: str = "weather"
                         ) -> list[WeatherMarket]:
    """Resolved markets in (kalshi, category) whose spec parses and whose YES
    outcome has a settled `resolved_value`. The YES side is outcome idx 0
    (KalshiSource emits YES first — see ingest_kalshi._parse_market)."""
    rows = conn.execute(
        """
        SELECT m.external_id, m.resolution_text, m.resolves_at,
               o.resolved_value, ot.token_id
        FROM market m
        JOIN outcome o        ON o.market_id  = m.market_id
        JOIN outcome_token ot ON ot.outcome_id = o.outcome_id
        WHERE m.venue = 'kalshi' AND m.category = %s
          AND m.resolved = true AND o.idx = 0 AND o.resolved_value IS NOT NULL
        ORDER BY m.external_id
        """,
        (category,),
    ).fetchall()
    out: list[WeatherMarket] = []
    for external_id, rules, resolves_at, resolved_value, token_id in rows:
        spec = parse_weather_market_spec(external_id, rules)
        if spec is None or resolves_at is None:
            continue
        out.append(WeatherMarket(spec=spec, yes_token_id=token_id,
                                 resolves_at=resolves_at,
                                 resolved_y=float(resolved_value)))
    return out


def run_study(conn: Connection, *, category: str = "weather",
              start: datetime, end: datetime, step: timedelta,
              margin: float = DEFAULT_MARGIN,
              min_error_pairs: int = DEFAULT_MIN_ERROR_PAIRS) -> CalibrationReport:
    """Production entry (plan.md WP-7 signature): load resolved weather markets
    from the store, then run the PIT study through a StoreReader over [start, end]
    stepping by `step`."""
    markets = load_weather_markets(conn, category)
    reader = StoreReader(conn)
    return evaluate(reader, markets, start=start, end=end, step=step,
                    category=category, margin=margin,
                    min_error_pairs=min_error_pairs)


if __name__ == "__main__":
    from datetime import timezone
    from store import Candle, WeatherForecastRow, WeatherObservationRow

    tz = ZoneInfo("America/New_York")

    class _FakeReader:
        def __init__(self, candles, forecasts, observations):
            self._c, self._f, self._o = candles, forecasts, observations

        def candles_before(self, token_id, as_of):
            return [c for c in self._c if c.token_id == token_id and c.ts < as_of]

        def forecasts_before(self, station, variable, as_of):
            return [f for f in self._f if f.station == station
                    and f.variable == variable and f.issued_at < as_of]

        def observations_before(self, station, variable, as_of):
            return [o for o in self._o if o.station == station
                    and o.variable == variable and o.observed_at < as_of]

    def obs_at(d):  # end-of-local-day instant WP-6 uses
        nd = d + timedelta(days=1)
        return datetime(nd.year, nd.month, nd.day, tzinfo=tz).astimezone(timezone.utc)

    # 20 past days of history: forecast high ~ truth (good forecast), plus one
    # target market whose price is stale (0.50) while the forecast nails it.
    forecasts, observations = [], []
    base = date(2026, 6, 1)
    for i in range(20):
        d = base + timedelta(days=i)
        forecast = 70 + (i % 10)
        truth = forecast + ((i % 3) - 1)   # small ±1°F forecast error -> σ > 0
        issued = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=1)
        valid = datetime(d.year, d.month, d.day, 18, tzinfo=timezone.utc)
        forecasts.append(WeatherForecastRow(issued, valid, "KNYC", "tmpf",
                                            float(forecast), "iem-mos-nbs", 24.0))
        observations.append(WeatherObservationRow(obs_at(d), "KNYC", "tmax",
                                                  float(truth), "iem-asos"))
    target = date(2026, 6, 22)
    resolves = datetime(2026, 6, 23, 4, tzinfo=timezone.utc)
    # forecast says 85 (>80 -> YES near-certain); market price stuck at 0.5
    for hh in (6, 12):
        issued = datetime(2026, 6, 21, hh, tzinfo=timezone.utc)
        valid = datetime(2026, 6, 22, 18, tzinfo=timezone.utc)
        forecasts.append(WeatherForecastRow(issued, valid, "KNYC", "tmpf", 85.0,
                                            "iem-mos-nbs", 24.0))
    candles = [Candle(datetime(2026, 6, 22, 0, tzinfo=timezone.utc), "KX-YES",
                      0.5, 0.5, 0.5, 0.5, 100.0)]
    weather_ingest.SERIES_STATION.setdefault("KXDEMO", "KNYC")
    spec = WeatherMarketSpec("KXDEMO-26JUN22-T80", "KNYC", "tmax", target,
                             "greater", 80.0, None)
    market = WeatherMarket(spec, "KX-YES", resolves, resolved_y=1.0)

    report = evaluate(_FakeReader(candles, forecasts, observations), [market],
                      start=datetime(2026, 6, 22, tzinfo=timezone.utc),
                      end=resolves, step=timedelta(hours=6))
    print(report.format())
