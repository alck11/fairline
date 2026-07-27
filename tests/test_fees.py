"""
tests/test_fees.py — acceptance tests for src/fees.py, Kalshi side.

Standalone, no pytest dependency (repo convention:
`python3 tests/test_fees.py`). No database, no network — every expected value
below is transcribed from Kalshi's own published fee tables, so these tests are
pure arithmetic and always run.

The oracle is the primary fee schedule, kalshi.com/docs/kalshi-fee-schedule.pdf
("Last updated and effective: Feb 5, 2026"), retrieved 2026-07-26 through the
Wayback snapshot of 2026-02-18 — kalshi.com answers non-browser clients with
HTTP 429, and every Wayback capture after 2026-04 archived that 429 instead of
the document. `KALSHI_TABLE_GENERAL` and `KALSHI_TABLE_INDEX` below are that
PDF's two tables typed out row for row, which is the point: they pin our
arithmetic to the venue's own numbers rather than to a re-derivation of our own
formula, so a coefficient drift or a rounding regression fails loudly here.

What these cover (ADR-0015):
  - the general 0.07 taker coefficient reproduces all 21 published rows, at
    both C=1 and C=100
  - the S&P500 / NASDAQ-100 0.035 coefficient reproduces all 21 of its rows
  - ceil-to-the-next-cent rounds at the cent scale, so a fee landing exactly on
    a cent boundary is not billed a cent high (the 100 @ $0.20 -> $1.12 case
    the published table settles)
  - maker fills are charged the 0.0175 coefficient on maker-fee-enabled series
    and nothing at all elsewhere
  - Leg actually forwards `maker` to kalshi_fee — it silently dropped it before
    ADR-0015, so every Kalshi maker leg was billed the full taker rate
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fees import (                       # noqa: E402
    KALSHI_COEF_DEFAULT, KALSHI_COEF_INDEX, KALSHI_COEF_MAKER, Leg,
    _ceil_cents, kalshi_fee,
)

# (price of 1 contract, fee for 1 contract, fee for 100 contracts)
# — "General Trading Fees Table", pages 4-5 of the schedule.
KALSHI_TABLE_GENERAL = [
    (0.01, 0.01, 0.07), (0.05, 0.01, 0.34), (0.10, 0.01, 0.63),
    (0.15, 0.01, 0.90), (0.20, 0.02, 1.12), (0.25, 0.02, 1.32),
    (0.30, 0.02, 1.47), (0.35, 0.02, 1.60), (0.40, 0.02, 1.68),
    (0.45, 0.02, 1.74), (0.50, 0.02, 1.75), (0.55, 0.02, 1.74),
    (0.60, 0.02, 1.68), (0.65, 0.02, 1.60), (0.70, 0.02, 1.47),
    (0.75, 0.02, 1.32), (0.80, 0.02, 1.12), (0.85, 0.01, 0.90),
    (0.90, 0.01, 0.63), (0.95, 0.01, 0.34), (0.99, 0.01, 0.07),
]

# — "Specific Trading Fees Table for S&P500 and NASDAQ-100 Markets",
#   pages 6-7 of the schedule.
KALSHI_TABLE_INDEX = [
    (0.01, 0.01, 0.04), (0.05, 0.01, 0.17), (0.10, 0.01, 0.32),
    (0.15, 0.01, 0.45), (0.20, 0.01, 0.56), (0.25, 0.01, 0.66),
    (0.30, 0.01, 0.74), (0.35, 0.01, 0.80), (0.40, 0.01, 0.84),
    (0.45, 0.01, 0.87), (0.50, 0.01, 0.88), (0.55, 0.01, 0.87),
    (0.60, 0.01, 0.84), (0.65, 0.01, 0.80), (0.70, 0.01, 0.74),
    (0.75, 0.01, 0.66), (0.80, 0.01, 0.56), (0.85, 0.01, 0.45),
    (0.90, 0.01, 0.32), (0.95, 0.01, 0.17), (0.99, 0.01, 0.04),
]


def test_general_table_matches_published_schedule():
    """All 21 published rows, both order sizes, against the 0.07 coefficient."""
    for price, fee_1, fee_100 in KALSHI_TABLE_GENERAL:
        got_1 = kalshi_fee(1, price)
        got_100 = kalshi_fee(100, price)
        assert got_1 == fee_1, (
            f"1 contract @ ${price}: schedule says ${fee_1}, got ${got_1}")
        assert got_100 == fee_100, (
            f"100 contracts @ ${price}: schedule says ${fee_100}, got ${got_100}")


def test_index_table_matches_published_schedule():
    """The S&P500 / NASDAQ-100 table, against the 0.035 coefficient."""
    for price, fee_1, fee_100 in KALSHI_TABLE_INDEX:
        got_1 = kalshi_fee(1, price, index_market=True)
        got_100 = kalshi_fee(100, price, index_market=True)
        assert got_1 == fee_1, (
            f"1 index contract @ ${price}: schedule says ${fee_1}, got ${got_1}")
        assert got_100 == fee_100, (
            f"100 index contracts @ ${price}: schedule says ${fee_100}, "
            f"got ${got_100}")


def test_ceil_cents_does_not_overcharge_on_an_exact_boundary():
    """A fee landing exactly on a cent must not round up to the next one.

    Rounding in dollars before scaling to cents (the pre-ADR-0015 form) billed
    100 @ $0.20 as $1.13 because 0.07*100*0.20*0.80 is 1.1200000000000003 in
    binary floating point. The published table says $1.12. Checked here on the
    two prices where the general coefficient produces an exact cent, plus a
    direct assertion on _ceil_cents itself so the intent survives a refactor."""
    assert kalshi_fee(100, 0.20) == 1.12
    assert kalshi_fee(100, 0.80) == 1.12
    assert _ceil_cents(1.1200000000000003) == 1.12
    assert _ceil_cents(0.63) == 0.63
    # and it must still round genuinely fractional cents UP, not to nearest
    assert _ceil_cents(0.3325) == 0.34
    assert _ceil_cents(0.0001) == 0.01
    assert _ceil_cents(0.0) == 0.0


def test_ceil_cents_never_undercharges_across_a_grid():
    """Whatever the rounding does, the charged fee must always be >= the exact
    fee and less than a cent above it. This is the property the boundary fix
    could plausibly have broken in the other direction."""
    for contracts in (1, 10, 25, 50, 100, 200, 421, 500, 1000):
        for i in range(1, 100):
            price = i / 100
            exact = KALSHI_COEF_DEFAULT * contracts * price * (1.0 - price)
            charged = kalshi_fee(contracts, price)
            assert charged >= exact - 1e-9, (
                f"C={contracts} P={price}: charged ${charged} < exact ${exact}")
            assert charged - exact < 0.01 + 1e-9, (
                f"C={contracts} P={price}: charged ${charged} is more than a "
                f"cent above exact ${exact}")
            assert math.isclose(charged * 100, round(charged * 100), abs_tol=1e-6), (
                f"C={contracts} P={price}: ${charged} is not a whole number of cents")


def test_maker_is_a_quarter_of_taker_on_maker_fee_markets():
    """The schedule states maker as 0.0175 against taker's 0.07. Compared
    pre-rounding, because ceil-to-cent destroys the ratio on small orders."""
    assert KALSHI_COEF_MAKER == 0.25 * KALSHI_COEF_DEFAULT
    # 10,000 contracts @ $0.50 — big enough that rounding is negligible
    taker = kalshi_fee(10_000, 0.50)
    maker = kalshi_fee(10_000, 0.50, maker=True)
    assert taker == 175.0, f"taker: expected $175.00, got ${taker}"
    assert maker == 43.75, f"maker: expected $43.75, got ${maker}"
    assert math.isclose(maker / taker, 0.25), (
        f"maker should be 25% of taker, got {maker / taker:.4f}")


def test_maker_is_free_on_markets_without_maker_fees():
    """Most of the catalog: a resting fill that is not on Kalshi's maker-fee
    list pays nothing. Taker on the same market is unaffected."""
    assert kalshi_fee(100, 0.50, maker=True, maker_fee_enabled=False) == 0.0
    assert kalshi_fee(1, 0.97, maker=True, maker_fee_enabled=False) == 0.0
    assert kalshi_fee(100, 0.50, maker=False, maker_fee_enabled=False) == 1.75


def test_maker_defaults_to_charged_not_free():
    """The conservative default: absent a per-series fact, assume the fee
    applies, so the default can never invent edge that isn't there."""
    assert kalshi_fee(100, 0.50, maker=True) == kalshi_fee(
        100, 0.50, maker=True, maker_fee_enabled=True)
    assert kalshi_fee(100, 0.50, maker=True) > 0.0


