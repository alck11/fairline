-- ---------------------------------------------------------------------------
-- 004_maker1_raw_levels.sql — store the raw book levels MAKER-1 needs to
-- score a snapshot the way Kalshi actually scores it.
--
-- Additive migration: two nullable columns on book_snapshot. Nothing existing
-- is altered, and rows written before this migration keep working (their
-- levels are NULL, which the gate must treat as "cannot be re-scored" rather
-- than as an empty book).
--
-- WHY THIS EXISTS. 003 deliberately stored the SCORED book and not the levels,
-- on the reasoning that "the score is a pure function of the levels and the
-- programme's discount factor" so the reduction was sufficient. Kalshi's
-- Liquidity Incentive Program documentation says otherwise, and the claim in
-- 003's comment that any re-derivation "can be checked without a second
-- collection run" is false:
--
--   * The distance penalty is measured from a **Reference Price** -- the first
--     price level at which cumulative resting size reaches one-fifth of Target
--     Size -- not from the best price. Recovering it needs the cumulative size
--     profile, which `best` and `total_size` do not carry.
--   * Only orders "helping reach Target Size" are scored, so credit is capped
--     by depth rather than running over the whole book.
--
-- Neither quantity is recoverable from (best, total_size, score). A snapshot
-- collected without levels can never be re-scored correctly, and this study
-- cannot re-run history -- so the cost of NOT storing them is permanent.
--
-- Cost of storing them: ~10 levels x 2 sides x 400 programmes x 288
-- passes/day is a few hundred MB/day as JSONB, which is why 003 avoided it.
-- `--levels-depth` on the collector caps how many levels are kept (default 12,
-- comfortably past a 1/5-of-target reference price on observed books) so the
-- volume stays bounded while keeping every level that can affect a score.
-- ---------------------------------------------------------------------------

ALTER TABLE book_snapshot ADD COLUMN IF NOT EXISTS yes_levels JSONB;
ALTER TABLE book_snapshot ADD COLUMN IF NOT EXISTS no_levels  JSONB;

COMMENT ON COLUMN book_snapshot.yes_levels IS
    'Top-N resting YES levels as [[price, size], ...], best first. NULL means '
    'the snapshot predates migration 004 and cannot be re-scored under '
    'Kalshi''s reference-price rule.';
COMMENT ON COLUMN book_snapshot.no_levels IS
    'Top-N resting NO levels as [[price, size], ...], best first, stored at '
    'raw NO-side prices (not YES complements). NULL means the snapshot '
    'predates migration 004.';
