> **Archived 2026-07-17.** All 8 work packages below are complete and describe
> the arb/copy-trade-primary build (pre-pivot). The MVP has since pivoted to
> Kalshi directional EV on weather/econ markets — see
> [`docs/product/requirements.md`](../../product/requirements.md),
> [`docs/product/roadmap.md`](../../product/roadmap.md), and
> [`docs/research/2026-07-17-polymarket-edge-landscape.md`](../../research/2026-07-17-polymarket-edge-landscape.md)
> for the current direction and rationale. Kept here as the historical record
> of the work these WPs actually shipped (still live in `src/`, now parked
> per the requirements doc) — not as a live plan.

# Implementation Plan — align code to the glossary & ADRs (archived)

These work packages close the gaps a grilling pass found between the code and the
decisions now recorded in [`CONTEXT.md`](../../../CONTEXT.md) and
[`docs/architecture/decisions/`](../decisions/). There is no `docs/product/requirements.md` yet, so work
packages are traced to **glossary terms and ADRs** rather than user stories.

Ordering is by dependency then correctness-risk. Each package is independently
reviewable and leaves the demos (`python3 src/<file>.py`) green.

---

## WP-1 — Collapse arb taxonomy to `complete_set | cross_venue` ✅ (done 2026-07-11)

**Traces to:** ADR (arb taxonomy), CONTEXT.md → _Complete set_, _Cross-venue_.
**Why:** `bundle` and `multi` are the same structure (a within-venue complete
set); the split is an implementation detail, not a domain distinction.

**Delivered:** [`src/detector.py`](../../../src/detector.py) — merged
`bundle_edge` and `multi_outcome_edge` into `complete_set_edge(size, *, venue,
category, prices: Sequence[float])` (binary case is `prices=[yes, no]`),
`kind="complete_set"`; `cross_venue_edge` left byte-identical.
[`schema/001_schema.sql`](../../../schema/001_schema.sql) comment and
[`README.md`](../../../README.md)'s detector row updated to match; `__main__`
demo now asserts both `kind` literals.

**Testing:** QA PASS — demo prints a within-venue complete-set opportunity and
a cross-venue one with the exact two allowed `kind` strings; no `"bundle"`/
`"multi"` references remain in code; downstream consumers (`ev_detector.py`,
`risk_execution.py`) don't read `Opportunity.kind` so nothing broke there.

**Follow-up resolved (2026-07-17):** `complete_set_edge` regained per-leg maker
flags — `maker: bool | Sequence[bool] = False`, broadcast to every leg when a
single bool, or matched 1:1 against `prices` when a sequence (mismatched
lengths raise `ValueError`). A within-venue complete set can now mix resting
(fee-free, rebate-earning) and taker legs same as the old `bundle_edge` could.
Also added the empty-legs guard: `complete_set_edge(prices=[])` now raises
`ValueError` instead of silently returning a fake full-notional "profit".
Demo in `src/detector.py`'s `__main__` extended to assert: an all-maker fill
has zero fees and strictly higher net profit than the all-taker fill at the
same prices; a mixed `[True, False]` fill's fees land strictly between the
all-taker and all-maker cases; empty `prices` raises. No other caller exists
in the repo (only the demo calls `complete_set_edge`), so the added keyword
arg is non-breaking.

---

## WP-2 — Matcher: embeddings triage only, never auto-link ✅ (done 2026-07-11)

**Traces to:** ADR-0002, CONTEXT.md → _Triage_, _Escalate_, _Match_.
**Why:** auto-linking at cosine ≥ 0.92 with hardcoded polarity +1 produces
guaranteed losses on negation/three-way markets (cut/hold/raise). Only reading
both resolution rule-sets can write a link.

**Delivered:** [`src/market_matcher.py`](../../../src/market_matcher.py) — removed
the `sim >= AUTO_LINK → MatchResult(...,"embedding")` branch entirely; `AUTO_LINK`
retired (no repurposed use needed). New routing: `sim < ESCALATE` → `None`
(discard); `sim >= ESCALATE` → `confirmer(...)`, always. Only `'llm'` (confirmer)
and `'manual'` (human inserts elsewhere) remain possible `MatchResult.method`
values. [`README.md`](../../../README.md)'s matcher row and
[`schema/001_schema.sql`](../../../schema/001_schema.sql)'s `market_link.method`
comment updated to match — `'embedding'` is no longer documented as a valid
method anywhere.

