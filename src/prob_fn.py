"""
prob_fn.py — the ProbFn interface contract (ADR-0009) + the MidpriceProbFn
placeholder/baseline, plus an optional ClimatologyProbFn sanity check (WP-2).

The MVP's whole value is a trustworthy answer to "does a model beat Kalshi's
price after fees?" That answer is only trustworthy if the model interface (a)
is stable enough that both build tracks (plumbing and the weather model)
target it, and (b) *mechanically* forbids lookahead. This module fixes that
contract, ahead of both the harness (WP-4) and the real model (WP-8):

    MarketRef   -- everything a model might key its answer on
    ProbFn      -- the Protocol: (market, as_of) -> p in [0,1]
    MidpriceProbFn -- returns the last candlestick close strictly before
                      as_of. Serves double duty: it unblocks the harness
                      before a real model exists, AND it *is* the US-6
                      "always-market-price" baseline (p_model = price has
                      zero gross edge and pays only fees) — one object, two
                      roles, per ADR-0009.
    ClimatologyProbFn -- optional fixed base-rate ProbFn for sanity checks.

Point-in-time guarantee (binding on every ProbFn implementation here): given
`as_of`, a ProbFn may read only data timestamped strictly before `as_of`. That
guarantee is enforced once, in SQL, by store.py's PIT readers (`candles_before`
et al. filter `ts < as_of` server-side) — this module never re-implements the
filter in Python, it only calls through a `Reader` that already enforces it.

`ev_detector.find_signal` is NOT changed here and does not import this module.
It still takes `prob_fn: Callable[[str], float]` — a later work package (the
WP-4 harness) resolves `p = prob_fn(ref, as_of)` per step and binds it into
`find_signal` via a trivial `lambda _tok: p`. See ADR-0009 "Option 2".

Demo: `python3 src/prob_fn.py` runs against a synthetic in-memory Reader (no
network, no real Postgres), matching the repo convention that every module
self-demos. `StoreReader` (a real-Postgres-backed Reader) is exercised by the
round-trip test in tests/test_prob_fn.py only when a store.Connection is
available — the demo below stays connection-free by design.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from store import Candle, Connection
import store as _store


# ---------------------------------------------------------------------------
# the contract (ADR-0009, verbatim field-for-field)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketRef:
    external_id: str            # Kalshi ticker
    venue: str                  # 'kalshi'
    category: str                # 'weather' | 'economics' | ...
    outcome_token_id: str       # the outcome being priced
    outcome_label: str          # 'YES' | 'NO' | candidate
    resolves_at: datetime | None
    params: dict                # resolution parameters a model may key on:
                                 # e.g. {'station':'KNYC','threshold_f':90,
                                 #       'target_date':'2026-07-20','comparator':'>='}


@runtime_checkable
class ProbFn(Protocol):
    """`p = prob_fn(market, as_of)`. Every implementation must:
      - read only data timestamped strictly before `as_of` (PIT guarantee);
      - return p in [0,1] (clamped/validated — see `_clamp01` below);
      - carry a stable `name` (stamped into backtest_run.prob_fn_name)."""
    name: str

    def __call__(self, market: MarketRef, as_of: datetime) -> float: ...


# ---------------------------------------------------------------------------
# data access — a read handle exposing the PIT readers, minus `conn`
# (ADR-0009 "Data access": "constructed with a read handle ... exposing
# candles_before(token_id, as_of), forecasts_before(...), observations_before(...)")
# ---------------------------------------------------------------------------
@runtime_checkable
class Reader(Protocol):
    """What a ProbFn implementation is constructed with. Any object exposing
    these three methods qualifies — store.StoreReader below adapts a real
    store.Connection; tests use a trivial in-memory fake. The PIT filter
    (`< as_of`) must already be enforced by whatever backs this Reader; this
    module trusts that and does not re-check it."""

    def candles_before(self, token_id: str, as_of: datetime) -> list[Candle]: ...

    def forecasts_before(self, station: str, variable: str,
                         as_of: datetime) -> list: ...

    def observations_before(self, station: str, variable: str,
                            as_of: datetime) -> list: ...


class StoreReader:
    """Adapts a store.Connection to the `Reader` protocol by binding `conn`
    once at construction, so a ProbFn's constructor signature never has to
    know about database connections — it just takes "a reader". store.py's
    PIT readers do the actual `< as_of` enforcement in SQL; this class adds
    no logic of its own beyond forwarding the bound `conn`."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def candles_before(self, token_id: str, as_of: datetime) -> list[Candle]:
        return _store.candles_before(self._conn, token_id, as_of)

    def forecasts_before(self, station: str, variable: str, as_of: datetime) -> list:
        return _store.forecasts_before(self._conn, station, variable, as_of)

    def observations_before(self, station: str, variable: str, as_of: datetime) -> list:
        return _store.observations_before(self._conn, station, variable, as_of)


