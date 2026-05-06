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


def init_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_PATH.read_text())
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
        )
        for m in markets
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO markets (
            market_id, slug, question, category, market_type, parent_event_id,
            end_date, resolved_outcome, resolved_value, total_volume_usd, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
