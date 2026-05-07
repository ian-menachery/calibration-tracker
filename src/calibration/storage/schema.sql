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
    yes_token_id     TEXT              -- CLOB token id for the YES outcome; needed by Stage 2
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