# ---------------------------------------------------------------------------
# shared output validation
# ---------------------------------------------------------------------------
class NoPriorDataError(LookupError):
    """Raised by a ProbFn when it has no data strictly before `as_of` to
    derive a probability from."""


def _clamp01(p: float) -> float:
    """Clamp/validate a ProbFn's raw output to [0,1] per WP-2's acceptance
    criteria. NaN is rejected outright — clamping a NaN would silently turn
    "the computation broke" into a confident-looking 0.0 or 1.0."""
    if p != p:  # NaN is the only float that is != itself
        raise ValueError("prob_fn output is NaN")
    return min(1.0, max(0.0, p))


# ---------------------------------------------------------------------------
# MidpriceProbFn — placeholder AND US-6 baseline (ADR-0009)
# ---------------------------------------------------------------------------
class MidpriceProbFn:
    """p = last candlestick close with ts < as_of.

    Double duty per ADR-0009: (a) it unblocks the WP-4 harness before the
    real weather model (WP-8) exists, and (b) it *is* the US-6
    "always-market-price" baseline — p_model = price has zero gross edge and
    pays only fees, which is exactly what a baseline needs to be.

    Behavior when no candle exists strictly before `as_of`: RAISES
    `NoPriorDataError`, rather than returning some default (e.g. 0.5). A
    probability cannot be honestly manufactured from an empty history — a
    silent 0.5 would look like a real (if unconfident) model output and could
    enter EV math as if it were one, when really it's "we don't know yet."
    Raising forces the caller (the WP-4 harness, ultimately) to make an
    explicit decision — typically: skip this step of the backtest/live loop —
    instead of trading on a fabricated probability. This mirrors store.py's
    own convention of raising (KeyError) on missing/unresolvable data rather
    than returning a sentinel.
    """

    name = "MidpriceProbFn"

    def __init__(self, reader: Reader):
        self._reader = reader

    def __call__(self, market: MarketRef, as_of: datetime) -> float:
        candles = self._reader.candles_before(market.outcome_token_id, as_of)
        if not candles:
            raise NoPriorDataError(
                f"MidpriceProbFn: no candlestick strictly before as_of={as_of!r} "
                f"for outcome_token_id={market.outcome_token_id!r} — cannot "
                f"derive a probability from no data")
        last = max(candles, key=lambda c: c.ts)   # PIT readers already sort by
                                                    # ts ascending; max() is a
                                                    # belt-and-suspenders guard
                                                    # against a Reader that doesn't.
        return _clamp01(last.close)


# ---------------------------------------------------------------------------
# ClimatologyProbFn — optional fixed base-rate sanity check (ADR-0009)
# ---------------------------------------------------------------------------
class ClimatologyProbFn:
    """p = a fixed base rate, independent of `market`/`as_of`. Reads no data
    at all, so the PIT guarantee holds trivially. Useful as a sanity-check
    counterpart to MidpriceProbFn in a backtest: a model that can't beat a
    constant is not a model worth deploying."""

    name = "ClimatologyProbFn"

    def __init__(self, base_rate: float):
        if not 0.0 <= base_rate <= 1.0:
            raise ValueError(f"base_rate must be in [0,1], got {base_rate}")
        self._base_rate = base_rate

    def __call__(self, market: MarketRef, as_of: datetime) -> float:
        return _clamp01(self._base_rate)


if __name__ == "__main__":
    from datetime import timezone

    class _FakeReader:
        """Synthetic in-memory Reader — no network, no real Postgres."""

        def __init__(self, candles: list[Candle]):
            self._candles = candles

        def candles_before(self, token_id, as_of):
            return [c for c in self._candles
                    if c.token_id == token_id and c.ts < as_of]

        def forecasts_before(self, station, variable, as_of):
            return []

        def observations_before(self, station, variable, as_of):
            return []

    t0 = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    reader = _FakeReader([
        Candle(t0, "tok-yes", 0.10, 0.12, 0.09, 0.11, 500.0),
        Candle(t0.replace(hour=13), "tok-yes", 0.11, 0.15, 0.11, 0.14, 700.0),
    ])
    market = MarketRef(
        external_id="KXHIGHNY-26JUL20-DEMO", venue="kalshi", category="weather",
        outcome_token_id="tok-yes", outcome_label="YES",
        resolves_at=None, params={"station": "KNYC", "threshold_f": 90})

    midprice = MidpriceProbFn(reader)
    p = midprice(market, t0.replace(hour=14))
    print(f"MidpriceProbFn: p={p:.2f} (name={midprice.name})")

    clima = ClimatologyProbFn(0.30)
    print(f"ClimatologyProbFn: p={clima(market, t0):.2f} (name={clima.name})")

    try:
        midprice(market, t0)   # only candle strictly before t0... none exist
    except NoPriorDataError as e:
        print(f"NoPriorDataError (expected, no candle strictly before t0): {e}")
