> **Status: PARKED, not active (2026-07-17).** A copy-trade basket decision; the
> copy-trade subsystem is parked out of the Kalshi directional-EV MVP. Kept in-repo
> and demo-green; **not enforced against the current plan.**

# Baskets are category-scoped by a specialism filter, not per-category scores

`build_basket(scored, category, ...)` must return the top-k wallets *specialized
in* a category (CONTEXT.md → _Basket_), but today it ignores `category` and
returns the top-k wallets by overall composite `score`. Two ways to fix it were
on the table, and they differ enormously in blast radius.

**(a) Per-category scores** — recompute the whole feature/scoring pipeline
per `(wallet, category)`: one feature row and one composite per category a wallet
has traded, cross-sectionally ranked within `(as_of, category)`, with a
category-scoped forward label. This is the more *correct* model — a wallet's
crypto skill and its politics skill genuinely differ — but it is a large,
premature lift for an unproven, paper-only strategy, and it fights the grain of
three things the repo has already committed to:

- **The glossary defines a single Score** ("_The only thing called a score_",
  "_each feature percentile-ranked cross-sectionally per `as_of`_"). Per-category
  scores would multiply that into N scores per wallet and re-cut the
  cross-section by category, contradicting the vocabulary rather than
  implementing it. Adopting (a) means first re-deciding what "Score" means.
- **The min-sample and survivorship discipline (ADR-0003).**
  `features_for_wallet` already drops wallets with fewer than 5 resolved trades
  as noise. Splitting each wallet's history across categories makes that floor
  bite far harder: every genuine specialist who is merely *new* to a category
  gets dropped, and the thinning is uneven across wallets — exactly the kind of
  silent universe distortion ADR-0003 exists to prevent.
- **The ML pipeline shape.** `FEATURE_COLS`, `build_training_table`,
  `forward_label`, and the purged time-series CV all assume one row per
  `(wallet, as_of)`. Per-category multiplies the rows and demands category-aware
  CV folds — real surface area on a pipeline that has not yet shown it predicts
  anything.

**(b) A specialism filter over the one Score** — keep the single composite Score
as the ranking, and make `category` a *selection* filter: a wallet enters basket
X only if X is the category it is genuinely concentrated in. The stated risk of
the naive version of (b) is real — a wallet with a mediocre crypto record but a
great overall score (driven by politics) leaking into the crypto basket — but it
closes almost entirely once "concentrated in X" is enforced with a **share
floor**: if a wallet's *majority* of resolved trades are in X, then its overall
Score is, by construction, mostly its X performance, so ranking that pool by the
overall Score is honest. The conflation only survives for diversified wallets,
and the share floor is exactly what excludes those.

**Decision: (b), tightened into a leakage-safe specialism filter.** This is the
right call for this stack's maturity — simple until proven wrong, prove the base
copy strategy has *any* edge before paying for per-category resolution — and it
buys correctness cheaply. The key architectural insight that makes it safe: the
per-category specialism metadata is derived from the history
`features_for_wallet` has *already* point-in-time-filtered (`resolve_ts <
as_of`), so it inherits ADR-0003's no-leakage guarantee for free and touches
neither the forward label nor the CV.

Concretely:

- `features_for_wallet` gains three columns computed from the already-filtered
  `hist`: `dominant_category` (the category with the most resolved trades,
  deterministic tie-break), `dominant_category_share` (that category's fraction
  of resolved trades), and `dominant_category_n` (its resolved-trade count).
  `hhi_category` stays as-is. These are **selection metadata, not model
  features** — do not add them to `FEATURE_COLS` (a string column breaks the
  regressor, and per-category ROI as an ML feature is a separate later question).
- `build_basket` filters to `dominant_category == category` AND
  `dominant_category_share >= min_share` (default `0.5` — a specialist trades a
  majority in one place) AND `dominant_category_n >= min_category_trades`
  (default `5`, mirroring the existing sample floor, now applied within the
  category) AND `score >= min_score`, then ranks the survivors by the overall
  `score` and takes `top_k`.

A wallet is a specialist in at most one category, so it belongs to at most one
basket — consistent with "one basket per category" and "top-k wallets
specialized in one category." A wallet that trades several categories roughly
evenly clears no share floor and correctly appears in no basket.

## Consequences

- `build_basket` becomes correct with near-zero blast radius: only additive
  columns on the feature row and a rewritten filter. `FEATURE_COLS`,
  `forward_label`, `build_training_table`, and the purged CV are untouched, so
  the ML path and ADR-0003's leakage/survivorship guarantees are unaffected.
- We knowingly accept a coarser model of skill than (a): a wallet is credited
  with one dominant specialism, and within-category skill differences below the
  share floor are invisible. The share floor bounds the resulting error — the
  Score that ranks a basket is provably majority-driven by that basket's
  category — but a wallet that is, say, 55% crypto / 45% politics is ranked by a
  Score with meaningful politics contribution. That is the honest cost of not
  rescoring per category.
- `dominant_category` is point-in-time and can change across `as_of` slots as a
  wallet's history shifts (a wallet that pivots into crypto becomes a crypto
  specialist once its crypto history dominates). This is correct, not a bug.
- The door to (a) stays open. If the base copy strategy proves an edge on paper
  **and** per-category skill divergence is shown to matter empirically, a full
  per-category rescore becomes justified follow-up — and would then also need a
  glossary/Score revision. Until both are true, it is complexity serving a
  hypothetical.
- Demo/tuning caveat: uniformly-random trade categories produce almost no
  specialists, so the demo generators must give wallets a home category for any
  basket to be non-empty (see the plan's WP-3 testing note).