def test_index_maker_uses_the_documented_maker_coefficient():
    """The schedule gives S&P500/NASDAQ-100 no maker table of its own, so we
    charge the documented 0.0175 rather than a quartered 0.00875 — the literal
    reading, and the conservative one (ADR-0015 open question)."""
    assert kalshi_fee(10_000, 0.50, maker=True, index_market=True) == 43.75
    assert kalshi_fee(10_000, 0.50, index_market=True) == 87.5
    assert KALSHI_COEF_INDEX == 0.035


def test_leg_forwards_maker_to_kalshi_fee():
    """The ADR-0015 regression: Leg.fee() dropped `maker` on the Kalshi branch,
    so every resting Kalshi fill was billed the full taker rate — a 4x
    overstatement on maker-fee markets and an infinite one elsewhere."""
    taker_leg = Leg("kalshi", 10_000, 0.50)
    maker_leg = Leg("kalshi", 10_000, 0.50, maker=True)
    free_leg = Leg("kalshi", 10_000, 0.50, maker=True, maker_fee_enabled=False)

    assert taker_leg.fee() == 175.0
    assert maker_leg.fee() == 43.75, (
        f"Leg is not forwarding maker=True: got ${maker_leg.fee()}, expected "
        f"$43.75 (it returns the taker ${taker_leg.fee()} when the flag is "
        f"dropped)")
    assert maker_leg.fee() < taker_leg.fee()
    assert free_leg.fee() == 0.0


