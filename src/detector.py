"""
detector.py — fee-aware edge functions for the two arb shapes.

Edge is expressed two ways:
  * net_edge  : guaranteed profit per $1 of payout (i.e. per complete set of size 1)
  * roi       : net profit / capital actually deployed

Key design choices
  * Fees are computed on the WHOLE order size (Kalshi rounds per order), so
    edge functions take `size`, not just price.
  * We are realistic about depth: filling more size walks UP the ask, so we
    simulate VWAP fills against the book and find the profit-MAXIMIZING size,
    not the maximum feasible size. A 5% top-of-book edge can go negative by
    the time you've filled real volume.
  * A safety buffer (`min_roi`) keeps you off the breakeven line where
    slippage / partial fills live.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
from fees import Leg


# ---------------------------------------------------------------------------
# order-book fill simulation
# ---------------------------------------------------------------------------
Level = tuple[float, float]   # (price, size_available)


def vwap_fill(asks: Sequence[Level], target: float) -> tuple[float, float]:
    """Walk the ask side to buy `target` shares.

    Returns (avg_price, filled). `filled` < target means the book is too thin.
    `asks` must be sorted by ascending price.
    """
    filled, cost = 0.0, 0.0
    for price, avail in asks:
        if filled >= target:
            break
        take = min(avail, target - filled)
        cost += take * price
        filled += take
    avg = cost / filled if filled > 0 else float("nan")
    return avg, filled


@dataclass
class Opportunity:
    kind: str                      # 'complete_set' | 'cross_venue'
    size: float
    gross_edge: float              # per $1 payout, pre-fee
    total_fees: float
    net_profit: float              # absolute USDC, for `size`
    roi: float
    legs: list[dict] = field(default_factory=list)

    @property
    def net_edge(self) -> float:   # per $1 payout, post-fee
        return self.net_profit / self.size if self.size else 0.0


# ---------------------------------------------------------------------------
# core edge calculators (single size)
# ---------------------------------------------------------------------------
def _profit_for_legs(legs: list[Leg], size: float) -> tuple[float, float, float]:
    """Given legs that together guarantee a $`size` payout, return
    (deployed, fees, net_profit)."""
    deployed = sum(l.size * l.price for l in legs)
    fees = sum(l.fee() for l in legs)
    net = size - deployed - fees       # exactly one $1/share leg pays out
    return deployed, fees, net


def cross_venue_edge(size: float, *,
                     yes_venue: str, yes_price: float, yes_cat: str,
                     no_venue: str,  no_price: float,  no_cat: str,
                     yes_maker: bool = False, no_maker: bool = False
                     ) -> Opportunity:
    """Buy YES on one venue, NO on the other; one side must pay $1."""
    legs = [
        Leg(yes_venue, size, yes_price, yes_cat, maker=yes_maker),
        Leg(no_venue,  size, no_price,  no_cat,  maker=no_maker),
    ]
    deployed, fees, net = _profit_for_legs(legs, size)
    return Opportunity(
        kind="cross_venue", size=size,
        gross_edge=1.0 - (yes_price + no_price),
        total_fees=fees, net_profit=net,
        roi=(net / deployed) if deployed else 0.0,
        legs=[{"venue": yes_venue, "side": "yes", "price": yes_price, "size": size},
              {"venue": no_venue,  "side": "no",  "price": no_price,  "size": size}],
    )


def complete_set_edge(size: float, *, venue: str, category: str,
                      prices: Sequence[float],
                      maker: bool | Sequence[bool] = False) -> Opportunity:
    """Buy one share of every outcome of a market, all on the SAME venue
    (sum of asks < $1). Exactly one outcome pays $1, so the venue itself
    guarantees settlement. Binary markets are just the size-2 case:
    `prices=[yes_price, no_price]` — there is no separate shape for
    binary vs. N-outcome, only the number of legs differs.

    `maker` is a single bool (applied to every leg) or one bool per leg
    (resting limit orders on Polymarket are fee-free and rebate-earning;
    see fees.py) — a within-venue complete set can mix resting and taker
    legs same as the old bundle_edge could."""
    if not prices:
        raise ValueError("complete_set_edge requires at least one price")
    makers = [maker] * len(prices) if isinstance(maker, bool) else list(maker)
    if len(makers) != len(prices):
        raise ValueError(
            f"maker has {len(makers)} entries but prices has {len(prices)}")
    legs = [Leg(venue, size, p, category, maker=m)
            for p, m in zip(prices, makers)]
    deployed, fees, net = _profit_for_legs(legs, size)
    return Opportunity(
        kind="complete_set", size=size,
        gross_edge=1.0 - sum(prices),
        total_fees=fees, net_profit=net,
        roi=(net / deployed) if deployed else 0.0,
        legs=[{"venue": venue, "side": f"out{i}", "price": p, "size": size,
               "maker": m}
              for i, (p, m) in enumerate(zip(prices, makers))],
    )


# ---------------------------------------------------------------------------
# depth-aware: find the size that MAXIMIZES net profit
# ---------------------------------------------------------------------------
def best_cross_venue_size(yes_book: Sequence[Level], no_book: Sequence[Level], *,
                          yes_venue: str, no_venue: str,
                          yes_cat: str, no_cat: str,
                          min_roi: float = 0.01,
                          step: float = 10.0,
                          max_size: float = 10_000.0) -> Opportunity | None:
    """Sweep size in `step` increments, repricing both legs at their VWAP fill,
    and return the most profitable Opportunity whose roi >= min_roi.

    Returns None if no size clears the buffer (the common case)."""
    best: Opportunity | None = None
    size = step
    while size <= max_size:
        yes_avg, yf = vwap_fill(yes_book, size)
        no_avg,  nf = vwap_fill(no_book,  size)
        if yf < size or nf < size:        # book exhausted -> stop growing
            break
        opp = cross_venue_edge(size,
                               yes_venue=yes_venue, yes_price=yes_avg, yes_cat=yes_cat,
                               no_venue=no_venue,   no_price=no_avg,   no_cat=no_cat)
        if opp.roi >= min_roi and (best is None or opp.net_profit > best.net_profit):
            best = opp
        size += step
    return best


if __name__ == "__main__":
    # complete_set: buy every outcome on ONE venue for less than $1 (binary
    # case here is just prices=[yes, no] — same shape as any N-outcome market).
    cs = complete_set_edge(100, venue="polymarket", category="politics",
                           prices=[0.42, 0.53])
    print(f"complete_set: kind={cs.kind!r}  roi={cs.roi:6.2%}  net=${cs.net_profit:6.2f}")
    assert cs.kind == "complete_set"

    # resting (maker) legs pay zero Polymarket fee -> strictly more net profit
    # for the same prices than the all-taker fill above.
    cs_maker = complete_set_edge(100, venue="polymarket", category="politics",
                                 prices=[0.42, 0.53], maker=True)
    assert cs_maker.total_fees == 0.0
    assert cs_maker.net_profit > cs.net_profit
    print(f"complete_set (maker): fees=${cs_maker.total_fees:.2f}  "
          f"net=${cs_maker.net_profit:6.2f}")

    # per-leg maker flags: only the resting leg is fee-free.
    cs_mixed = complete_set_edge(100, venue="polymarket", category="politics",
                                 prices=[0.42, 0.53], maker=[True, False])
    assert cs.total_fees > cs_mixed.total_fees > cs_maker.total_fees

    # empty legs must error, not silently report a fake full-notional profit.
    try:
        complete_set_edge(100, venue="polymarket", category="politics", prices=[])
        raise AssertionError("expected ValueError for empty prices")
    except ValueError:
        pass

    # top-of-book looks great (5% gross) ...
    flat = cross_venue_edge(100, yes_venue="polymarket", yes_price=0.42, yes_cat="politics",
                            no_venue="kalshi", no_price=0.53, no_cat="politics")
    print(f"cross_venue : kind={flat.kind!r}  roi={flat.roi:6.2%}  net=${flat.net_profit:6.2f}")
    assert flat.kind == "cross_venue"

    # ... but thin books eat it. Depth-aware sizing tells the truth:
    yes_book = [(0.42, 60), (0.44, 80), (0.47, 200)]
    no_book  = [(0.53, 50), (0.55, 90), (0.58, 300)]
    depth = best_cross_venue_size(yes_book, no_book,
                                  yes_venue="polymarket", no_venue="kalshi",
                                  yes_cat="politics", no_cat="politics",
                                  min_roi=0.01, step=10, max_size=400)
    if depth:
        print(f"depth       : size={depth.size:.0f}  roi={depth.roi:6.2%}  "
              f"net=${depth.net_profit:6.2f}")
    else:
        print("depth       : no size clears the 1% buffer after slippage")
