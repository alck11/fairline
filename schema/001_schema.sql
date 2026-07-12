-- ============================================================================
-- fairline : storage schema  (PostgreSQL 15+ with TimescaleDB)
-- ----------------------------------------------------------------------------
-- Design notes
--   * "cold" time-series (orderbooks, trades, point-in-time wallet scores)
--     live in hypertables so you can replay history for backtests.
--   * "hot" best-bid/ask state is kept in Redis at runtime, NOT here.
--   * prices are stored as NUMERIC in [0,1] (probability == price in USDC).
--   * one row per OUTCOME, not per market, so multi-outcome markets work.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- reference / dimension tables
-- ---------------------------------------------------------------------------
CREATE TABLE venue (
    venue       TEXT PRIMARY KEY            -- 'polymarket' | 'kalshi'
);
INSERT INTO venue VALUES ('polymarket'), ('kalshi') ON CONFLICT DO NOTHING;

-- A market = one tradable event on one venue. Outcomes are rows in outcome.
CREATE TABLE market (
    market_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue            TEXT NOT NULL REFERENCES venue(venue),
    external_id      TEXT NOT NULL,         -- venue's own id / conditionId / ticker
    question         TEXT NOT NULL,
    category         TEXT NOT NULL,         -- 'politics','crypto','sports',...
    resolution_text  TEXT,                  -- the rules; used by the matcher
    fee_rate         NUMERIC,               -- venue+category taker coefficient
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolves_at      TIMESTAMPTZ,
    resolved         BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (venue, external_id)
);

CREATE TABLE outcome (
    outcome_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    market_id    BIGINT NOT NULL REFERENCES market(market_id),
    label        TEXT NOT NULL,             -- 'YES','NO' or candidate name
    idx          SMALLINT NOT NULL,         -- 0,1,... position within market
    resolved_value NUMERIC,                 -- 1.0 / 0.0 once settled, else NULL
    UNIQUE (market_id, idx)
);

-- Cross-venue equivalence: "these two outcomes are the same real-world event."
-- Written by the market matcher: embeddings only triage (discard or escalate);
-- only Claude (reading both resolution rule-sets) or a human writes a link (ADR-0002).
CREATE TABLE market_link (
    link_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    outcome_a     BIGINT NOT NULL REFERENCES outcome(outcome_id),
    outcome_b     BIGINT NOT NULL REFERENCES outcome(outcome_id),
    polarity      SMALLINT NOT NULL DEFAULT 1,   -- 1: a==b ; -1: a == NOT b
    confidence    NUMERIC NOT NULL,              -- 0..1
    method        TEXT NOT NULL,                 -- 'llm','manual' (never 'embedding' — ADR-0002)
    verified      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (outcome_a <> outcome_b),
    UNIQUE (outcome_a, outcome_b)
);

