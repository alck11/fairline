# Implementation Plan — align code to the glossary & ADRs

These work packages close the gaps a grilling pass found between the code and the
decisions now recorded in [`CONTEXT.md`](../../CONTEXT.md) and
[`docs/architecture/decisions/`](./decisions/). There is no `docs/product/requirements.md` yet, so work
packages are traced to **glossary terms and ADRs** rather than user stories.

Ordering is by dependency then correctness-risk. Each package is independently
reviewable and leaves the demos (`python3 src/<file>.py`) green.

---

## WP-1 — Collapse arb taxonomy to `complete_set | cross_venue` ✅ (done 2026-07-11)

**Traces to:** ADR (arb taxonomy), CONTEXT.md → _Complete set_, _Cross-venue_.
**Why:** `bundle` and `multi` are the same structure (a within-venue complete
set); the split is an implementation detail, not a domain distinction.

**Delivered:** [`src/detector.py`](../../src/detector.py) — merged
`bundle_edge` and `multi_outcome_edge` into `complete_set_edge(size, *, venue,
category, prices: Sequence[float])` (binary case is `prices=[yes, no]`),
`kind="complete_set"`; `cross_venue_edge` left byte-identical.
[`schema/001_schema.sql`](../../schema/001_schema.sql) comment and
[`README.md`](../../README.md)'s detector row updated to match; `__main__`
demo now asserts both `kind` literals.

**Testing:** QA PASS — demo prints a within-venue complete-set opportunity and
a cross-venue one with the exact two allowed `kind` strings; no `"bundle"`/
`"multi"` references remain in code; downstream consumers (`ev_detector.py`,
`risk_execution.py`) don't read `Opportunity.kind` so nothing broke there.

**Follow-up (QA-flagged, needs an architect ruling):** the merged
`complete_set_edge` signature dropped the `yes_maker`/`no_maker` params the old
`bundle_edge` had — a within-venue complete set can no longer be priced with
resting (fee-free, rebate-earning) maker legs, only taker. Nothing in the repo
currently calls it with `maker=True`, so nothing is broken today, but decide
whether `complete_set_edge` should regain per-leg `maker` flags before this is
used for real. Separately, `complete_set_edge(prices=[])` silently returns a
fake full-notional "profit" instead of erroring — pre-existing (inherited
unchanged from the old code), not introduced by this merge, but worth an empty-
legs guard whenever this function is next touched.

---

## WP-2 — Matcher: embeddings triage only, never auto-link ✅ (done 2026-07-11)

**Traces to:** ADR-0002, CONTEXT.md → _Triage_, _Escalate_, _Match_.
**Why:** auto-linking at cosine ≥ 0.92 with hardcoded polarity +1 produces
guaranteed losses on negation/three-way markets (cut/hold/raise). Only reading
both resolution rule-sets can write a link.

**Delivered:** [`src/market_matcher.py`](../../src/market_matcher.py) — removed
the `sim >= AUTO_LINK → MatchResult(...,"embedding")` branch entirely; `AUTO_LINK`
retired (no repurposed use needed). New routing: `sim < ESCALATE` → `None`
(discard); `sim >= ESCALATE` → `confirmer(...)`, always. Only `'llm'` (confirmer)
and `'manual'` (human inserts elsewhere) remain possible `MatchResult.method`
values. [`README.md`](../../README.md)'s matcher row and
[`schema/001_schema.sql`](../../schema/001_schema.sql)'s `market_link.method`
comment updated to match — `'embedding'` is no longer documented as a valid
method anywhere.

**Testing:** QA PASS — near-identical pair now **escalates** (`method='llm'`)
instead of auto-linking; orthogonal pair still discards to `None`; boundary
case `sim == ESCALATE` confirmed to escalate (not discard), consistent with the
`>=` semantics; `ESCALATE` constant itself unchanged (0.70), so the triage floor
wasn't accidentally loosened. No other module (`risk_execution.py`,
`ev_detector.py`) depends on `AUTO_LINK` or assumes `method="embedding"`.

---

## WP-3 — Baskets are category-scoped

**Traces to:** ADR (basket scope), CONTEXT.md → _Basket_.
**Why:** `build_basket` takes `category` but ignores it; baskets are meant to be
top-k specialists *within* a category.

**Changes**
- [`src/wallet_scoring.py`](../../src/wallet_scoring.py) `build_basket`: actually
  filter/rank by category specialism. Needs a per-(wallet, category) signal — the
  feature panel currently aggregates categories per wallet. Either (a) compute
  per-category scores, or (b) use `hhi_category` + the wallet's dominant category
  as a specialism proxy. **Architect decision needed** on which; flag it rather
  than improvising.

**Testing:** two baskets for two categories return different, category-appropriate
wallet sets on the demo data.

**Blocked-by:** none, but the (a)/(b) choice is an architecture call.