**Testing:** QA PASS — near-identical pair now **escalates** (`method='llm'`)
instead of auto-linking; orthogonal pair still discards to `None`; boundary
case `sim == ESCALATE` confirmed to escalate (not discard), consistent with the
`>=` semantics; `ESCALATE` constant itself unchanged (0.70), so the triage floor
wasn't accidentally loosened. No other module (`risk_execution.py`,
`ev_detector.py`) depends on `AUTO_LINK` or assumes `method="embedding"`.

---

## WP-3 — Baskets are category-scoped ✅ (done 2026-07-12)

**Traces to:** ADR-0007 (basket scope), ADR-0003 (leakage/survivorship),
CONTEXT.md → _Basket_.
**Why:** `build_basket` takes `category` but ignores it; baskets are meant to be
top-k specialists *within* a category.

**Decision (ADR-0007):** a **specialism filter over the single Score**, not
per-category scores. Keep the one composite `score` as the ranking; make
`category` a *selection* filter that admits only wallets genuinely concentrated
in that category. Per-category rescoring (the "more correct" option) is rejected
as premature complexity that also contradicts the glossary's single-Score
definition and worsens the ADR-0003 min-sample/survivorship discipline; it stays
open as future work only if the base copy strategy proves edge *and* per-category
skill divergence is shown to matter. See ADR-0007 for the full rationale.

The specialism metadata is derived from the history `features_for_wallet` has
**already** point-in-time-filtered (`resolve_ts < as_of`), so it inherits
ADR-0003's no-leakage guarantee for free and touches neither the forward label
nor the CV.

**Changes**
- [`src/wallet_features.py`](../../../src/wallet_features.py) `features_for_wallet`:
  add three columns computed from the already-filtered `hist` (do **not** change
  the `hist`/`resolve_ts < as_of` filter, and do **not** touch `forward_label`):
  - `dominant_category` — the category with the most resolved trades; break ties
    deterministically (e.g. highest total stake, then lexical) so panels are
    reproducible.
  - `dominant_category_share` — that category's fraction of the wallet's resolved
    trades (`max(value_counts(normalize=True))`).
  - `dominant_category_n` — its resolved-trade count.
  Leave `hhi_category` unchanged. These columns flow through `build_feature_panel`
  (it just collects the dicts) and survive `composite_score` (it only adds
  `score`), so they reach `build_basket` on the `scored` frame.
- [`src/wallet_scoring.py`](../../../src/wallet_scoring.py): **do not** add the new
  columns to `FEATURE_COLS` — they are selection metadata, not model features
  (`dominant_category` is a string and would break the regressor; per-category
  ROI as an ML feature is a separate later question). `FEATURE_COLS`,
  `forward_label`, `build_training_table`, and the purged CV stay untouched.
  Rewrite `build_basket` to:
  ```python
  def build_basket(scored, category, *, top_k=8, min_score=70.0,
                   min_share=0.5, min_category_trades=5):
      pool = scored[
          (scored["dominant_category"] == category)
          & (scored["dominant_category_share"] >= min_share)
          & (scored["dominant_category_n"] >= min_category_trades)
          & (scored["score"] >= min_score)
      ].copy()
      pool = pool.sort_values("score", ascending=False)
      return pool["wallet"].head(top_k).tolist()
  ```
  Defaults: `min_share=0.5` (a specialist trades a majority in one category),
  `min_category_trades=5` (mirrors the existing `len(hist) >= 5` sample floor,
  now applied *within* the category), `min_score=70.0` unchanged. A wallet is a
  specialist in at most one category, so it belongs to at most one basket —
  consistent with "one basket per category."
- **Demo data must produce specialists.** Uniformly-random trade categories
  (`rng.choice([...])` per trade, as in both `__main__` blocks today) yield
  almost no wallet clearing a 0.5 share floor, so every basket comes back empty.
  Update the `wallet_scoring.py` demo generator (and `wallet_features.py`'s if
  used in the test) to give each wallet a *home* category it trades with high
  probability, so distinct, non-empty baskets exist to demonstrate.

