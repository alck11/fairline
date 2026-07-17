"""
QA regression tests for WP-4 (src/risk_execution.py: consensus_gate / execute_copy).

Standalone, no pytest dependency (matches repo convention: run directly with
`python3 tests/test_risk_execution_consensus.py`). Exits non-zero on first
failed assertion, prints "ALL PASSED" if everything the spec requires holds.

Traces to docs/architecture/plan.md WP-4 acceptance criteria:
  - 1-of-1 participation is rejected (below floor)
  - 4-of-5 agreeing passes
  - 3-of-8 (whole-basket denom would fail) still evaluated on participants
  - floor comparison is participant_count < min_participation (inclusive floor)
  - consensus comparison is agreement < basket_consensus (inclusive gate)

Also covers inputs the spec does not explicitly enumerate, including two
follow-up fixes (2026-07-17) for behavior QA had originally flagged and left
unfixed:
  - participant_count == 0, including with min_participation == 0 ("no
    floor") -- now returns gracefully instead of raising ZeroDivisionError.
  - agree_count > participant_count, participant_count > basket_size, and
    negative counts -- now raise ValueError instead of being silently
    accepted as a legitimate (if malformed) basket.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from risk_execution import consensus_gate, RiskLimits  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_plan_acceptance_scenarios():
    L = RiskLimits()  # defaults: basket_consensus=0.80, min_participation=3
    ok, agreement, reason = consensus_gate(1, 1, 10, L)
    check(ok is False, f"1-of-1 must be rejected (floor breach), got {ok!r}/{reason!r}")

    ok, agreement, reason = consensus_gate(4, 5, 10, L)
    check(ok is True, f"4-of-5 must pass, got {ok!r}/{reason!r}")
    check(abs(agreement - 0.8) < 1e-9, f"4-of-5 agreement should be 0.8, got {agreement}")

    # 3-of-8 basket, all 3 participants agree: whole-basket denominator (3/8=0.375)
    # would fail the 0.80 gate, but participant-denominator (3/3=1.0) must pass.
    ok, agreement, reason = consensus_gate(3, 3, 8, L)
    check(ok is True, f"3-of-8 (3/3 participants) must pass, got {ok!r}/{reason!r}")
    check(abs(agreement - 1.0) < 1e-9, f"3/3 agreement should be 1.0, got {agreement}")


def test_floor_boundary_is_inclusive():
    L = RiskLimits(min_participation=3, basket_consensus=0.80)
    # participant_count == floor exactly must NOT be rejected by the floor check
    # (only by the consensus gate, if agreement is too low).
    ok, agreement, reason = consensus_gate(3, 3, 8, L)
    check(ok is True, f"participant_count == min_participation must pass floor, got {reason!r}")

    ok, agreement, reason = consensus_gate(0, 3, 8, L)
    check("floor" not in reason, f"participant_count==floor must not be floor-rejected, got {reason!r}")
    check(ok is False, "0/3 agreement should still fail the consensus gate")

    # one below the floor must be rejected regardless of 100% agreement
    ok, agreement, reason = consensus_gate(2, 2, 8, L)
    check(ok is False and "floor" in reason,
          f"participant_count == floor-1 with 100% agreement must still be floor-rejected, got {ok!r}/{reason!r}")


def test_consensus_boundary_is_inclusive():
    L = RiskLimits(min_participation=3, basket_consensus=0.80)
    # agreement exactly == basket_consensus must PASS (>=), not fail.
    ok, agreement, reason = consensus_gate(4, 5, 10, L)  # 0.80 exactly
    check(ok is True, f"agreement == basket_consensus (0.80) must pass, got {ok!r}/{reason!r}")

    # one unit of agreement short of the gate must fail
    ok, agreement, reason = consensus_gate(3, 5, 10, L)  # 0.60
    check(ok is False, f"agreement 0.60 < 0.80 must fail, got {ok!r}/{reason!r}")


def test_participant_count_zero_with_default_limits_is_safe():
    L = RiskLimits()  # min_participation=3 by default
    ok, agreement, reason = consensus_gate(0, 0, 10, L)
    check(ok is False, "0 participants must be rejected")
    check(agreement == 0.0, "agreement should default to 0.0 on floor rejection")


def test_zero_participants_is_safe_even_with_no_floor():
    """
    Fixed (was: KNOWN BUG). consensus_gate now has an explicit
    `participant_count == 0` guard independent of the floor comparison, so a
    caller configuring RiskLimits(min_participation=0) -- "no participation
    floor" -- no longer hits participant_count=0 falling through the floor
    check (0 < 0 is False) into `agree_count / participant_count` and raising
    ZeroDivisionError. It now returns a graceful (False, 0.0, reason) tuple.
    """
    L = RiskLimits(min_participation=0)
    ok, agreement, reason = consensus_gate(0, 0, 10, L)
    check(ok is False, f"0 participants must still be rejected even with no floor, got {ok!r}")
    check(agreement == 0.0, f"agreement should be 0.0, got {agreement}")
    check("participant" in reason, f"reason should mention participants, got {reason!r}")


def test_inconsistent_counts_raise_value_error():
    """
    Fixed (was: documented-not-fixed). consensus_gate now validates that
    agree_count <= participant_count <= basket_size and that no count is
    negative -- these shapes can only come from an upstream counting bug, so
    they now raise ValueError instead of being silently gated as if they were
    a legitimate (if malformed) basket.
    """
    L = RiskLimits()

    try:
        consensus_gate(5, 3, 10, L)  # agree_count > participant_count
        raise AssertionError("expected ValueError for agree_count > participant_count")
    except ValueError:
        pass

    try:
        consensus_gate(12, 15, 10, L)  # participant_count > basket_size
        raise AssertionError("expected ValueError for participant_count > basket_size")
    except ValueError:
        pass

    try:
        consensus_gate(-1, 3, 10, L)  # negative count
        raise AssertionError("expected ValueError for negative agree_count")
    except ValueError:
        pass


if __name__ == "__main__":
    tests = [
        test_plan_acceptance_scenarios,
        test_floor_boundary_is_inclusive,
        test_consensus_boundary_is_inclusive,
        test_participant_count_zero_with_default_limits_is_safe,
        test_zero_participants_is_safe_even_with_no_floor,
        test_inconsistent_counts_raise_value_error,
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

    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nALL PASSED")