---

## WP-4 — Consensus needs a participation floor ✅ (done 2026-07-11)

**Traces to:** ADR (consensus, option C), CONTEXT.md → _Consensus_,
_Participation_.
**Why:** `execute_copy` takes a bare `basket_agreement` float; one wallet trading
alone reads as 100% consensus. Consensus must be agreement among *participants*,
valid only above a floor.

**Delivered:** [`src/risk_execution.py`](../../src/risk_execution.py) — added
`min_participation: int = 3` to `RiskLimits`; new `consensus_gate(agree_count,
participant_count, basket_size, limits) -> (bool, float, str)` rejects
unconditionally when `participant_count < min_participation`, otherwise gates
`agree_count/participant_count` (never diluted by `basket_size`) against
`basket_consensus`. `execute_copy`'s signature changed to
`(wallet, leg, agree_count, participant_count, basket_size)` — no other caller
existed in the repo, confirmed by grep. First regression test added:
[`tests/test_risk_execution_consensus.py`](../../tests/test_risk_execution_consensus.py)
(standalone, no pytest dependency — matches the repo's `python3 <file>.py`
convention).

**Testing:** QA PASS — 1-of-1 participation rejected (below floor) even at
100% agreement; 4-of-5 passes; 3-of-8 (3 participants out of an 8-member
basket, whole-basket denominator would fail the gate at 0.375) passes when
correctly evaluated on participants (3/3 = 1.0). Both the floor boundary
(`participant_count == min_participation`) and the consensus boundary
(`agreement == basket_consensus`) are inclusive and tested. `_check`,
`execute_arb`, kill switch, and all other risk-gate logic verified untouched.

**Follow-up (QA-flagged, not fixed — minor, doesn't trigger under any default
config):** `consensus_gate(0, 0, ..., RiskLimits(min_participation=0))` raises
`ZeroDivisionError` instead of failing gracefully, since `min_participation=0`
("no floor") makes the floor check `0 < 0 → False` and falls through to the
division. Also, `agree_count > participant_count` or `participant_count >
basket_size` (nonsensical inputs) are silently accepted rather than validated —
could mask an upstream counting bug in whatever eventually supplies these
counts. Both documented as intentionally-reproducing regression tests in
`tests/test_risk_execution_consensus.py` rather than silently fixed.

---

## WP-5 — Kill switch latches in live mode ✅ (done 2026-07-12)

**Traces to:** ADR-0001, CONTEXT.md → _Kill switch_.
**Why:** `_roll_day` clears `kill` at the UTC day roll in *both* modes. Live must
require manual re-arm; auto-reset is paper-only (unattended replays).

**Delivered:** [`src/risk_execution.py`](../../src/risk_execution.py) —
`_roll_day(self, mode)` only auto-clears `kill` when `mode == "paper"`;
`realized_today` still resets unconditionally every day roll in both modes.
New `Engine.rearm()` — the explicit human/live re-arm path — clears both `kill`
and `realized_today` together (a human re-arming is domain-equivalent to
"start the day's loss accounting fresh from here," the same semantic
`_roll_day` already applies automatically at UTC midnight in paper mode).
New [`tests/test_risk_execution_killswitch.py`](../../tests/test_risk_execution_killswitch.py)
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

**Follow-up (QA-flagged, not fixed — accepted tradeoff, not a bug):**
`rearm()` unconditionally zeroes `realized_today` with no gating on whether
`kill` was actually set, and no cap on how often it's called. A human calling
`rearm()` repeatedly after each trip effectively grants a fresh daily-loss
budget each time (verified: 5× `settle(-90)`+`rearm()` loop absorbs -$450
against a $100 limit), and calling `rearm()` when `kill` is still `False`
silently zeroes legitimate accumulated loss too. Since `rearm()` is explicitly
the human-reviewed manual path, this is a defensible tradeoff rather than a
defect — but nothing currently logs the masked loss at rearm time or rate-
limits rearm calls. Worth a product/architecture decision if live placement is
ever built.

---

## WP-6 — README & naming cleanup

**Traces to:** CONTEXT.md header (name decision).
**Why:** README title still says `polymkt-arb`; `fairline` is canonical.

**Changes**
- [`README.md`](../../README.md): retitle to `fairline`, update the file table to
  reflect the collapsed arb kinds (WP-1) and triage-only matcher (WP-2).
- Add a one-line pointer to `CONTEXT.md` and `docs/architecture/decisions/`.

**Testing:** none (docs).

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

WP-1 → WP-2 → WP-4 → WP-5 → WP-3 (architecture call) → WP-6.
Only WP-3 remains, and it needs an architect ruling before an executor should
touch it; WP-6 goes last so it describes the finished state. WP-1/2/4/5/7/8 are
already done; WP-6's README pass should also cover the three new ingestion/EV
modules.