-- ---------------------------------------------------------------------------
-- time-series : orderbook snapshots  (hypertable)
-- ---------------------------------------------------------------------------
CREATE TABLE orderbook_snapshot (
    ts          TIMESTAMPTZ NOT NULL,
    outcome_id  BIGINT NOT NULL REFERENCES outcome(outcome_id),
    best_bid    NUMERIC,
    best_ask    NUMERIC,
    bid_size    NUMERIC,
    ask_size    NUMERIC,
    levels      JSONB,                 -- optional full depth: {"bids":[[p,sz]],"asks":[[p,sz]]}
    PRIMARY KEY (outcome_id, ts)
);
SELECT create_hypertable('orderbook_snapshot', 'ts',
                         chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON orderbook_snapshot (outcome_id, ts DESC);

-- on-venue trade prints (useful for slippage models / volume features)
CREATE TABLE trade_print (
    ts          TIMESTAMPTZ NOT NULL,
    outcome_id  BIGINT NOT NULL REFERENCES outcome(outcome_id),
    price       NUMERIC NOT NULL,
    size        NUMERIC NOT NULL,
    aggressor   TEXT,                  -- 'buy'|'sell'
    PRIMARY KEY (outcome_id, ts, price, size)
);
SELECT create_hypertable('trade_print', 'ts',
                         chunk_time_interval => INTERVAL '1 day');

-- ---------------------------------------------------------------------------
-- wallets  (copy-trade subsystem)
-- ---------------------------------------------------------------------------
CREATE TABLE wallet (
    wallet       TEXT PRIMARY KEY,      -- 0x... proxy address
    x_handle     TEXT,
    first_seen   TIMESTAMPTZ,
    last_seen    TIMESTAMPTZ
);

-- one row per resolved position; this is the raw input to feature engineering
CREATE TABLE wallet_trade (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    wallet         TEXT NOT NULL REFERENCES wallet(wallet),
    market_id      BIGINT REFERENCES market(market_id),
    category       TEXT NOT NULL,
    side           TEXT NOT NULL,         -- 'buy_yes','buy_no', normalized
    size           NUMERIC NOT NULL,
    entry_price    NUMERIC NOT NULL,
    entry_ts       TIMESTAMPTZ NOT NULL,
    resolve_ts     TIMESTAMPTZ,
    resolved_value NUMERIC,               -- 1/0 for the outcome they hold
    fee_paid       NUMERIC NOT NULL DEFAULT 0,
    realized_pnl   NUMERIC                -- size*(resolved_value-entry_price)-fee
);
CREATE INDEX ON wallet_trade (wallet, resolve_ts);
CREATE INDEX ON wallet_trade (category, resolve_ts);

-- point-in-time wallet scores (hypertable so you never leak future info)
CREATE TABLE wallet_score (
    as_of               TIMESTAMPTZ NOT NULL,
    wallet              TEXT NOT NULL REFERENCES wallet(wallet),
    score               NUMERIC,          -- 0..100 composite
    n_resolved          INTEGER,
    win_rate            NUMERIC,
    realized_pnl        NUMERIC,
    roi                 NUMERIC,
    sharpe              NUMERIC,
    max_drawdown        NUMERIC,
    avg_hold_hours      NUMERIC,
    hhi_category        NUMERIC,          -- 0..1 concentration
    pnl_7d              NUMERIC,
    pnl_30d             NUMERIC,
    pnl_90d             NUMERIC,
    longest_loss_streak INTEGER,
    PRIMARY KEY (wallet, as_of)
);
SELECT create_hypertable('wallet_score', 'as_of',
                         chunk_time_interval => INTERVAL '7 days');

-- ---------------------------------------------------------------------------
-- detection + execution audit trail
-- ---------------------------------------------------------------------------
CREATE TABLE arb_opportunity (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind          TEXT NOT NULL,          -- 'complete_set'|'cross_venue'
    legs          JSONB NOT NULL,         -- [{outcome_id,venue,side,price,size}]
    gross_edge    NUMERIC NOT NULL,       -- per $1 of payout
    total_fees    NUMERIC NOT NULL,
    net_edge      NUMERIC NOT NULL,
    roi           NUMERIC NOT NULL,
    max_size      NUMERIC NOT NULL,
    detect_ms     NUMERIC                 -- book-update -> opportunity latency
);
CREATE INDEX ON arb_opportunity (ts DESC);

CREATE TABLE execution (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    opportunity_id  BIGINT REFERENCES arb_opportunity(id),
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode            TEXT NOT NULL,         -- 'paper'|'live'
    status          TEXT NOT NULL,         -- 'filled'|'partial'|'rejected'|'aborted'
    legs            JSONB NOT NULL,
    realized_pnl    NUMERIC,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- example continuous aggregate: 1-minute best bid/ask (handy for backtests/UI)
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW obook_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket,
       outcome_id,
       last(best_bid, ts) AS bid,
       last(best_ask, ts) AS ask
FROM orderbook_snapshot
GROUP BY bucket, outcome_id
WITH NO DATA;