**Testing:** QA PASS — two baskets for two categories return **different**,
category-appropriate wallet sets on the (specialism-bearing) demo data (8
crypto + 8 politics, zero overlap, all 120 wallets checked pairwise-disjoint
across all 3 demo categories with no score floor applied); every wallet
returned for `category=X` has `dominant_category == X`; a deliberately
diversified wallet (share < `min_share`) appears in **neither** basket; an
unspecialized category returns `[]` gracefully. Leakage boundary re-verified
directly: a wallet with 5 pre-`as_of` "politics" trades and 100 higher-volume
post-`as_of` "crypto" trades still resolves to `dominant_category=="politics"`
— confirms zero leakage from ADR-0003's `resolve_ts < as_of` filter. Tie-break
(count → stake → lexical) verified deterministic across `PYTHONHASHSEED`
variations. `FEATURE_COLS`, `forward_label`, `build_training_table`, and the
purged CV are byte-identical; the xgboost path is unaffected. New regression
test: [`tests/test_wallet_basket_specialism.py`](../../../tests/test_wallet_basket_specialism.py).

**Blocked-by:** none — architecture call resolved by ADR-0007.

---

## WP-4 — Consensus needs a participation floor ✅ (done 2026-07-11)

**Traces to:** ADR (consensus, option C), CONTEXT.md → _Consensus_,
_Participation_.
**Why:** `execute_copy` takes a bare `basket_agreement` float; one wallet trading
alone reads as 100% consensus. Consensus must be agreement among *participants*,
valid only above a floor.

**Delivered:** [`src/risk_execution.py`](../../../src/risk_execution.py) — added
`min_participation: int = 3` to `RiskLimits`; new `consensus_gate(agree_count,
participant_count, basket_size, limits) -> (bool, float, str)` rejects
unconditionally when `participant_count < min_participation`, otherwise gates
`agree_count/participant_count` (never diluted by `basket_size`) against
`basket_consensus`. `execute_copy`'s signature changed to
`(wallet, leg, agree_count, participant_count, basket_size)` — no other caller
existed in the repo, confirmed by grep. First regression test added:
[`tests/test_risk_execution_consensus.py`](../../../tests/test_risk_execution_consensus.py)
(standalone, no pytest dependency — matches the repo's `python3 <file>.py`
convention).

**Testing:** QA PASS — 1-of-1 participation rejected (below floor) even at
100% agreement; 4-of-5 passes; 3-of-8 (3 participants out of an 8-member
basket, whole-basket denominator would fail the gate at 0.375) passes when
correctly evaluated on participants (3/3 = 1.0). Both the floor boundary
(`participant_count == min_participation`) and the consensus boundary
(`agreement == basket_consensus`) are inclusive and tested. `_check`,
`execute_arb`, kill switch, and all other risk-gate logic verified untouched.

**Follow-up resolved (2026-07-17):** `consensus_gate` now guards
`participant_count == 0` independently of the floor comparison, so
`RiskLimits(min_participation=0)` ("no floor") with zero participants returns
`(False, 0.0, "no participants (0/N)")` instead of raising
`ZeroDivisionError`. It also validates `agree_count <= participant_count <=
basket_size` and rejects negative counts, raising `ValueError` on any of
those — nonsensical shapes that can only come from an upstream counting bug,
so they're no longer silently gated as if they were a legitimate (if
malformed) basket. The two regression tests in
`tests/test_risk_execution_consensus.py` that documented the old
bug/no-validation behavior (`test_BUG_zero_division_when_min_participation_is_zero`,
`test_no_upper_bound_validation_on_agree_count_or_participant_count`) were
rewritten to assert the fixed behavior
(`test_zero_participants_is_safe_even_with_no_floor`,
`test_inconsistent_counts_raise_value_error`). No caller in the repo passes
malformed counts today (`execute_copy`'s only caller is the demo, with
well-formed inputs), so this is non-breaking.

---

## WP-5 — Kill switch latches in live mode ✅ (done 2026-07-12)

**Traces to:** ADR-0001, CONTEXT.md → _Kill switch_.
**Why:** `_roll_day` clears `kill` at the UTC day roll in *both* modes. Live must
require manual re-arm; auto-reset is paper-only (unattended replays).

