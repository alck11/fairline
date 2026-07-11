"""
fees.py — venue fee math.

Polymarket (global / on-chain), Fee Structure V2 (2026): taker-only, makers free.
    fee_usdc_per_share = rate * price * (1 - price)
    rate by category (coefficient, NOT a flat %):
        crypto                         0.072
        economics/culture/weather/oth  0.05
        finance/politics/tech/mentions 0.04
        sports                         0.03
        geopolitics / world events     0.0   (fee-free)
    -> dollar fee peaks at price=0.50 and decays toward 0/1.
       Makers (resting limit orders) pay 0 and earn rebates.
       Polymarket US regulated venue instead: flat 0.30% taker / 0.20% maker rebate.

Kalshi: bell-curve per-contract fee, rounded UP to the next cent on the ORDER:
    fee = ceil_cents( coef * contracts * price * (1 - price) )
    coef = 0.07 general ; 0.035 for a few index markets.

All prices are in [0, 1]; size is in shares/contracts (1 share -> $1 at win).
"""
from __future__ import annotations
import math
from dataclasses import dataclass

POLY_RATE = {
    "crypto": 0.072,
    "economics": 0.05, "culture": 0.05, "weather": 0.05, "other": 0.05,
    "finance": 0.04, "politics": 0.04, "tech": 0.04, "mentions": 0.04,
    "sports": 0.03,
    "geopolitics": 0.0, "world": 0.0,
}
POLY_US_TAKER = 0.0030          # flat, regulated venue
KALSHI_COEF_DEFAULT = 0.07
KALSHI_COEF_INDEX = 0.035


def _ceil_cents(x: float) -> float:
    return math.ceil(round(x, 10) * 100) / 100.0


def poly_fee(size: float, price: float, category: str,
             *, maker: bool = False, us_venue: bool = False) -> float:
    """USDC taker fee for a Polymarket fill of `size` shares at `price`."""
    if maker:
        return 0.0
    if us_venue:
        return POLY_US_TAKER * size * price
    rate = POLY_RATE.get(category.lower(), 0.05)   # unknown -> conservative 0.05
    return rate * size * price * (1.0 - price)


def kalshi_fee(contracts: float, price: float, *, index_market: bool = False) -> float:
    """USDC fee for a Kalshi order of `contracts` at `price` (rounded up per order)."""
    coef = KALSHI_COEF_INDEX if index_market else KALSHI_COEF_DEFAULT
    return _ceil_cents(coef * contracts * price * (1.0 - price))


@dataclass(frozen=True)
class Leg:
    """One side of a position to be priced for fees."""
    venue: str            # 'polymarket' | 'kalshi'
    size: float           # shares / contracts
    price: float          # fill price in [0,1]
    category: str = "other"
    maker: bool = False    # only meaningful for polymarket
    us_venue: bool = False
    index_market: bool = False  # only meaningful for kalshi

    def fee(self) -> float:
        if self.venue == "polymarket":
            return poly_fee(self.size, self.price, self.category,
                            maker=self.maker, us_venue=self.us_venue)
        if self.venue == "kalshi":
            return kalshi_fee(self.size, self.price, index_market=self.index_market)
        raise ValueError(f"unknown venue {self.venue!r}")


if __name__ == "__main__":
    # sanity: the worked example from the design discussion
    poly = Leg("polymarket", 100, 0.42, "politics")     # buy 100 YES @ 0.42
    kals = Leg("kalshi",     100, 0.53)                 # buy 100 NO  @ 0.53
    cost = 100 * 0.42 + 100 * 0.53 + poly.fee() + kals.fee()
    print(f"poly fee  = ${poly.fee():.4f}")             # ~0.97
    print(f"kalshi fee= ${kals.fee():.4f}")             # ~1.75
    print(f"deployed  = ${cost:.2f}")                   # ~97.72
    print(f"net @ $100 payout = ${100 - cost:.2f}")     # ~2.28
