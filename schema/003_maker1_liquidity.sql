-- ---------------------------------------------------------------------------
-- 003_maker1_liquidity.sql — MAKER-1 forward-observation study.
--
-- Additive migration. Touches nothing in 001 or 002; no existing table, index
-- or constraint is altered. Same discipline as 002 (ADR-0010).
--
-- MAKER-1 is the project's first *maker*-side candidate: every one of the
-- candidates closed by ADR-0014/0022/0025/0026/0027/0029 crossed the spread.
-- The study samples Kalshi's published liquidity-incentive programmes and the
-- L2 book on the markets carrying them, then asks whether resting orders earn
-- enough reward, gross of adverse selection, to justify measuring what adverse
-- selection costs.
--
-- Unlike every prior study, this one CANNOT be run from history: Kalshi serves
-- no archive of past book state or past programme rosters. It is a forward
-- observation, which the user approved on 2026-08-02.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- incentive_program — one row per programme, as served by
-- GET /incentive_programs. Rosters change as events list and settle, so this
-- is upserted on every collector pass rather than loaded once.
--
-- period_reward_centicents keeps the venue's own unit in the column NAME.
-- Kalshi denominates this field in centi-cents (1e-4 USD); reading it as cents
-- overstates every pool by 100x, which is exactly the error the first pass at
-- this research made. A column called `period_reward` would invite it again.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incentive_program (
    program_id               TEXT PRIMARY KEY,
    market_ticker            TEXT NOT NULL,
    incentive_type           TEXT NOT NULL,
    start_at                 TIMESTAMPTZ NOT NULL,
    end_at                   TIMESTAMPTZ NOT NULL,
    period_reward_centicents BIGINT NOT NULL,
    discount_factor_bps      INTEGER,
    target_size              NUMERIC,
    description              TEXT NOT NULL DEFAULT '',
    paid_out                 BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incentive_program_ticker_idx
    ON incentive_program (market_ticker, start_at);

-- ---------------------------------------------------------------------------
-- book_snapshot — one row per (programme, instant), both sides scored.
--
-- Stores the SCORED book, not the raw levels: the score is a pure function of
-- the levels and the programme's discount factor, and keeping ~10 levels x 2
-- sides x 1,440 snapshots/day/market as rows would be a hypertable's worth of
-- data to answer a question that only needs the reduction. The raw best price
-- and total size survive alongside it so the target-size diagnostic and any
-- re-derivation of the score can be checked without a second collection run.
--
-- UNIQUE (program_id, ts) makes the collector idempotent: a restart mid-period
-- re-samples rather than double-counting, and double-counting the denominator
-- of a yield is precisely the silent failure this project keeps finding.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS book_snapshot (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    program_id       TEXT NOT NULL REFERENCES incentive_program(program_id),
    ts               TIMESTAMPTZ NOT NULL,
    yes_best         NUMERIC,
    yes_total_size   NUMERIC NOT NULL,
    yes_score        NUMERIC NOT NULL,
    no_best          NUMERIC,
    no_total_size    NUMERIC NOT NULL,
    no_score         NUMERIC NOT NULL,
    UNIQUE (program_id, ts)
);
CREATE INDEX IF NOT EXISTS book_snapshot_program_ts_idx
    ON book_snapshot (program_id, ts);