**Delivered:** [`src/risk_execution.py`](../../../src/risk_execution.py) —
`_roll_day(self, mode)` only auto-clears `kill` when `mode == "paper"`;
`realized_today` still resets unconditionally every day roll in both modes.
New `Engine.rearm()` — the explicit human/live re-arm path — clears both `kill`
and `realized_today` together (a human re-arming is domain-equivalent to
"start the day's loss accounting fresh from here," the same semantic
`_roll_day` already applies automatically at UTC midnight in paper mode).
New [`tests/test_risk_execution_killswitch.py`](../../../tests/test_risk_execution_killswitch.py)
(standalone, matches `test_risk_execution_consensus.py`'s conventions).

**Testing:** QA FAIL → fix → PASS. First pass caught a Major bug: `rearm()`
cleared `kill` but left the stale negative `realized_today` in place, so the
very next `settle()` call — even one settling a brand-new profit, same day, no
roll — re-tripped the kill switch against the carried-over value, making
`rearm()` non-functional beyond a single `_check()` window. Fixed by having
`rearm()` reset `realized_today` too. Re-verified: paper auto-resets `kill`
across a simulated day roll; live stays latched across multiple consecutive
day rolls until `rearm()` is called; `realized_today` still resets every day
roll in both modes (unaffected by the fix); `_check`/`execute_arb`/`_fill`/
`_unwind`/`consensus_gate`/`execute_copy` byte-identical throughout.

**Follow-up resolved (2026-07-17):** product decision (log + rate-limit,
chosen over log-only, no-op-when-not-tripped, and leave-as-is) — `rearm()`
now logs every call, successful or blocked, to the blotter (status `"rearm"`
/ `"rearm_blocked"`) recording the `realized_today` value being zeroed (the
masked loss) and whether `kill` was actually set. New
`RiskLimits.max_rearms_per_day: int = 1` caps successful rearms per calendar
day; the counter (`RiskState.rearms_today`) resets at the same day roll that
resets `realized_today`. Once the cap is exhausted, `rearm()` raises
`RuntimeError` instead of silently no-op'ing, closing the loop that let a
human absorb unbounded daily loss one rearm at a time (previously verified:
5× `settle(-90)`+`rearm()` absorbed -$450 against a $100 limit). `rearm()`'s
return type changed from `None` to the audit-row `dict`; no caller in the
repo used the return value, and no test calls `rearm()` more than once per
engine per day, so the default cap doesn't break existing behavior. Three new
regression tests added to `tests/test_risk_execution_killswitch.py`:
log content, cap enforcement (raises, leaves state untouched), and cap reset
at the day roll.

---

## WP-6 — README & naming cleanup ✅ (done 2026-07-13)

**Traces to:** CONTEXT.md header (name decision).
**Why:** README title still says `polymkt-arb`; `fairline` is canonical.

**Delivered:** [`README.md`](../../../README.md) title, ADR pointer, collapsed
arb-kind row (WP-1), and triage-only matcher row (WP-2) were already correct —
carried along incidentally by the WP-1/WP-2 commits. The one gap was WP-3
(done after those rows were last touched): the `wallet_features.py` and
`wallet_scoring.py` rows didn't mention category-scoped baskets. Updated both
rows to note the dominant-category features and the category-scoped,
ADR-0007-gated `build_basket`.

**Testing:** none (docs) — re-ran `src/wallet_scoring.py`'s demo to confirm
the row's description (disjoint, category-appropriate, non-empty baskets)
still matches current behavior.

---

## WP-7 — Ingestion: MarketSource interface + polymarket-cli backend ✅ (done 2026-07-11)

**Traces to:** ADR-0006, `docs/research/2026-07-11-polymarket-cli-and-ev-references.md`.
**Delivered:** `src/ingest.py` (MarketSource Protocol, row dataclasses shaped
for the schema tables, FakeSource demo) and `src/ingest_polymarket_cli.py`
(subprocess adapter over `polymarket -o json`, no-auth public data only,
graceful skip when the binary is absent).
**Testing:** both demos run standalone; CLI demo degrades to exit 0 without the
binary. **Follow-up:** live-binary smoke run once polymarket-cli is installed;
`KalshiSource` is future work.

---

## WP-8 — Directional-EV prototype ✅ (done 2026-07-11)

**Traces to:** ADR-0005, CONTEXT.md → _Directional_, _EV_, _Signal (directional)_.
**Delivered:** `src/ev_detector.py` — post-fee EV per share (via `fees.Leg`),
depth-aware sizing (via `detector.vwap_fill`), fractional-Kelly cap
(quarter-Kelly default), `DirectionalSignal` output (not an Opportunity,
never written to `arb_opportunity`). Probability model injected via `prob_fn`.
**Testing:** demo shows a positive-EV signal Kelly-capped into the book and a
no-edge case returning None. **Follow-up:** a `signal` audit table; a real
`prob_fn` (weather-style horizon, not latency-competitive 5-min markets).

---

## Suggested sequence

WP-1 → WP-2 → WP-4 → WP-5 → WP-3 → WP-6.
All work packages (WP-1 through WP-8) are done. README reflects the collapsed
arb kinds, the triage-only matcher, category-scoped baskets, and the three
ingestion/EV modules.
