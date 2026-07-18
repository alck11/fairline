"""
store.py — thin persistence layer for the Kalshi directional-EV MVP (WP-1).

Provisioning: PostgreSQL 15+ with the TimescaleDB extension (see README ->
"Database setup"). Apply schema/001_schema.sql then schema/002_kalshi_ev.sql,
in that order, to a fresh database before running anything here.

This module is deliberately dumb: a connection from env config, idempotent
upserts keyed on the natural key ADR-0010 assigns each table, and three
point-in-time ("PIT") read helpers that enforce `< as_of` in SQL — never in
Python — so the guarantee ADR-0009 depends on lives in exactly one place. NO
business logic (EV, sizing, model) and NO network/API calls live here:
persistence only (WP-1 boundary; those are WP-3/WP-4/WP-8).

Outcome addressing. schema/001_schema.sql's `outcome` table (untouched, per
ADR-0010: "no change to market/outcome/venue/trade_print") carries no column
for the venue-native token/ticker id that Candle, ResolutionRow,
DirectionalSignal and every PIT reader below address outcomes by (see
ingest.py's `OutcomeRef.token_id`: "Polymarket CLOB token id / Kalshi ticker
side"). This module resolves that string to the internal `outcome_id` FK via
the additive `outcome_token` bridge table (schema/002_kalshi_ev.sql),
populated by `upsert_outcomes`. Every function below that takes `token_id`
does this resolution internally so callers never see `outcome_id`.

Demo: `python3 src/store.py` needs a real Postgres reachable via
$DATABASE_URL (see README) — there is no synthetic in-memory demo for a
persistence layer; it prints a clear message and exits if none is reachable.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

import psycopg
from psycopg import Connection
from psycopg.types.json import Json

from ingest import MarketRow, OutcomeRef
from ev_detector import DirectionalSignal


# ---------------------------------------------------------------------------
# row types WP-1 defines the target columns for. WP-3 formalizes Candle /
# ResolutionRow as part of ingest.py's MarketDataSource Protocol per the
# plan's "Outputs / signatures" section; these are that exact shape
# (ts/token_id/open/high/low/close/volume and
# external_id/outcome_token_id/resolved_value/resolved_at) so WP-3 can import
# them from here, or define byte-compatible ones — this module only cares
# that the fields it reads exist.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Candle:
    ts: datetime
    token_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass(frozen=True)
class ResolutionRow:
    external_id: str          # market's external_id (ticker) — informational
    outcome_token_id: str
    resolved_value: float     # 1.0 / 0.0
    resolved_at: datetime | None = None   # informational only; see apply_resolutions


@dataclass(frozen=True)
class WeatherForecastRow:
    issued_at: datetime       # PIT key — what was knowable when published
    valid_at: datetime
    station: str
    variable: str
    value: float
    source: str
    horizon_h: float | None = None


@dataclass(frozen=True)
class WeatherObservationRow:
    observed_at: datetime     # PIT key
    station: str
    variable: str
    value: float
    source: str


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------
def connect() -> Connection:
    """Open a connection from env config: $DATABASE_URL if set, else the
    standard libpq env vars ($PGHOST/$PGPORT/$PGDATABASE/$PGUSER/$PGPASSWORD),
    exactly like `psql` with no args. Autocommit: every function below is a
    single statement (or a short loop of them) with no caller-visible
    transaction to manage — a thin layer, not a unit-of-work abstraction."""
    dsn = os.environ.get("DATABASE_URL", "")
    return psycopg.connect(dsn, autocommit=True)


# ---------------------------------------------------------------------------
# internal: token_id -> outcome_id resolution (see module docstring)
# ---------------------------------------------------------------------------
def _resolve_outcome_id(conn: Connection, token_id: str) -> int:
    row = conn.execute(
        "SELECT outcome_id FROM outcome_token WHERE token_id = %s", (token_id,)
    ).fetchone()
    if row is None:
        raise KeyError(
            f"unknown token_id {token_id!r} — upsert_outcomes() must be "
            f"called for its market before candles/resolutions/signals "
            f"reference it")
    return row[0]


# ---------------------------------------------------------------------------
# dimension upserts
# ---------------------------------------------------------------------------
def upsert_market(conn: Connection, market: MarketRow) -> int:
    """Idempotent on (venue, external_id) (ADR-0010). Returns market_id."""
    row = conn.execute(
        """
        INSERT INTO market (venue, external_id, question, category,
                             resolution_text, resolves_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (venue, external_id) DO UPDATE SET
            question        = EXCLUDED.question,
            category        = EXCLUDED.category,
            resolution_text = EXCLUDED.resolution_text,
            resolves_at     = EXCLUDED.resolves_at
        RETURNING market_id
        """,
        (market.venue, market.external_id, market.question, market.category,
         market.resolution_text, market.resolves_at),
    ).fetchone()
    return row[0]


def upsert_outcomes(conn: Connection, market_id: int,
                     outcomes: Sequence[OutcomeRef]) -> None:
    """Idempotent on (market_id, idx) for `outcome` (001, untouched) and on
    token_id for the outcome_token bridge (see module docstring)."""
    for o in outcomes:
        row = conn.execute(
            """
            INSERT INTO outcome (market_id, label, idx)
            VALUES (%s, %s, %s)
            ON CONFLICT (market_id, idx) DO UPDATE SET label = EXCLUDED.label
            RETURNING outcome_id
            """,
            (market_id, o.label, o.idx),
        ).fetchone()
        outcome_id = row[0]
        conn.execute(
            """
            INSERT INTO outcome_token (token_id, outcome_id)
            VALUES (%s, %s)
            ON CONFLICT (token_id) DO UPDATE SET outcome_id = EXCLUDED.outcome_id
            """,
            (o.token_id, outcome_id),
        )


def upsert_candles(conn: Connection, candles: Sequence[Candle]) -> None:
    """Idempotent on (outcome_id, ts) (ADR-0010)."""
    for c in candles:
        outcome_id = _resolve_outcome_id(conn, c.token_id)
        conn.execute(
            """
            INSERT INTO candlestick (ts, outcome_id, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (outcome_id, ts) DO UPDATE SET
                open   = EXCLUDED.open,  high   = EXCLUDED.high,
                low    = EXCLUDED.low,   close  = EXCLUDED.close,
                volume = EXCLUDED.volume
            """,
            (c.ts, outcome_id, c.open, c.high, c.low, c.close, c.volume),
        )


def apply_resolutions(conn: Connection, resolutions: Sequence[ResolutionRow]) -> None:
    """Update `outcome.resolved_value` and mark the parent `market` resolved.
    Resolution timestamps are not persisted as a separate column — ADR-0010:
    "resolutions are just updates to these [existing] columns" — the PIT
    anchor for settlement stays `market.resolves_at` (already stored, already
    the scheduled resolution time)."""
    for r in resolutions:
        outcome_id = _resolve_outcome_id(conn, r.outcome_token_id)
        conn.execute(
            "UPDATE outcome SET resolved_value = %s WHERE outcome_id = %s",
            (r.resolved_value, outcome_id),
        )
        conn.execute(
            """
            UPDATE market SET resolved = true
            WHERE market_id = (SELECT market_id FROM outcome WHERE outcome_id = %s)
            """,
            (outcome_id,),
        )


def upsert_forecasts(conn: Connection, rows: Sequence[WeatherForecastRow]) -> None:
    """Idempotent on (source, station, variable, issued_at, valid_at) (ADR-0010)."""
    for f in rows:
        conn.execute(
            """
            INSERT INTO weather_forecast (issued_at, valid_at, station, variable,
                                           value, source, horizon_h)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, station, variable, issued_at, valid_at)
            DO UPDATE SET value = EXCLUDED.value, horizon_h = EXCLUDED.horizon_h
            """,
            (f.issued_at, f.valid_at, f.station, f.variable, f.value, f.source,
             f.horizon_h),
        )


def upsert_observations(conn: Connection, rows: Sequence[WeatherObservationRow]) -> None:
    """Idempotent on the PK (station, variable, observed_at) (ADR-0010)."""
    for o in rows:
        conn.execute(
            """
            INSERT INTO weather_observation (observed_at, station, variable, value, source)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (station, variable, observed_at)
            DO UPDATE SET value = EXCLUDED.value, source = EXCLUDED.source
            """,
            (o.observed_at, o.station, o.variable, o.value, o.source),
        )


def write_signal(conn: Connection, run_id: str, signal: DirectionalSignal,
                  as_of: datetime) -> None:
    """Persist one DirectionalSignal at decision time. Idempotent on
    (run_id, as_of, outcome_id). `prob_fn_name` is not a DirectionalSignal
    field (ev_detector.py predates the prob_fn contract, ADR-0009, and stays
    untouched per WP-2's boundary) — it is pulled from the backtest_run row
    `write_backtest_run` must already have written for this run_id, so
    `directional_signal.prob_fn_name` is always consistent with its run."""
    outcome_id = _resolve_outcome_id(conn, signal.token_id)
    conn.execute(
        """
        INSERT INTO directional_signal (run_id, as_of, outcome_id, p_model, price,
                                         size, ev_per_share, expected_profit,
                                         prob_fn_name)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                (SELECT prob_fn_name FROM backtest_run WHERE run_id = %s))
        ON CONFLICT (run_id, as_of, outcome_id) DO UPDATE SET
            p_model         = EXCLUDED.p_model,
            price           = EXCLUDED.price,
            size            = EXCLUDED.size,
            ev_per_share    = EXCLUDED.ev_per_share,
            expected_profit = EXCLUDED.expected_profit,
            prob_fn_name    = EXCLUDED.prob_fn_name
        """,
        (run_id, as_of, outcome_id, signal.p_model, signal.price, signal.size,
         signal.ev_per_share, signal.expected_profit, run_id),
    )


def write_backtest_run(conn: Connection, run_id: str, prob_fn_name: str,
                        category: str, window_start: datetime,
                        window_end: datetime, step: str,
                        params: dict | None = None,
                        git_sha: str | None = None) -> None:
    """Idempotent on run_id (PK)."""
    conn.execute(
        """
        INSERT INTO backtest_run (run_id, prob_fn_name, category, window_start,
                                   window_end, step, params, git_sha)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id) DO UPDATE SET
            prob_fn_name = EXCLUDED.prob_fn_name,
            category     = EXCLUDED.category,
            window_start = EXCLUDED.window_start,
            window_end   = EXCLUDED.window_end,
            step         = EXCLUDED.step,
            params       = EXCLUDED.params,
            git_sha      = EXCLUDED.git_sha
        """,
        (run_id, prob_fn_name, category, window_start, window_end, step,
         Json(params) if params is not None else None, git_sha),
    )


def write_backtest_result(conn: Connection, run_id: str, token_id: str,
                           entry_as_of: datetime, entry_price: float,
                           size: float, resolved_value: float,
                           fee_paid: float, realized_pnl: float) -> None:
    """Idempotent on (run_id, outcome_id, entry_as_of)."""
    outcome_id = _resolve_outcome_id(conn, token_id)
    conn.execute(
        """
        INSERT INTO backtest_result (run_id, outcome_id, entry_as_of, entry_price,
                                      size, resolved_value, fee_paid, realized_pnl)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id, outcome_id, entry_as_of) DO UPDATE SET
            entry_price    = EXCLUDED.entry_price,
            size           = EXCLUDED.size,
            resolved_value = EXCLUDED.resolved_value,
            fee_paid       = EXCLUDED.fee_paid,
            realized_pnl   = EXCLUDED.realized_pnl
        """,
        (run_id, outcome_id, entry_as_of, entry_price, size, resolved_value,
         fee_paid, realized_pnl),
    )


# ---------------------------------------------------------------------------
# point-in-time readers — `< as_of` enforced in SQL, never in Python
# (ADR-0009's binding guarantee)
# ---------------------------------------------------------------------------
def candles_before(conn: Connection, token_id: str, as_of: datetime) -> list[Candle]:
    outcome_id = _resolve_outcome_id(conn, token_id)
    rows = conn.execute(
        """
        SELECT ts, open, high, low, close, volume FROM candlestick
        WHERE outcome_id = %s AND ts < %s
        ORDER BY ts
        """,
        (outcome_id, as_of),
    ).fetchall()
    return [
        Candle(ts, token_id, float(o), float(h), float(l), float(c),
               float(v) if v is not None else None)
        for ts, o, h, l, c, v in rows
    ]


def forecasts_before(conn: Connection, station: str, variable: str,
                      as_of: datetime) -> list[WeatherForecastRow]:
    rows = conn.execute(
        """
        SELECT issued_at, valid_at, value, source, horizon_h FROM weather_forecast
        WHERE station = %s AND variable = %s AND issued_at < %s
        ORDER BY issued_at
        """,
        (station, variable, as_of),
    ).fetchall()
    return [
        WeatherForecastRow(issued_at, valid_at, station, variable, float(value),
                            source, float(horizon_h) if horizon_h is not None else None)
        for issued_at, valid_at, value, source, horizon_h in rows
    ]


def observations_before(conn: Connection, station: str, variable: str,
                         as_of: datetime) -> list[WeatherObservationRow]:
    rows = conn.execute(
        """
        SELECT observed_at, value, source FROM weather_observation
        WHERE station = %s AND variable = %s AND observed_at < %s
        ORDER BY observed_at
        """,
        (station, variable, as_of),
    ).fetchall()
    return [
        WeatherObservationRow(observed_at, station, variable, float(value), source)
        for observed_at, value, source in rows
    ]


if __name__ == "__main__":
    try:
        conn = connect()
        conn.execute("SELECT 1")
    except Exception as e:
        print("store.py demo needs a real Postgres+TimescaleDB reachable via "
              "$DATABASE_URL (see README -> 'Database setup').")
        print(f"connect() failed: {type(e).__name__}: {e}")
        raise SystemExit(0)

    market = MarketRow(
        venue="kalshi", external_id="KXHIGHNY-26JUL20-DEMO",
        question="Will NYC's high temp on Jul 20 be >= 90F?",
        category="weather", resolution_text="NWS KNYC official high, per Kalshi rules.",
        outcomes=(OutcomeRef("KXHIGHNY-26JUL20-DEMO-YES", "YES", 0),
                  OutcomeRef("KXHIGHNY-26JUL20-DEMO-NO", "NO", 1)),
    )
    market_id = upsert_market(conn, market)
    upsert_outcomes(conn, market_id, market.outcomes)
    print(f"upserted market_id={market_id} with {len(market.outcomes)} outcomes")

    ts = datetime.now(timezone.utc)
    upsert_candles(conn, [Candle(ts, "KXHIGHNY-26JUL20-DEMO-YES", 0.40, 0.44, 0.39, 0.42, 1200.0)])
    back = candles_before(conn, "KXHIGHNY-26JUL20-DEMO-YES", ts + timedelta(seconds=1))
    print(f"candles_before -> {back}")
    conn.close()
