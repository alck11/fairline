"""
ev_detector.py — EXPERIMENTAL third strategy: model-based directional EV.

Unlike arbitrage (guaranteed profit from a complete set) and copy-trading
(following scored wallets), a directional bet backs ONE side because YOUR
probability model disagrees with the market's price. It is not riskless and it
is only as good as the injected model — see ADR-0005 for why this is a
paper-only prototype and why the motivating evidence is treated with suspicion.

The probability model is NOT built here. `prob_fn(token_id) -> p` is injected,
exactly like `embedder`/`confirmer` in market_matcher. This module owns only:

    * EV per share after fees (fees.Leg is the single source of truth)
    * depth-aware sizing (reuses detector.vwap_fill; stop where EV dies)
    * fractional-Kelly cap so a confident model can't bet the farm

Output is a DirectionalSignal — deliberately NOT an Opportunity (that word is
arb-specific, see CONTEXT.md) and it is never written to arb_opportunity.
Execution still goes through Engine's risk gates like everything else.

Demo: `python3 src/ev_detector.py` (synthetic weather example, no network).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Sequence

from fees import Leg
from detector import Level, vwap_fill


@dataclass(frozen=True)
class DirectionalSignal:
    token_id: str
    venue: str
    category: str
    p_model: float            # injected model probability the outcome pays $1
    price: float              # VWAP fill price at `size`
    size: float               # shares, after depth + Kelly + notional caps
    ev_per_share: float       # post-fee expected value per share at `price`
    expected_profit: float    # ev_per_share * size
    kelly_size: float         # what fractional Kelly alone would allow


def ev_per_share(p: float, price: float, *, venue: str, category: str,
                 size: float = 1.0) -> float:
    """Post-fee expected value of buying one share at `price` when the model
    says it pays $1 with probability `p`:
        EV = p*(1-price) - (1-p)*price - fee_per_share
           = p - price - fee_per_share
    Fees come from fees.Leg so venue/category rules stay in one place."""
    fee = Leg(venue, size, price, category).fee() / size if size > 0 else 0.0
    return p - price - fee


def kelly_shares(p: float, price: float, bankroll: float,
                 *, kelly_fraction: float = 0.25) -> float:
    """Shares allowed by fractional Kelly on a binary contract bought at
    `price` (win: +$(1-price)/share, lose: -$price/share).

        f* = (p - price) / (1 - price)     # fraction of bankroll to stake

    Full Kelly is famously too aggressive for noisy edges (and our p comes
    from an unproven model), so default to quarter-Kelly."""
    if price >= 1.0 or p <= price:
        return 0.0
    f_star = (p - price) / (1.0 - price)
    stake = bankroll * f_star * kelly_fraction
    return stake / price


def find_signal(token_id: str, asks: Sequence[Level], *,
                venue: str, category: str,
                prob_fn: Callable[[str], float],
                bankroll: float = 1_000.0,
                min_ev: float = 0.02,
                kelly_fraction: float = 0.25,
                step: float = 10.0,
                max_size: float = 5_000.0) -> DirectionalSignal | None:
    """Size a directional bet into the book, VWAP-repriced at each step, and
    return the largest size whose post-fee EV per share still clears `min_ev`
    — capped by fractional Kelly. Returns None when the model has no edge
    worth the buffer (the common case, and the honest one)."""
    p = prob_fn(token_id)
    if not 0.0 < p < 1.0:
        raise ValueError(f"prob_fn must return p in (0,1), got {p}")

    top = asks[0][0] if asks else None
    if top is None:
        return None
    k_cap = kelly_shares(p, top, bankroll, kelly_fraction=kelly_fraction)
    if k_cap < step:
        return None

    best: DirectionalSignal | None = None
    size = step
    while size <= min(max_size, k_cap):
        avg, filled = vwap_fill(asks, size)
        if filled < size:                      # book exhausted
            break
        ev = ev_per_share(p, avg, venue=venue, category=category, size=size)
        if ev < min_ev:                        # deeper only gets worse
            break
        best = DirectionalSignal(
            token_id=token_id, venue=venue, category=category,
            p_model=p, price=avg, size=size,
            ev_per_share=ev, expected_profit=ev * size, kelly_size=k_cap)
        size += step
    return best


if __name__ == "__main__":
    # synthetic weather market: model says 12% for an outcome asked at 0.04
    asks = [(0.04, 200.0), (0.06, 400.0), (0.09, 1000.0)]
    model = lambda tok: 0.12

    sig = find_signal("tok-rain", asks, venue="polymarket", category="weather",
                      prob_fn=model, bankroll=1_000.0)
    if sig:
        print(f"signal : p={sig.p_model:.2f} vwap={sig.price:.3f} "
              f"size={sig.size:.0f} (kelly cap {sig.kelly_size:.0f})")
        print(f"         ev/share={sig.ev_per_share:+.3f} "
              f"expected=${sig.expected_profit:+.2f}")

    # same book, but the model agrees with the market -> no signal
    none = find_signal("tok-rain", asks, venue="polymarket",
                       category="weather", prob_fn=lambda t: 0.045,
                       bankroll=1_000.0)
    print(f"no-edge: {none}")
