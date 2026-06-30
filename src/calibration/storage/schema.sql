-- Schema for the calibration tracker. See ARCHITECTURE.md sec 4 for the data model.

CREATE TABLE IF NOT EXISTS markets (
    market_id        TEXT PRIMARY KEY,
    slug             TEXT NOT NULL,
    question         TEXT NOT NULL,
    category         TEXT,
    market_type      TEXT NOT NULL,
    parent_event_id  TEXT,
    end_date         TEXT NOT NULL,    -- ISO 8601 UTC; sourced from Gamma umaEndDate / closedTime, not endDate (see NOTES.md)
    resolved_outcome TEXT,
    resolved_value   REAL,
    total_volume_usd REAL,
    fetched_at       TEXT NOT NULL,    -- ISO 8601 UTC
    yes_token_id     TEXT,             -- CLOB token id for the YES outcome; needed by Stage 2
    gamma_event_id   TEXT,             -- Gamma event id; needed by fetch-tags to look up category tags via /events/{id}
    created_at       TEXT,             -- ISO 8601 UTC; Gamma createdAt. Market origin, for time-to-resolution. Backfilled.
    venue            TEXT NOT NULL DEFAULT 'polymarket'  -- 'polymarket' | 'kalshi' (v2 Phase 5 cross-venue)
);

CREATE TABLE IF NOT EXISTS market_tags (
    market_id  TEXT NOT NULL,
    tag_slug   TEXT NOT NULL,
    PRIMARY KEY (market_id, tag_slug),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

CREATE TABLE IF NOT EXISTS raw_price_history (
    market_id  TEXT NOT NULL,
    timestamp  TEXT NOT NULL,          -- ISO 8601 UTC
    price      REAL NOT NULL,
    PRIMARY KEY (market_id, timestamp),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    market_id     TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,       -- 'close', '1h', '24h', '7d'
    price         REAL NOT NULL,
    observed_at   TEXT NOT NULL,       -- ISO 8601 UTC; the actual tick selected, not the target time
    PRIMARY KEY (market_id, snapshot_type),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

-- Phase 4 forward test: paper signals logged live against the frozen rule, then
-- settled at resolution. One row per (market_id, horizon); entry is locked on first scan.
CREATE TABLE IF NOT EXISTS forward_signals (
    market_id      TEXT NOT NULL,
    venue          TEXT NOT NULL,
    horizon        TEXT NOT NULL,        -- '24h' / '7d'
    observed_at    TEXT NOT NULL,        -- ISO 8601 UTC; when the signal was logged
    category       TEXT,
    market_price   REAL NOT NULL,        -- mid YES price at entry
    side           TEXT NOT NULL,        -- 'YES' / 'NO'
    q_hat          REAL NOT NULL,        -- recalibrated fair prob (point)
    q_used         REAL NOT NULL,        -- conservative bound used for sizing
    edge_gross     REAL NOT NULL,
    half_spread    REAL NOT NULL,
    fee            REAL NOT NULL,
    edge_net       REAL NOT NULL,
    stake_fraction REAL NOT NULL,        -- fractional Kelly stake
    entry_price    REAL NOT NULL,        -- realizable spread-crossed entry price
    end_date       TEXT NOT NULL,        -- market resolution time
    status         TEXT NOT NULL,        -- 'open' / 'resolved' / 'void'
    resolved_value REAL,                 -- filled at settle
    pnl            REAL,                  -- realized P&L per contract at settle
    realized_minus_predicted REAL,       -- realized edge - predicted edge (efficiency tax)
    settled_at     TEXT,
    PRIMARY KEY (market_id, horizon)
);
