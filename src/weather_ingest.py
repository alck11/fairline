"""
weather_ingest.py — NOAA/NWS forecast + observation history via the Iowa
Environmental Mesonet (IEM) point API (WP-6, B1, US-4 data).

ADR-0011: the free `api.weather.gov` serves no historical *forecast* archive
(current forecast only), so WP-6 sources its `issued_at`-keyed forecast history
from IEM's point API instead — MOS model guidance for forecasts, ASOS daily
summaries for observations — all public/free/no-auth JSON. The authoritative
gridded NCEI NDFD archive is deferred to post-GO (it needs GRIB/eccodes and grid
point-extraction; overkill before the WP-7 kill gate decides the weather track is
worth it). This module mirrors `ingest_kalshi.KalshiSource`'s shape: an HTTP
`_get` transport with retry/backoff, a typed `WeatherAPIError`, graceful
degradation, and fixture-based network-free tests (tests/test_weather_ingest.py).

Two IEM endpoints (shapes confirmed live 2026-07-20 against
https://mesonet.agron.iastate.edu/api/1):

    GET /mos.json?station=<ICAO>&model=<MOS>   -> forecasts()
        Rows carry `runtime_utc` (the model CYCLE time = the true publication
        instant -> weather_forecast.issued_at, never back-filled from valid_at,
        WP-6 boundary), `ftime_utc` (the VALID time -> valid_at), and `tmp`
        (forecast temperature, degrees F). `ftime_utc > runtime_utc` on every
        forecast row, so issued_at < valid_at holds by construction; this module
        enforces it anyway and fails loud if a response ever violates it.
    GET /daily.json?network=<NET>&station=<ID>&year=&month=  -> observations()
        Rows carry `date` (local calendar day), `max_tmpf`, `min_tmpf` — the
        daily extremes Kalshi high/low-temp markets resolve against, the realized
        truth for weather_observation.

Station addressing (ADR-0011). MOS keys stations by ICAO (`KNYC`); the daily/ASOS
feed keys them by an IEM network + short id (`NY_ASOS` / `NYC`). Both feeds are
normalized to a single CANONICAL ICAO key so store.py's PIT readers — which filter
on an exact `station` string — join forecasts to observations. `STATIONS` is the
curated registry (icao -> network, daily-id, IANA tz); the Kalshi series -> station
mapping is curated per series, not parsed from tickers (MVP simplification).

`source` is namespaced (`iem-mos-<model>` for forecasts, `iem-asos` for
observations) and is part of weather_forecast's upsert key, so a later NDFD ingest
coexists with the IEM rows without collision.

Demo: `python3 src/weather_ingest.py` fetches a few live MOS forecasts and daily
observations for KNYC against the real public API (network required; no auth).
"""
from __future__ import annotations
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

from store import WeatherForecastRow, WeatherObservationRow

DEFAULT_BASE_URL = "https://mesonet.agron.iastate.edu/api/1"

# Default MOS model: NBS = the National Blend of Models (NBM) short-range MOS,
# IEM's most broadly-available point guidance for US ASOS sites.
DEFAULT_MOS_MODEL = "NBS"

# Forecast temperature is stored under this variable name (raw hourly MOS `tmp`,
# degrees F). Daily-extreme *forecast* derivation (max over a valid-day's hourly
# rows, or MOS `n_x` with day/night classification) is a WP-7/WP-8 concern reading
# these PIT rows — deliberately not done here (WP-6 = acquire data, not model).
FORECAST_VARIABLE = "tmpf"

# Observation variables: the unambiguous daily extremes the daily endpoint gives
# directly (Kalshi high/low-temp markets resolve against these).
OBS_TMAX = "tmax"
OBS_TMIN = "tmin"

# A sane physical bound for US surface air temperature in degrees F; anything
# outside is treated as a malformed response and fails loud (matching
# KalshiSource's fail-on-malformed-field ethos) rather than silently storing
# garbage the calibration study would then trust.
_TEMP_F_MIN, _TEMP_F_MAX = -80.0, 140.0


@dataclass(frozen=True)
class WeatherStation:
    """Canonical station + how each IEM feed addresses it.

    `icao` is the single canonical key written to weather_forecast.station /
    weather_observation.station (so the PIT readers join the two). `iem_network`
    + `iem_daily_station` address the daily/ASOS feed; MOS uses `icao` directly.
    `tz` (IANA) makes observation `observed_at` the true end-of-local-day instant.
    """
    icao: str
    iem_network: str
    iem_daily_station: str
    tz: str


