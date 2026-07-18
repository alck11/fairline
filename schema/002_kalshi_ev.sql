-- ============================================================================
-- fairline : Kalshi directional-EV schema extensions  (WP-1, ADR-0010)
-- ----------------------------------------------------------------------------
-- Forward-only, additive migration applied ON TOP OF schema/001_schema.sql.
-- Apply order: 001 then 002. Does NOT modify 001 or any parked table
-- (market_link, wallet, wallet_trade, wallet_score, arb_opportunity,
-- execution) -- see ADR-0010 ("Reuse, don't reshape, the dimension tables").
--
-- Seven tables: the five ADR-0010 tables --
--   candlestick, weather_forecast, weather_observation,
--   directional_signal, backtest_run, backtest_result
-- -- plus two small additive helpers the ADR left implicit:
--
--   * outcome_token  -- 001's `outcome` table (untouched, per ADR-0010's "no
--     change to market/outcome/venue/trade_print") has no column for the
--     venue-native token/ticker id that Candle, ResolutionRow,
--     DirectionalSignal and every PIT reader in src/store.py address outcomes
--     by (see src/ingest.py's OutcomeRef.token_id: "Polymarket CLOB token id /
--     Kalshi ticker side"). This bridge maps that string to the internal
--     outcome_id FK without touching `outcome`.
--
-- Idempotent upsert keys (US-1) match ADR-0010's "Idempotent upserts"
-- paragraph exactly where it specifies one, and use the natural key
-- elsewhere: candlestick on (outcome_id, ts); weather_forecast on
-- (source, station, variable, issued_at, valid_at); weather_observation on
-- its PK (station, variable, observed_at); outcome_token on token_id;
-- directional_signal on (run_id, as_of, outcome_id) -- one signal per
-- outcome per decision step per run; backtest_run on run_id; backtest_result
-- on (run_id, outcome_id, entry_as_of) -- one settled position per outcome
-- per entry per run.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- bridge: venue-native token/ticker id -> internal outcome_id (see header)
-- ---------------------------------------------------------------------------
CREATE TABLE outcome_token (
    token_id    TEXT PRIMARY KEY,
    outcome_id  BIGINT NOT NULL REFERENCES outcome(outcome_id)
);
CREATE INDEX ON outcome_token (outcome_id);

-- ---------------------------------------------------------------------------
-- candlestick (hypertable) -- Kalshi's free OHLC history, the harness's
-- primary point-in-time price source (ADR-0010 #1). Not modelled as
-- orderbook_snapshot: candles are bars, not book depth, and Kalshi's API
-- gives no historical depth -- reusing orderbook_snapshot would lie about
-- what the data is.
-- ---------------------------------------------------------------------------
CREATE TABLE candlestick (
    ts          TIMESTAMPTZ NOT NULL,
    outcome_id  BIGINT NOT NULL REFERENCES outcome(outcome_id),
    open        NUMERIC NOT NULL,
    high        NUMERIC NOT NULL,
    low         NUMERIC NOT NULL,
    close       NUMERIC NOT NULL,
    volume      NUMERIC,
    PRIMARY KEY (outcome_id, ts),
    CHECK (open  BETWEEN 0 AND 1 AND high BETWEEN 0 AND 1 AND
           low   BETWEEN 0 AND 1 AND close BETWEEN 0 AND 1)
);
SELECT create_hypertable('candlestick', 'ts', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON candlestick (outcome_id, ts DESC);

-- ---------------------------------------------------------------------------
-- weather_forecast -- PIT key is issued_at, what was knowable when the
-- forecast was published (ADR-0010 #2 / ADR-0009). Never back-filled from
-- valid_at.
-- ---------------------------------------------------------------------------
CREATE TABLE weather_forecast (
    issued_at   TIMESTAMPTZ NOT NULL,
    valid_at    TIMESTAMPTZ NOT NULL,
    station     TEXT NOT NULL,
    variable    TEXT NOT NULL,
    value       NUMERIC NOT NULL,
    source      TEXT NOT NULL,
    horizon_h   NUMERIC,
    PRIMARY KEY (source, station, variable, issued_at, valid_at)
);
CREATE INDEX ON weather_forecast (station, variable, valid_at);
CREATE INDEX ON weather_forecast (issued_at);

-- ---------------------------------------------------------------------------
-- weather_observation -- realized truth the calibration study (WP-7) and any
-- model training score against (ADR-0010 #3).
-- ---------------------------------------------------------------------------
CREATE TABLE weather_observation (
    observed_at TIMESTAMPTZ NOT NULL,
    station     TEXT NOT NULL,
    variable    TEXT NOT NULL,
    value       NUMERIC NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (station, variable, observed_at)
);

-- ---------------------------------------------------------------------------
-- directional_signal -- the audit table ADR-0005 flagged as follow-up.
-- Persists each DirectionalSignal at decision time; distinct from
-- arb_opportunity (CONTEXT.md -> Signal (directional) -- never conflated)
-- (ADR-0010 #4).
-- ---------------------------------------------------------------------------
CREATE TABLE directional_signal (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id            TEXT NOT NULL,
    as_of             TIMESTAMPTZ NOT NULL,
    outcome_id        BIGINT NOT NULL REFERENCES outcome(outcome_id),
    p_model           NUMERIC NOT NULL,
    price             NUMERIC NOT NULL,
    size              NUMERIC NOT NULL,
    ev_per_share      NUMERIC NOT NULL,
    expected_profit   NUMERIC NOT NULL,
    prob_fn_name      TEXT,
    UNIQUE (run_id, as_of, outcome_id)
);
CREATE INDEX ON directional_signal (outcome_id, as_of);

-- ---------------------------------------------------------------------------
-- backtest_run / backtest_result -- the US-6 report and the always-market-
-- price baseline read ONLY these, so the report reproduces from stored
-- tables with no re-ingest (ADR-0010 #5).
-- ---------------------------------------------------------------------------
CREATE TABLE backtest_run (
    run_id        TEXT PRIMARY KEY,
    prob_fn_name  TEXT NOT NULL,
    category      TEXT NOT NULL,
    window_start  TIMESTAMPTZ NOT NULL,
    window_end    TIMESTAMPTZ NOT NULL,
    step          TEXT NOT NULL,
    params        JSONB,
    git_sha       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE backtest_result (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES backtest_run(run_id),
    outcome_id     BIGINT NOT NULL REFERENCES outcome(outcome_id),
    entry_as_of    TIMESTAMPTZ NOT NULL,
    entry_price    NUMERIC NOT NULL,
    size           NUMERIC NOT NULL,
    resolved_value NUMERIC NOT NULL,
    fee_paid       NUMERIC NOT NULL,
    realized_pnl   NUMERIC NOT NULL,
    UNIQUE (run_id, outcome_id, entry_as_of)
);
CREATE INDEX ON backtest_result (run_id);
