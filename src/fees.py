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

    Coefficients, quoted verbatim from the primary fee schedule
    (kalshi.com/docs/kalshi-fee-schedule.pdf, "Last updated and effective:
    Feb 5, 2026", retrieved 2026-07-26 via the Wayback snapshot — kalshi.com
    itself returns HTTP 429 to non-browser clients, and every Wayback capture
    after 2026-04 archived that 429 rather than the document):

        taker (general)  fees = round up(0.07   x C x P x (1-P))
        maker            fees = round up(0.0175 x C x P x (1-P))   (25% of taker)
        S&P500 / NASDAQ-100
                         fees = round up(0.035  x C x P x (1-P))
            -> "all iterations of the S&P500 and Nasdaq-100 markets", i.e.
               Rulebook tickers beginning INX (INXD/INXW/INXM/INXY/INXU/...)
               or NASDAQ100 (NASDAQ100D/W/M/Y/U/...). That 0.035 is a
               *coefficient*, not a per-contract cap; the schedule contains no
               cap of any kind, and the "$0.035/contract cap" recorded in
               docs/research/2026-07-17-polymarket-edge-landscape.md is that
               coefficient garbled (see ADR-0015).

    MAKER FEES ARE NOT UNIVERSAL. The schedule is explicit: trading fees "are
    not charged for orders placed that are not immediately matched and are
    instead left as resting orders on the orderbook *unless they are included
    in our Maker Fees section*", and points at kalshi.com/fee-schedule for the
    current list of which markets those are. So a resting fill pays 0.0175 on a
    maker-fee-enabled series and *zero* everywhere else. `maker_fee_enabled`
    below carries that per-market fact; it defaults to True (charge the fee)
    because the conservative default must never manufacture edge that isn't
    there — a caller who has checked the series list should pass False to get
    the true number.

    Not modelled, deliberately: Kalshi reimburses maker rounding excess monthly
    when it exceeds $10. That is a rebate, so ignoring it overstates cost, and
    at this project's bankroll it would essentially never trigger.

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
# The schedule states the maker formula once, at 0.0175, without giving
# S&P500/NASDAQ-100 a maker table of its own -- so whether an index maker pays
# 0.0175 or a quartered 0.00875 is genuinely undocumented. We charge the
# documented 0.0175. That is both the literal reading and the conservative one,
# so the ambiguity cannot cost us edge (ADR-0015 open question).
KALSHI_COEF_MAKER = 0.0175


def _ceil_cents(x: float) -> float:
    """Round a dollar amount UP to the next whole cent.

    The rounding happens at the *cent* scale, not the dollar scale. Rounding in
    dollars first (`math.ceil(round(x, 10) * 100)`) looks equivalent and is not:
    a fee that lands exactly on a cent boundary comes out one cent too high,
    because the tidied dollar value is still not exactly representable and
    multiplying it by 100 lands just above the integer. The concrete case, which
    Kalshi's own published table contradicts, is 100 contracts at $0.20 --
    0.07 * 100 * 0.20 * 0.80 is 1.1200000000000003, the old form billed $1.13,
    the schedule says $1.12. Eight of 891 (contracts, price) grid cells over
    C in {1,10,25,50,100,200,421,500,1000} were affected, all of them exact
    boundaries. See tests/test_fees.py, which pins every row of both published
    tables."""
    return math.ceil(round(x * 100.0, 9)) / 100.0


def poly_fee(size: float, price: float, category: str,
             *, maker: bool = False, us_venue: bool = False) -> float:
    """USDC taker fee for a Polymarket fill of `size` shares at `price`."""
    if maker:
        return 0.0
    if us_venue:
        return POLY_US_TAKER * size * price
    rate = POLY_RATE.get(category.lower(), 0.05)   # unknown -> conservative 0.05
    return rate * size * price * (1.0 - price)


def kalshi_fee(contracts: float, price: float, *, maker: bool = False,
               index_market: bool = False,
               maker_fee_enabled: bool = True) -> float:
    """USDC fee for a Kalshi order of `contracts` at `price` (rounded up per order).

    `maker=True` prices a resting order that was filled rather than one that
    crossed the spread. `maker_fee_enabled` says whether this market is on
    Kalshi's maker-fee list (see module docstring): a resting fill on a market
    that is *not* on that list is free, which is most of the catalog. Both are
    ignored when `maker=False`.

    `index_market=True` selects the S&P500 / NASDAQ-100 coefficient, i.e. for
    tickers beginning INX or NASDAQ100."""
    if maker and not maker_fee_enabled:
        return 0.0
    if maker:
        coef = KALSHI_COEF_MAKER
    else:
        coef = KALSHI_COEF_INDEX if index_market else KALSHI_COEF_DEFAULT
    return _ceil_cents(coef * contracts * price * (1.0 - price))


@dataclass(frozen=True)
class Leg:
    """One side of a position to be priced for fees."""
    venue: str            # 'polymarket' | 'kalshi'
    size: float           # shares / contracts
    price: float          # fill price in [0,1]
    category: str = "other"
    maker: bool = False    # resting fill, not a spread cross -- both venues
    us_venue: bool = False
    index_market: bool = False  # only meaningful for kalshi
    # only meaningful for kalshi, and only when maker=True: is this series on
    # Kalshi's maker-fee list? Defaults to charging the fee (module docstring).
    maker_fee_enabled: bool = True

    def fee(self) -> float:
        if self.venue == "polymarket":
            return poly_fee(self.size, self.price, self.category,
                            maker=self.maker, us_venue=self.us_venue)
        if self.venue == "kalshi":
            return kalshi_fee(self.size, self.price, maker=self.maker,
                              index_market=self.index_market,
                              maker_fee_enabled=self.maker_fee_enabled)
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
