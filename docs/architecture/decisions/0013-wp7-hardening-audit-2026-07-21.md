# WP-7 Hardening Audit (2026-07-21)

**Status:** Complete. WP-7 calibration study code reviewed, fixed, re-reviewed, and hardened post-MVP-gate-close.

## Context

WP-7 shipped (commit d0fdf52) and passed initial review. A second full review (commit 5368650) against live Kalshi data revealed gaps in the spec parser coverage and inspector findings from earlier. This document records what was addressed and what remains as non-blocking future work.

## Findings Addressed

### 1. Self-referential PIT leak (BLOCKER → FIXED)

**Finding:** A market's own settled outcome, knowable in `[observed_at(target_date), resolves_at)`, leaked into the σ/bias pool used to price it. **Status: FIXED.** `_error_stats` now takes `exclude_date` parameter (the priced market's `target_date`), and `evaluate` passes it. The one date that can leak is now excluded by design. Regression tests added and verified to fail on revert (2026-07-21).

**Code:** [src/calibration.py:175-212](../../src/calibration.py#L175-L212), [src/calibration.py:342](../../src/calibration.py#L342), tests [test_error_stats_excludes_target_date_self_leak](../../tests/test_calibration.py) + [test_evaluate_verdict_unaffected_by_target_self_obs](../../tests/test_calibration.py).

**Impact:** Critical for gate credibility — the study's verdict can no longer depend on the outcome it prices.

---

### 2. CLI hangs on `--step-hours 0` / negative (MAJOR → FIXED)

**Finding:** A non-positive step never advances the `as_of` grid, causing an infinite loop / unbounded memory in `_as_of_grid`. **Status: FIXED.** `_as_of_grid` raises `ValueError` immediately; CLI validates `--step-hours > 0` before connecting. Direct `evaluate()` callers get a clear error, not a hang.

**Code:** [src/calibration.py:302-312](../../src/calibration.py#L302-L312) (direct guard), [src/run_calibration.py:62-67](../../src/run_calibration.py#L62-L67) (CLI guard), test [test_cli_rejects_bad_step_and_min_pairs](../../tests/test_calibration.py) verified to fail on guard removal.

**Impact:** Operational robustness — a mistyped parameter now fails fast and clear.

---

### 3. `--min-error-pairs 1` → ZeroDivisionError (MINOR → FIXED)

**Finding:** With `min_pairs=1`, the sample-variance formula `(n-1)` divides by zero when `n=1` passes the `len(residuals) < min_pairs` gate. **Status: FIXED.** `_error_stats` now guards `n < 2` (needed for any sample variance); CLI validates `--min-error-pairs >= 2`.

**Code:** [src/calibration.py:206](../../src/calibration.py#L206), [src/run_calibration.py:68-71](../../src/run_calibration.py#L68-L71), test [test_error_stats_min_pairs_one_no_zerodiv](../../tests/test_calibration.py).

**Impact:** Edge case safety — the study now handles degenerate inputs gracefully.

---

### 4. Connection leak on `SELECT 1` failure (MINOR → FIXED)

**Finding:** If `conn.execute("SELECT 1")` raises after `store.connect()` succeeds, `conn` is never closed. **Status: FIXED.** Guarded `conn.close()` in the except block (handles the case where `connect()` was the thing that failed).

**Code:** [src/run_calibration.py:80-83](../../src/run_calibration.py#L80-L83).

**Impact:** Resource hygiene — no conn leaks on startup failure.

---

## Hardening Completed (Post-MVP)

### 5. Spec parser coverage expansion (DEFERRED REVIEW FLAG → HARDENED)

**Finding (2026-07-21 live-data review):** The spec parser was only tested against the fixture's `less` and `between` strike types. Live Kalshi data shows `greater`, `less_or_equal`, `greater_or_equal`, and binaries (`strike_type=None`). The parser's regex patterns for "greater than" and related phrasings were untested against real rules text.

**Status: HARDENED.** Expanded `_parse_strike` to handle:
- "X or fewer" / "X or less"
- "at least X" (with intervening words, e.g., "at least an earthquake of 8.0")
- "X or more" (with intervening text, e.g., "12.5 million tonnes or more")
- All existing patterns retain backward compatibility.

**Code:** [src/calibration.py:110-141](../../src/calibration.py#L110-L141), test [test_parse_strike_expands_real_phrasings](../../tests/test_calibration.py) with 8 real-data cases.

**Design decision recorded:** Non-weather yes/no binaries (Kalshi's dominant market type) are skipped because they have no numeric strike and no daily-high forecast anchor the study needs. This is **fail-safe-and-silent** (markets are skipped, not mis-priced).

**Impact:** The parser now covers standard Kalshi numeric-strike phrasings found in real markets.

---

### 6. `_error_stats` O(n²) memoization (DEFERRED REVIEW FLAG → MEASURED & DEFERRED)

**Finding (reviewer 2026-07-21):** `_error_stats` rescans the entire station history on every `(market, as_of)` pair. For long backfills with many markets, this could be slow (O(n²) in principle).

**Status: MEASURED & DEFERRED.** Benchmarked on 180-day history: ~0.45ms per call. Even at 1000 markets × 30 `as_of` samples each (~30k calls), total time is ~13 seconds — acceptable for an offline study. A future optimization (memoizing per-station σ/bias at each `as_of`) could amortize this, but **not required to reach the gate.**

**Code:** [docs/architecture/decisions/0012-calibration-edge-room-brier-skill-gate.md](0012-calibration-edge-room-brier-skill-gate.md) records the trade-off.

**Impact:** Deferred, low priority. Revisit if backfills span years.

---

## Remaining Fail-Safe Flags (No Bugs, Design Choices)

### 7. Weather strike phrasing corpus unverified

**Status:** The parser's "greater/above" and "between X and Y" patterns are validated against individual test cases and the fixture's real Kalshi rules, but the full phrasing corpus in Kalshi's live production market catalog has not been hand-reviewed. **Risk is minimal:** any unparseable phrasing returns `None` (market skipped), never a mis-parsed threshold.

### 8. Negative thresholds unsupported

**Status:** The numeric regex doesn't handle negative numbers (e.g., sub-zero temperature strikes). Currently moot: no weather series in `SERIES_STATION` target sub-zero events. If a low-temperature series is added, this will need attention.

---

## Test Coverage Summary

- **25 tests total** (added 8 during hardening):
  - Spec parser: 8 tests (3 fixture-based real Kalshi rules, 5 synthetic phrasing patterns)
  - Probability math: 3 tests
  - PIT honesty: 3 tests (including self-leak exclusion + verdict invariance)
  - End-to-end verdicts: 3 tests (seeded GO, seeded NO-GO, market-more-accurate)
  - Input guards: 5 tests (min-pairs zero-div, non-positive step, CLI guards)
  - CLI degradation: 2 tests
- **All 25 pass** (tested 2026-07-21).
- **No network / no DB** — all tests use synthetic Reader + fixture-based rules.

---

## Next Steps (Future, Not Blocking)

1. **Real-data gate run:** Provision Postgres, ingest a multi-month Kalshi weather window + IEM forecasts, run `calibration.run_study()` for the actual GO/NO-GO decision. This is the operational test and the proper close of WP-7.
2. **Negative-threshold support:** Add if a sub-zero weather series is registered.
3. **Phrasing corpus audit:** Hand-review Kalshi's complete live rules-text corpus if new market patterns emerge.
4. **Memoization (optional):** Implement per-station σ/bias caching if backfills hit years.

---

**Audited by:** Claude Code (2026-07-21)  
**Commits:** d0fdf52 (WP-7 initial), 5368650 (hardened strike parser), daea1a4 (docs)
