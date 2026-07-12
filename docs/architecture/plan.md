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

## WP-4 — Consensus needs a participation floor

**Traces to:** ADR (consensus, option C), CONTEXT.md → _Consensus_,
_Participation_.
**Why:** `execute_copy` takes a bare `basket_agreement` float; one wallet trading
alone reads as 100% consensus. Consensus must be agreement among *participants*,
valid only above a floor.

**Changes**
- [`src/risk_execution.py`](../../src/risk_execution.py): add a consensus helper
  (or accept `(agree_count, participant_count, basket_size)`), compute
  `agree/participants`, and reject when `participants < floor` or consensus < gate.
  Add `min_participation` to `RiskLimits` (default e.g. 3).

**Testing:** 1-of-1 participation is rejected (below floor); 4-of-5 agreeing
passes; 3-of-8 (whole-basket denom would fail) still evaluated on participants.

---

## WP-5 — Kill switch latches in live mode

**Traces to:** ADR-0001, CONTEXT.md → _Kill switch_.
**Why:** `_roll_day` clears `kill` at the UTC day roll in *both* modes. Live must
require manual re-arm; auto-reset is paper-only (unattended replays).

**Changes**
- [`src/risk_execution.py`](../../src/risk_execution.py): in `_roll_day`, only
  auto-clear `kill` when `self.mode == "paper"`. Add an explicit `rearm()` method
  for the live/human path.

**Testing:** paper engine auto-resets `kill` across a simulated day roll; live
engine stays killed until `rearm()` is called.

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
WP-4/5 are self-contained; WP-3 needs an architect ruling; WP-6 last so it
describes the finished state. WP-1/2/7/8 are already done; WP-6's README pass
should also cover the three new ingestion/EV modules.
