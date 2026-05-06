-- Phase 2: markets table only. price_snapshots and raw_price_history come in Phase 3.
-- See ARCHITECTURE.md sec 4 for the full schema.

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
    fetched_at       TEXT NOT NULL     -- ISO 8601 UTC
);
