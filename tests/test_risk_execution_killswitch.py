"""
QA regression tests for WP-5 (src/risk_execution.py: kill switch latches in
live mode).

Standalone, no pytest dependency (matches repo convention: run directly with
`python3 tests/test_risk_execution_killswitch.py`). Exits non-zero on first
failed assertion, prints "ALL PASSED" if everything the spec requires holds.

Traces to docs/architecture/plan.md WP-5 acceptance criteria and ADR-0001 /
CONTEXT.md's "Kill switch" glossary entry:
  - paper engine: kill switch auto-clears at the (simulated) UTC day roll
  - live engine: kill switch stays set across the day roll -- only an
    explicit Engine.rearm() call clears it
  - _roll_day still resets realized_today in live mode even though it leaves
    `kill` untouched (the day-roll bookkeeping isn't fully skipped, only the
    kill-switch auto-clear is)
  - rearm() clears `kill` unconditionally, including in paper mode

Also covers the WP-5 follow-up fix (2026-07-17): rearm() previously had no
audit trail and no limit on how many times it could be called per day, so a
human could loop settle(loss)+rearm() to absorb unbounded daily loss past
`daily_loss_limit`. rearm() now logs every call (blocked or not) with the
masked-loss amount, and RiskLimits.max_rearms_per_day (default 1) caps
successful rearms per calendar day, raising RuntimeError once exhausted.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from risk_execution import Engine, RiskLimits  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _trip_and_roll(mode: str, day_after_roll: str = "2000-01-01") -> Engine:
    """Build an engine in `mode`, trip its kill switch, then back-date
    RiskState._day so the next _roll_day()-triggering call sees a new day.
    """
    eng = Engine(RiskLimits(daily_loss_limit=100), mode=mode)
    eng.settle(-150.0)
    check(eng.state.kill is True, f"{mode}: kill switch must trip past the daily loss limit")
    eng.state._day = day_after_roll
    return eng


def test_paper_auto_resets_kill_at_day_roll():
    eng = _trip_and_roll("paper")
    eng.settle(0.0)  # any call that reaches _roll_day
    check(eng.state.kill is False, "paper mode must auto-clear kill at the day roll")


def test_live_latches_kill_across_day_roll():
    eng = _trip_and_roll("live")
    eng.settle(0.0)
    check(eng.state.kill is True, "live mode must NOT auto-clear kill at the day roll")


def test_live_day_roll_still_resets_realized_today():
    """The day roll's other bookkeeping (realized_today reset) must still run
    in live mode -- only the kill-switch auto-clear is paper-only."""
    eng = Engine(RiskLimits(daily_loss_limit=100), mode="live")
    eng.settle(-150.0)
    check(eng.state.realized_today == -150.0, "sanity: realized_today should reflect the loss")
    eng.state._day = "2000-01-01"
    eng.settle(0.0)
    check(eng.state.realized_today == 0.0,
          f"live day roll must still reset realized_today, got {eng.state.realized_today}")
    check(eng.state.kill is True, "kill must remain latched even though realized_today reset")


def test_rearm_clears_kill_in_live_mode():
    eng = _trip_and_roll("live")
    eng.settle(0.0)
    check(eng.state.kill is True, "sanity: still latched before rearm()")
    eng.rearm()
    check(eng.state.kill is False, "rearm() must clear kill in live mode")


def test_rearm_also_works_in_paper_mode():
    """rearm() is a human action available in both modes for consistency and
    testability, even though paper doesn't need it in normal unattended use."""
    eng = Engine(RiskLimits(daily_loss_limit=100), mode="paper")
    eng.settle(-150.0)
    check(eng.state.kill is True, "sanity: kill tripped in paper mode")
    eng.rearm()
    check(eng.state.kill is False, "rearm() must also clear kill in paper mode")


def test_rearm_resets_realized_today_so_it_does_not_self_relatch():
    """QA-reported bug: rearm() cleared `kill` but left the stale, deeply
    negative `realized_today` in place. The very next settle() -- even one
    settling a brand-new profit, same day, no roll involved -- re-evaluated
    `realized_today <= -daily_loss_limit` against that stale value and
    immediately re-tripped `kill`. rearm() must reset realized_today (the same
    "start the day's loss accounting fresh" semantic a day roll applies) so a
    rearmed engine stays rearmed until a NEW loss independently crosses the
    threshold from that point forward.
    """
    eng = Engine(RiskLimits(daily_loss_limit=100), mode="live")
    eng.settle(-500.0)
    check(eng.state.kill is True, "sanity: kill trips on the big loss")

    eng.rearm()
    check(eng.state.kill is False, "sanity: rearm() clears kill")
    check(eng.state.realized_today == 0.0,
          f"rearm() must reset realized_today, got {eng.state.realized_today}")

    ok, why = eng._check(10.0, wallet=None)
    check(ok is True, f"entries must be allowed right after rearm(), got {ok!r}/{why!r}")

    eng.settle(1.0)  # settle a tiny PROFIT, same calendar day, no roll
    check(eng.state.kill is False,
          f"BUG: settling a profit after rearm() must not re-latch kill, got {eng.state.kill!r}")


