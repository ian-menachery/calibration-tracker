"""Storage layer for the markets table. No business logic; reads and writes only.

Datetimes are stored as ISO 8601 strings (UTC) to dodge sqlite3's deprecated
auto-adapters in 3.12+. Conversion happens at the boundary of each function.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Iterable

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@dataclass(frozen=True)
class Market:
    market_id: str
    slug: str
    question: str
    category: str | None
    market_type: str
    parent_event_id: str | None
    end_date: datetime
    resolved_outcome: str | None
    resolved_value: float | None
    total_volume_usd: float | None
    fetched_at: datetime
    yes_token_id: str | None  # nullable for migrated rows pre-backfill; always set after re-discover
    gamma_event_id: str | None  # nullable; populated by re-discover, used by fetch-tags
    created_at: datetime | None = None  # Gamma createdAt; nullable until backfilled (backfill-created)


@dataclass(frozen=True)
class PriceTick:
    market_id: str
    timestamp: datetime
    price: float


@dataclass(frozen=True)
class Snapshot:
    market_id: str
    snapshot_type: str  # 'close', '1h', '24h', '7d'
    price: float
    observed_at: datetime


def init_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_PATH.read_text())
    # Ad-hoc migrations: CREATE TABLE IF NOT EXISTS skips altering existing
    # tables, so add new columns here. Pattern: PRAGMA table_info check +
    # ALTER TABLE ADD COLUMN (see notes/NOTES.md for the rationale).
    cols = {row[1] for row in conn.execute("PRAGMA table_info(markets)").fetchall()}
    if "yes_token_id" not in cols:
        conn.execute("ALTER TABLE markets ADD COLUMN yes_token_id TEXT")
    if "gamma_event_id" not in cols:
        conn.execute("ALTER TABLE markets ADD COLUMN gamma_event_id TEXT")
    if "created_at" not in cols:
        conn.execute("ALTER TABLE markets ADD COLUMN created_at TEXT")
    # Drop the inert training_features table left in local DBs by the rolled-back
    # v2 modeling spike. init_db no longer creates it; this clears stragglers.
    # (Its 2,905 rows are unrelated to the T-7d 2,905-market cohort — coincidence.)
    conn.execute("DROP TABLE IF EXISTS training_features")
    conn.commit()
    return conn


def upsert_markets(conn: sqlite3.Connection, markets: Iterable[Market]) -> int:
    rows = [
        (
            m.market_id,
            m.slug,
            m.question,
            m.category,
            m.market_type,
            m.parent_event_id,
            m.end_date.isoformat(),
            m.resolved_outcome,
            m.resolved_value,
            m.total_volume_usd,
            m.fetched_at.isoformat(),
            m.yes_token_id,
            m.gamma_event_id,
            m.created_at.isoformat() if m.created_at else None,
        )
        for m in markets
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO markets (
            market_id, slug, question, category, market_type, parent_event_id,
            end_date, resolved_outcome, resolved_value, total_volume_usd, fetched_at,
            yes_token_id, gamma_event_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def count_markets(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]


def get_market(conn: sqlite3.Connection, market_id: str) -> Market | None:
    cols = [f.name for f in fields(Market)]
    row = conn.execute(
        f"SELECT {', '.join(cols)} FROM markets WHERE market_id = ?",
        (market_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(zip(cols, row))
    data["end_date"] = datetime.fromisoformat(data["end_date"])
    data["fetched_at"] = datetime.fromisoformat(data["fetched_at"])
    data["created_at"] = (
        datetime.fromisoformat(data["created_at"]) if data["created_at"] else None
    )
    return Market(**data)


def insert_price_ticks(conn: sqlite3.Connection, ticks: Iterable[PriceTick]) -> int:
    rows = [(t.market_id, t.timestamp.isoformat(), t.price) for t in ticks]
    # INSERT OR IGNORE: ticks for a (market_id, timestamp) are deterministic, so
    # re-fetching the same window should be a no-op rather than overwriting.
    conn.executemany(
        "INSERT OR IGNORE INTO raw_price_history (market_id, timestamp, price) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def get_ticks_for_market(conn: sqlite3.Connection, market_id: str) -> list[PriceTick]:
    rows = conn.execute(
        "SELECT timestamp, price FROM raw_price_history WHERE market_id = ? ORDER BY timestamp",
        (market_id,),
    ).fetchall()
    return [
        PriceTick(market_id=market_id, timestamp=datetime.fromisoformat(ts), price=p)
        for ts, p in rows
    ]


def upsert_snapshots(conn: sqlite3.Connection, snapshots: Iterable[Snapshot]) -> int:
    rows = [
        (s.market_id, s.snapshot_type, s.price, s.observed_at.isoformat())
        for s in snapshots
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO price_snapshots (market_id, snapshot_type, price, observed_at)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def markets_missing_history(conn: sqlite3.Connection) -> list[str]:
    """Market IDs that have zero ticks in raw_price_history. Drives Stage 2 resumability."""
    rows = conn.execute(
        """
        SELECT m.market_id FROM markets m
        LEFT JOIN raw_price_history h ON m.market_id = h.market_id
        WHERE h.market_id IS NULL
        """
    ).fetchall()
    return [r[0] for r in rows]


def markets_with_history(conn: sqlite3.Connection) -> list[str]:
    """Market IDs that have at least one row in raw_price_history. Drives Stage 3."""
    rows = conn.execute("SELECT DISTINCT market_id FROM raw_price_history").fetchall()
    return [r[0] for r in rows]


def insert_market_tags(
    conn: sqlite3.Connection, pairs: Iterable[tuple[str, str]]
) -> int:
    """INSERT OR IGNORE (market_id, tag_slug) pairs into market_tags.

    Idempotent — re-running fetch-tags is a no-op for already-stored tags.
    """
    rows = list(pairs)
    conn.executemany(
        "INSERT OR IGNORE INTO market_tags (market_id, tag_slug) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def get_tags_for_market(conn: sqlite3.Connection, market_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT tag_slug FROM market_tags WHERE market_id = ? ORDER BY tag_slug",
        (market_id,),
    ).fetchall()
    return [r[0] for r in rows]


def get_tags_for_markets(
    conn: sqlite3.Connection, market_ids: list[str]
) -> dict[str, list[str]]:
    """Bulk lookup: returns {market_id: [tag_slug, ...]} for the given ids.

    Used by Stage 4's load_calibration_frame to avoid N round-trips.
    """
    if not market_ids:
        return {}
    placeholders = ",".join("?" * len(market_ids))
    rows = conn.execute(
        f"SELECT market_id, tag_slug FROM market_tags WHERE market_id IN ({placeholders}) ORDER BY market_id, tag_slug",
        market_ids,
    ).fetchall()
    out: dict[str, list[str]] = {}
    for mid, slug in rows:
        out.setdefault(mid, []).append(slug)
    return out


def markets_missing_tags(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Markets with a known gamma_event_id but no rows in market_tags.

    Returns (market_id, gamma_event_id) pairs so fetch-tags can hit the
    Gamma /events/{id} endpoint without a second lookup.
    """
    rows = conn.execute(
        """
        SELECT m.market_id, m.gamma_event_id FROM markets m
        LEFT JOIN market_tags t ON m.market_id = t.market_id
        WHERE m.gamma_event_id IS NOT NULL
          AND t.market_id IS NULL
        """
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def markets_missing_created_at(conn: sqlite3.Connection) -> list[str]:
    """Market IDs with no created_at yet (rows discovered before the column existed).

    Drives backfill-created resumability — re-running only fetches the stragglers.
    """
    rows = conn.execute(
        "SELECT market_id FROM markets WHERE created_at IS NULL"
    ).fetchall()
    return [r[0] for r in rows]


def set_market_created_at(
    conn: sqlite3.Connection, pairs: Iterable[tuple[str, datetime]]
) -> int:
    """Set created_at for the given (market_id, datetime) pairs. Datetime -> ISO at the boundary."""
    rows = [(dt.isoformat(), mid) for mid, dt in pairs]
    conn.executemany("UPDATE markets SET created_at = ? WHERE market_id = ?", rows)
    conn.commit()
    return len(rows)


def min_tick_per_market(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(market_id, earliest tick timestamp ISO) for every market with price history.

    Feeds the tick-coverage data-quality check: a market whose first tick is less
    than 7 days before its end_date can't have a real T-7d snapshot.
    """
    rows = conn.execute(
        "SELECT market_id, MIN(timestamp) FROM raw_price_history GROUP BY market_id"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def select_snapshot_join(
    conn: sqlite3.Connection, snapshot_type: str
) -> list[tuple]:
    """markets x price_snapshots for one snapshot type. Drives Stage 4 analysis.

    Returns rows of (market_id, slug, predicted_price, resolved_value,
    total_volume_usd, end_date). Filters out rows missing resolved_value
    defensively (shouldn't happen with our discover filter, but the math
    can't handle NULL outcomes).
    """
    return conn.execute(
        """
        SELECT m.market_id, m.slug, s.price, m.resolved_value,
               m.total_volume_usd, m.end_date
        FROM markets m
        JOIN price_snapshots s ON s.market_id = m.market_id
        WHERE s.snapshot_type = ?
          AND m.resolved_value IS NOT NULL
        """,
        (snapshot_type,),
    ).fetchall()
