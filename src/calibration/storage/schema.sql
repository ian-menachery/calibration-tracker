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
    gamma_event_id   TEXT              -- Gamma event id; needed by fetch-tags to look up category tags via /events/{id}
);

CREATE TABLE IF NOT EXISTS market_tags (
    market_id  TEXT NOT NULL,
    tag_slug   TEXT NOT NULL,
    PRIMARY KEY (market_id, tag_slug),
    FOREIGN KEY (market_id) REFERENCES markets(market_id)
);

-- v2.0: pre-computed feature table for the v2 modeling pipeline.
-- One row per (market, snapshot_type='7d') pair. Re-runnable via
-- INSERT OR REPLACE on the market_id PK. See ARCHITECTURE.md / v2 plan.
CREATE TABLE IF NOT EXISTS training_features (
    market_id                       TEXT PRIMARY KEY,
    snapshot_type                   TEXT NOT NULL,
    target                          REAL NOT NULL,
    category                        TEXT,
    tag_count                       INTEGER,
    log_total_volume_usd            REAL,
    market_age_days_at_t7d          REAL,
    total_market_lifespan_days      REAL,
    price_t7d                       REAL NOT NULL,
    price_t7d_dist_to_half          REAL NOT NULL,
    price_t7d_above_half            INTEGER NOT NULL,
    price_t14d                      REAL,
    drift_t14d_to_t7d               REAL,
    realized_vol_t14d_to_t7d        REAL,
    max_abs_move_t14d_to_t7d        REAL,
    sign_flip_count_t14d_to_t7d     INTEGER,
    end_date_dow                    INTEGER,
    end_date_month                  INTEGER,
    end_date_year                   INTEGER,
    built_at                        TEXT NOT NULL,
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