def test_live_kill_blocks_new_entries_until_rearmed():
    """End-to-end: a tripped, latched kill switch in live mode must actually
    reject new trades via _check(), not just flip a flag nobody reads."""
    eng = Engine(RiskLimits(daily_loss_limit=100), mode="live")
    eng.settle(-150.0)
    ok, why = eng._check(10.0, wallet=None)
    check(ok is False and "kill switch" in why, f"tripped kill must reject entries, got {ok!r}/{why!r}")

    eng.state._day = "2000-01-01"
    ok, why = eng._check(10.0, wallet=None)  # this call itself triggers the day roll
    check(ok is False and "kill switch" in why,
          f"live kill must still reject entries after a day roll, got {ok!r}/{why!r}")

    eng.rearm()
    ok, why = eng._check(10.0, wallet=None)
    check(ok is True, f"after rearm(), entries must be allowed again, got {ok!r}/{why!r}")


def test_rearm_logs_masked_loss_to_the_blotter():
    """Every rearm() call must leave an audit row recording the realized_today
    value it's about to zero out and whether kill was actually set -- this is
    the previously-missing observability the WP-5 follow-up flagged."""
    eng = Engine(RiskLimits(daily_loss_limit=100), mode="live")
    eng.settle(-150.0)
    row = eng.rearm()
    check(row["status"] == "rearm", f"expected status 'rearm', got {row['status']!r}")
    check("masked loss $-150.00" in row["notes"],
          f"rearm() log must record the masked realized_today, got {row['notes']!r}")
    check("kill was set" in row["notes"],
          f"rearm() log must record kill was actually tripped, got {row['notes']!r}")
    check(row in eng.blotter, "rearm() audit row must land in the blotter")


def test_rearm_beyond_daily_cap_raises_and_leaves_state_untouched():
    """RiskLimits.max_rearms_per_day (default 1) caps successful rearms per
    calendar day. A second same-day rearm() must raise RuntimeError rather
    than silently no-op -- so a human hitting the cap notices instead of
    assuming the switch cleared -- and must not further mutate state."""
    eng = Engine(RiskLimits(daily_loss_limit=100), mode="live")
    eng.settle(-150.0)
    eng.rearm()  # first rearm today: allowed (cap defaults to 1)
    check(eng.state.kill is False, "sanity: first rearm() succeeds")

    eng.settle(-150.0)  # trip it again, same day
    check(eng.state.kill is True, "sanity: kill re-trips on a second big loss")

    try:
        eng.rearm()
        raise AssertionError("expected RuntimeError once max_rearms_per_day is exhausted")
    except RuntimeError:
        pass
    check(eng.state.kill is True, "blocked rearm() must leave kill latched")
    check(eng.state.realized_today == -150.0,
          f"blocked rearm() must not reset realized_today, got {eng.state.realized_today}")

    blocked_row = eng.blotter[-1]
    check(blocked_row["status"] == "rearm_blocked",
          f"blocked rearm() must still log an audit row, got {blocked_row['status']!r}")


def test_rearm_cap_resets_at_day_roll():
    """The rearm counter is a daily counter like realized_today -- it resets
    at the same UTC day roll, so a fresh day gets a fresh rearm budget."""
    eng = Engine(RiskLimits(daily_loss_limit=100, max_rearms_per_day=1), mode="live")
    eng.settle(-150.0)
    eng.rearm()
    check(eng.state.rearms_today == 1, "sanity: one rearm used today")

    eng.state._day = "2000-01-01"  # force the next roll to fire
    eng.settle(-150.0)  # this call triggers the day roll, then re-trips kill
    check(eng.state.rearms_today == 0, "rearms_today must reset at the day roll")

    eng.rearm()  # must succeed again: fresh day, fresh budget
    check(eng.state.kill is False, "rearm() must succeed on the new day's fresh budget")


if __name__ == "__main__":
    tests = [
        test_paper_auto_resets_kill_at_day_roll,
        test_live_latches_kill_across_day_roll,
        test_live_day_roll_still_resets_realized_today,
        test_rearm_clears_kill_in_live_mode,
        test_rearm_also_works_in_paper_mode,
        test_rearm_resets_realized_today_so_it_does_not_self_relatch,
        test_live_kill_blocks_new_entries_until_rearmed,
        test_rearm_logs_masked_loss_to_the_blotter,
        test_rearm_beyond_daily_cap_raises_and_leaves_state_untouched,
        test_rearm_cap_resets_at_day_roll,
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
