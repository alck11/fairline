# The prob_fn interface contract: (market, as_of) -> p, point-in-time

The MVP's whole value is a trustworthy answer to "does a model beat Kalshi's price
after fees?" That answer is only trustworthy if the model interface (a) is stable
enough that both build tracks target it, and (b) *mechanically* forbids lookahead.
This ADR fixes that contract. It is defined in **week 1** (roadmap A2 / US-3),
before the harness or the weather model, because both depend on it.

## Context

- `ev_detector.find_signal` today takes `prob_fn: Callable[[str], float]` — a
  token_id in, a probability out. It has **no `as_of`**, so it cannot express the
  point-in-time guarantee a backtest requires, and no market context beyond an id.
- US-3 mandates `prob_fn(market, as_of) -> p_model ∈ [0,1]` with a stated
  point-in-time guarantee, and a placeholder both tracks build against.
- The parked ADR-0003 established the discipline: a decision at time `t` may use
  only data resolved/timestamped strictly before `t`. That principle is the reason
  this contract carries `as_of`.

The tension: enrich the signature (US-3) **without** breaking `ev_detector`'s
tested EV/Kelly code, and without a lookahead loophole.

## Options considered

1. **Change `ev_detector.find_signal`'s `prob_fn` signature to `(market, as_of)`.**
   Honest, but rewrites tested code (WP-8 archived) and couples the low-level EV
   math to market/as_of concepts it doesn't need — it only needs a scalar `p`.
2. **Define the contract one layer up (chosen).** A new `ProbFn` Protocol,
   `prob_fn(market, as_of) -> p`, lives in `src/prob_fn.py` and is what the
   **harness** and the **weather model** target. The harness resolves
   `p = prob_fn(ref, as_of)` per step and passes it into the unchanged
   `find_signal` via a trivial `lambda _tok: p`. `ev_detector` stays byte-compatible.
3. **Let each model read the DB directly with no contract.** Rejected: no single
   place to enforce the PIT guarantee; every model re-implements the loophole risk.

## Decision

**Option 2.** The contract is:

```python
# src/prob_fn.py
@dataclass(frozen=True)
class MarketRef:
    external_id: str            # Kalshi ticker
    venue: str                  # 'kalshi'
    category: str               # 'weather' | 'economics' | ...
    outcome_token_id: str       # the outcome being priced
    outcome_label: str          # 'YES' | 'NO' | candidate
    resolves_at: datetime | None
    params: dict                # resolution parameters a model may key on:
                                # e.g. {'station':'KNYC','threshold_f':90,
                                #       'target_date':'2026-07-20','comparator':'>='}

class ProbFn(Protocol):
    name: str                                   # stamped into backtest_run
    def __call__(self, market: MarketRef, as_of: datetime) -> float: ...  # p in [0,1]
```

**Point-in-time guarantee (binding on every implementation):** given `as_of`, a
`ProbFn` may read only data timestamped strictly before `as_of` — candlesticks
with `ts < as_of`, `weather_forecast` with `issued_at < as_of`,
`weather_observation` with `observed_at < as_of`. It must return `p ∈ [0,1]` (the
harness/`ev_detector` raise on violation).

**Placeholder = baseline.** `MidpriceProbFn` returns the last candlestick close
strictly before `as_of`. It (a) unblocks the harness before the real model exists
(US-3) and (b) *is* the US-6 always-market-price baseline — `p_model = price` has
zero gross edge and pays only fees. One object serves both roles. A second trivial
`ClimatologyProbFn` (fixed base rate) is optional for sanity checks.

**Data access.** A `ProbFn` implementation is constructed with a read handle (a
store/reader object exposing `candles_before(token_id, as_of)`,
`forecasts_before(...)`, `observations_before(...)`). The reader enforces the
`< as_of` filter in SQL so the guarantee is one place, not per-model.

## Consequences

- Both tracks build against one signature from week 1; the weather model (WP-8)
  drops into the harness with **no harness change** (US-3 acceptance).
- `ev_detector.py` is untouched — its `Callable[[str], float]` param is now an
  internal adapter target, bound per-step by the harness. Documented, low blast radius.
- The `prob_fn`/forecast PIT guarantee is enforced **by construction**: store.py's
  PIT readers filter `< as_of` in SQL, one place, for every model. The US-7 audit
  (`audit_run`) mechanically **re-checks the price surface** — that every recorded
  signal price reproduces from candlesticks strictly before its `as_of` — catching
  price lookahead. Re-deriving a model's own `p_model`/forecast PIT-honesty needs
  the model itself and is deferred to WP-8's model-leakage tests.
- What becomes harder: a model that legitimately needs *streaming* intra-step data
  must still express it as "timestamped before as_of"; anything without a timestamp
  cannot enter a `ProbFn` and stay auditable. That constraint is deliberate.