# Curated station registry. KNYC is live-verified (2026-07-20); the rest follow
# IEM's documented `<STATE>_ASOS` network + 3-letter-id convention and should be
# spot-checked against IEM before a production backfill. IANA tz per station makes
# observation PIT keys exact.
STATIONS: dict[str, WeatherStation] = {
    "KNYC": WeatherStation("KNYC", "NY_ASOS", "NYC", "America/New_York"),
    "KLAX": WeatherStation("KLAX", "CA_ASOS", "LAX", "America/Los_Angeles"),
    "KMDW": WeatherStation("KMDW", "IL_ASOS", "MDW", "America/Chicago"),
    "KMIA": WeatherStation("KMIA", "FL_ASOS", "MIA", "America/New_York"),
    "KDEN": WeatherStation("KDEN", "CO_ASOS", "DEN", "America/Denver"),
    "KAUS": WeatherStation("KAUS", "TX_ASOS", "AUS", "America/Chicago"),
    "KPHL": WeatherStation("KPHL", "PA_ASOS", "PHL", "America/New_York"),
}

# Kalshi weather series ticker prefix -> canonical station (curated per ADR-0011;
# each entry is a claim about which station that Kalshi series resolves against and
# should be confirmed against the series' Kalshi rules before relying on it).
SERIES_STATION: dict[str, str] = {
    "KXHIGHNY": "KNYC",
}


class WeatherAPIError(RuntimeError):
    """Raised on an unrecoverable IEM API failure: HTTP error, rate limit
    exhausted after retries, or a malformed/unexpected response shape. A plain
    RuntimeError subclass so a caller (the run_weather_ingest entry point, or a
    future WP-7 caller) can catch specifically this and degrade gracefully — clear
    message, non-zero exit — rather than crashing on a bare traceback. Mirrors
    ingest_kalshi.KalshiAPIError."""


def resolve_station(station: WeatherStation | str) -> WeatherStation:
    """A WeatherStation passes through; a str is looked up in STATIONS (ICAO) or
    SERIES_STATION (Kalshi series prefix). Unknown -> ValueError, never a silent
    miss."""
    if isinstance(station, WeatherStation):
        return station
    if station in STATIONS:
        return STATIONS[station]
    if station in SERIES_STATION:
        return STATIONS[SERIES_STATION[station]]
    raise ValueError(
        f"unknown station {station!r} — not a registered ICAO ({sorted(STATIONS)}) "
        f"or Kalshi series ({sorted(SERIES_STATION)}); add it to STATIONS/"
        f"SERIES_STATION in weather_ingest.py")


def _require_aware(dt: datetime, name: str) -> None:
    """Reject a naive datetime — a runtime without tzinfo would be formatted as
    if UTC while actually meaning local wall-clock, silently shifting which model
    cycle is requested. Mirrors store.py / ingest_kalshi.py's convention."""
    if dt.tzinfo is None:
        raise ValueError(
            f"{name} must be timezone-aware, got naive datetime {dt!r}")


def _parse_utc(raw: str) -> datetime:
    """Parse an IEM `*_utc` timestamp (e.g. '2026-07-21T00:00:00.000', already
    UTC by the field name) into a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(raw)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _observed_at(local_date: date, tz: str) -> datetime:
    """The instant a daily extreme for `local_date` became knowable = start of the
    NEXT local calendar day, in UTC. Conservative on the PIT-safe side: never
    earlier than the value was actually known (being late can only exclude a row
    from an as_of window, never leak a future value into it — ADR-0009/0011). Uses
    calendar-day arithmetic then localizes, so it's correct across DST boundaries."""
    nd = local_date + timedelta(days=1)
    local_midnight = datetime(nd.year, nd.month, nd.day, tzinfo=ZoneInfo(tz))
    return local_midnight.astimezone(timezone.utc)


