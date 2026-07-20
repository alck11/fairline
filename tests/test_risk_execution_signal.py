"""
tests/test_risk_execution_signal.py — WP-4 unit tests for the additive
Engine.execute_signal method (src/risk_execution.py).

Standalone, no pytest dependency, no database, no network (repo convention:
`python3 tests/test_risk_execution_signal.py`). Exits non-zero on the first
failed assertion, prints "ALL PASSED" otherwise.

Traces to docs/architecture/plan.md WP-4 outputs/acceptance:
  - execute_signal routes a DirectionalSignal through _check + _fill and
    records to the blotter (status filled/rejected, entry-time pnl 0.0)
  - the per-trade notional cap, open-exposure cap and kill switch all gate it
  - it never touches the copy-trade wallet allocation state
  - a fill increases open_exposure by price*size; a rejection changes nothing
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ev_detector import DirectionalSignal  # noqa: E402
from risk_execution import Engine, RiskLimits  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _signal(price=0.40, size=100.0) -> DirectionalSignal:
    return DirectionalSignal(
        token_id="TOK-YES", venue="kalshi", category="weather",
        p_model=0.80, price=price, size=size,
        ev_per_share=0.35, expected_profit=0.35 * size, kelly_size=400.0)


def test_fill_records_and_updates_exposure():
    eng = Engine(RiskLimits())
    sig = _signal(price=0.40, size=100.0)
    row = eng.execute_signal(sig, category="weather")
    check(row["status"] == "filled", f"expected filled, got {row['status']}: {row['notes']}")
    check(row["realized_pnl"] == 0.0, "entry-time realized pnl must be 0.0 (hold-to-resolution)")
    check(abs(eng.state.open_exposure - 40.0) < 1e-9,
          f"open_exposure must grow by price*size=40, got {eng.state.open_exposure}")
    leg = row["legs"][0]
    check(leg["token_id"] == "TOK-YES" and leg["side"] == "buy"
          and leg["category"] == "weather" and leg["filled"] == 100.0,
          f"blotter leg malformed: {leg}")
    check(eng.blotter[-1] is row, "the returned row must be the appended blotter row")


def test_notional_cap_rejects():
    eng = Engine(RiskLimits(max_trade_notional=30.0))
    row = eng.execute_signal(_signal(price=0.40, size=100.0), category="weather")
    check(row["status"] == "rejected", f"notional 40 > cap 30 must reject, got {row['status']}")
    check("notional" in row["notes"], f"rejection reason must name the cap: {row['notes']}")
    check(eng.state.open_exposure == 0.0, "a rejection must not change exposure")


def test_exposure_cap_rejects():
    eng = Engine(RiskLimits(max_trade_notional=500.0, max_open_exposure=70.0))
    first = eng.execute_signal(_signal(price=0.40, size=100.0), category="weather")
    check(first["status"] == "filled", "first entry (notional 40) must fill under cap 70")
    second = eng.execute_signal(_signal(price=0.40, size=100.0), category="weather")
    check(second["status"] == "rejected",
          f"second entry would take exposure to 80 > 70, got {second['status']}")
    check("exposure" in second["notes"], f"reason must name exposure: {second['notes']}")


def test_kill_switch_gates_entries():
    eng = Engine(RiskLimits(daily_loss_limit=100.0))
    eng.settle(-150.0)
    check(eng.state.kill is True, "settle past the daily loss limit must trip the kill switch")
    row = eng.execute_signal(_signal(), category="weather")
    check(row["status"] == "rejected", f"kill switch must gate directional entries: {row}")
    check("kill switch" in row["notes"], f"reason must name the kill switch: {row['notes']}")
    check(eng.state.open_exposure == 0.0, "a kill-gated entry must not change exposure")


def test_wallet_state_untouched():
    eng = Engine(RiskLimits())
    eng.execute_signal(_signal(), category="weather")
    check(eng.state.wallet_alloc == {},
          f"directional entries have no wallet dimension: {eng.state.wallet_alloc}")


def main() -> int:
    tests = [
        test_fill_records_and_updates_exposure,
        test_notional_cap_rejects,
        test_exposure_cap_rejects,
        test_kill_switch_gates_entries,
        test_wallet_state_untouched,
    ]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
