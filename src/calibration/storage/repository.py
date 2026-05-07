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
    # Ad-hoc migration: pre-3a-fix DBs are missing markets.yes_token_id.
    # CREATE TABLE IF NOT EXISTS skips altering existing tables, so add it here.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(markets)").fetchall()}
    if "yes_token_id" not in cols:
        conn.execute("ALTER TABLE markets ADD COLUMN yes_token_id TEXT")
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
        )
        for m in markets
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO markets (
            market_id, slug, question, category, market_type, parent_event_id,
            end_date, resolved_outcome, resolved_value, total_volume_usd, fetched_at,
            yes_token_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