class WeatherSource:
    """Point-based NOAA/NWS forecast + observation reader over IEM's public API.
    Data only — no trading, no persistence (the load_* functions below wire the
    parsed rows to store.py). Network + parse layer, fixture-tested in isolation."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, *, timeout: float = 30.0,
                 max_retries: int = 4, backoff: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    # -- plumbing (mirrors KalshiSource._get) ----------------------------
    def _get(self, path: str, **params) -> dict:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read())
                if not isinstance(body, dict):
                    # valid JSON, wrong shape — every IEM endpoint this module
                    # calls returns a top-level object ({"data": [...]}). A bare
                    # list/string/null would bypass the parsing below and surface
                    # as an uncaught error deep in a caller; raise the documented
                    # WeatherAPIError immediately (not retryable — a permanently
                    # wrong shape won't fix itself).
                    raise WeatherAPIError(
                        f"IEM API returned a non-object JSON response for {url}: "
                        f"expected a JSON object at the top level, got "
                        f"{type(body).__name__}")
                return body
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429 or e.code >= 500:
                    if attempt < self.max_retries - 1:
                        time.sleep(self.backoff * (2 ** attempt))
                    continue
                raise WeatherAPIError(
                    f"IEM API error {e.code} for {url}: {e.reason}") from e
            except urllib.error.URLError as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (2 ** attempt))
            except (json.JSONDecodeError, TimeoutError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (2 ** attempt))
        raise WeatherAPIError(
            f"IEM API unreachable after {self.max_retries} attempt(s): "
            f"{url} ({type(last_err).__name__}: {last_err})") from last_err

    @staticmethod
    def _check_temp(value: float, field: str, station: str) -> float:
        if not (_TEMP_F_MIN <= value <= _TEMP_F_MAX):
            raise ValueError(
                f"{field} out of physical range for {station!r}: {value!r} "
                f"(expected {_TEMP_F_MIN}..{_TEMP_F_MAX} degrees F)")
        return value

    # -- forecasts (MOS) --------------------------------------------------
    def forecasts(self, station: WeatherStation | str, *,
                  model: str = DEFAULT_MOS_MODEL,
                  variable: str = FORECAST_VARIABLE,
                  runtime: datetime | None = None) -> list[WeatherForecastRow]:
        """MOS `tmp` guidance for one station as point-in-time forecast rows:
        issued_at = `runtime_utc` (model cycle), valid_at = `ftime_utc`. Rows with
        no `tmp` value (that field null for a given forecast hour) are skipped —
        they carry no temperature to store, not an error.

        `runtime` selects a specific past model CYCLE (verified accepted by IEM in
        ISO-Z form, 2026-07-20). `None` (default) returns only IEM's LATEST cycle —
        so forecast *history* is built either by running this on a schedule (each
        cycle upserts new issued_at rows) or by supplying past runtimes (the
        run_weather_ingest CLI iterates daily cycles across a window for exactly
        this reason)."""
        st = resolve_station(station)
        source = f"iem-mos-{model.lower()}"
        runtime_arg = None
        if runtime is not None:
            _require_aware(runtime, "runtime")
            runtime_arg = runtime.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = self._get("/mos.json", station=st.icao, model=model, runtime=runtime_arg)
        rows: list[WeatherForecastRow] = []
        # _get() guarantees `data` is a dict; this try/except covers the next layer
        # — a row missing an expected key, a non-ISO timestamp, or a non-numeric
        # temperature — valid JSON, wrong shape (mirrors KalshiSource's parsing
        # guards), turning it into WeatherAPIError instead of a bare traceback.
        try:
            for r in data.get("data") or []:
                tmp = r.get("tmp")
                if tmp is None:
                    continue
                issued = _parse_utc(r["runtime_utc"])
                valid = _parse_utc(r["ftime_utc"])
                if not issued < valid:
                    # The load-bearing PIT invariant (WP-6 acceptance:
                    # "issued_at < valid_at on every row"). A forecast is always
                    # for a time at/after its run; a response violating this is
                    # malformed and must fail loud, never be stored.
                    raise ValueError(
                        f"forecast issued_at {issued.isoformat()} not before "
                        f"valid_at {valid.isoformat()} for {st.icao!r} — refusing "
                        f"to store a non-point-in-time forecast row")
                value = self._check_temp(float(tmp), "tmp", st.icao)
                horizon_h = (valid - issued).total_seconds() / 3600.0
                rows.append(WeatherForecastRow(
                    issued_at=issued, valid_at=valid, station=st.icao,
                    variable=variable, value=value, source=source,
                    horizon_h=horizon_h))
        except (KeyError, TypeError, ValueError) as e:
            raise WeatherAPIError(
                f"IEM API returned an unexpected MOS response shape for "
                f"{st.icao!r} (model={model!r}): {type(e).__name__}: {e}") from e
        return rows

    # -- observations (ASOS daily) ---------------------------------------
    def observations(self, station: WeatherStation | str, *,
                     start: date, end: date) -> list[WeatherObservationRow]:
        """Daily max/min temperature for one station over [start, end] (inclusive,
        by local calendar date) as observation rows. The daily endpoint is queried
        per (year, month) covering the window; rows outside [start, end] are
        dropped. Emits a tmax and/or tmin row per day, whichever the response
        carries (a null extreme is skipped, not stored)."""
        if end < start:
            raise ValueError(f"end {end} is before start {start}")
        st = resolve_station(station)
        rows: list[WeatherObservationRow] = []
        for year, month in _months_between(start, end):
            data = self._get("/daily.json", network=st.iem_network,
                             station=st.iem_daily_station, year=year, month=month)
            try:
                for r in data.get("data") or []:
                    d = date.fromisoformat(r["date"])
                    if d < start or d > end:
                        continue
                    observed_at = _observed_at(d, st.tz)
                    for variable, key in ((OBS_TMAX, "max_tmpf"),
                                          (OBS_TMIN, "min_tmpf")):
                        raw = r.get(key)
                        if raw is None:
                            continue
                        value = self._check_temp(float(raw), key, st.icao)
                        rows.append(WeatherObservationRow(
                            observed_at=observed_at, station=st.icao,
                            variable=variable, value=value, source="iem-asos"))
            except (KeyError, TypeError, ValueError) as e:
                raise WeatherAPIError(
                    f"IEM API returned an unexpected daily response shape for "
                    f"{st.icao!r} ({year}-{month:02d}): "
                    f"{type(e).__name__}: {e}") from e
        return rows


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    """Every (year, month) touched by [start, end], inclusive."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------------------
# named entry functions (plan.md WP-6 "Outputs / signatures") — fetch + upsert
# into the store (WP-1). Idempotent via store's ON CONFLICT upserts, so a re-run
# updates in place and never duplicates rows (WP-6 acceptance).
# ---------------------------------------------------------------------------
def load_forecasts(conn, src: WeatherSource, station: WeatherStation | str, *,
                   model: str = DEFAULT_MOS_MODEL,
                   variable: str = FORECAST_VARIABLE,
                   runtimes: Sequence[datetime] | None = None) -> int:
    """Fetch MOS forecasts for one station and upsert them into weather_forecast.
    `runtimes=None` pulls IEM's latest cycle (one call); a list of runtimes pulls
    each past model cycle in turn (forecast-history backfill) and upserts them all.
    Returns the total row count written. Raises WeatherAPIError on a bad response,
    or whatever store.py raises on a DB failure — the caller decides how to report."""
    import store
    cycles: Sequence[datetime | None] = runtimes if runtimes else [None]
    total = 0
    for rt in cycles:
        rows = src.forecasts(station, model=model, variable=variable, runtime=rt)
        store.upsert_forecasts(conn, rows)
        total += len(rows)
    return total


def load_observations(conn, src: WeatherSource, station: WeatherStation | str, *,
                      start: date, end: date) -> int:
    """Fetch daily observations for one station over [start, end] and upsert them
    into weather_observation. Returns the row count written."""
    import store
    rows = src.observations(station, start=start, end=end)
    store.upsert_observations(conn, rows)
    return len(rows)


if __name__ == "__main__":
    src = WeatherSource()
    try:
        fc = src.forecasts("KNYC")
        print(f"forecasts KNYC (model={DEFAULT_MOS_MODEL}): {len(fc)} rows")
        if fc:
            f = fc[0]
            print(f"  e.g. issued={f.issued_at.isoformat()} valid={f.valid_at.isoformat()} "
                  f"{f.variable}={f.value} h+{f.horizon_h:.0f} src={f.source}")
        today = datetime.now(timezone.utc).date()
        obs = src.observations("KNYC", start=today - timedelta(days=7), end=today)
        print(f"observations KNYC last 7d: {len(obs)} rows")
        if obs:
            o = obs[0]
            print(f"  e.g. observed_at={o.observed_at.isoformat()} "
                  f"{o.variable}={o.value} src={o.source}")
    except WeatherAPIError as e:
        print(f"IEM API failure: {e}")
        sys.exit(1)