def test_leg_index_and_maker_compose():
    """index_market and maker are independent axes and both reach the fee."""
    assert Leg("kalshi", 10_000, 0.50, index_market=True).fee() == 87.5
    assert Leg("kalshi", 10_000, 0.50, maker=True,
               index_market=True).fee() == 43.75


def test_polymarket_leg_is_unaffected():
    """The Kalshi change must not disturb the Polymarket branch: makers there
    are free venue-wide, and maker_fee_enabled is a Kalshi-only field."""
    assert Leg("polymarket", 100, 0.42, "politics").fee() > 0.0
    assert Leg("polymarket", 100, 0.42, "politics", maker=True).fee() == 0.0
    # maker_fee_enabled is ignored entirely off Kalshi
    assert Leg("polymarket", 100, 0.42, "politics", maker=True,
               maker_fee_enabled=False).fee() == 0.0


def main() -> int:
    tests = [
        test_general_table_matches_published_schedule,
        test_index_table_matches_published_schedule,
        test_ceil_cents_does_not_overcharge_on_an_exact_boundary,
        test_ceil_cents_never_undercharges_across_a_grid,
        test_maker_is_a_quarter_of_taker_on_maker_fee_markets,
        test_maker_is_free_on_markets_without_maker_fees,
        test_maker_defaults_to_charged_not_free,
        test_index_maker_uses_the_documented_maker_coefficient,
        test_leg_forwards_maker_to_kalshi_fee,
        test_leg_index_and_maker_compose,
        test_polymarket_leg_is_unaffected,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")

    passed = len(tests) - failures
    if failures:
        print(f"\n{passed} passed, {failures} failed")
        return 1
    print(f"\n{passed} passed, 0 failed — ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
