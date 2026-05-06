from datetime import datetime, timezone

import pytest

from calibration.storage.repository import (
    Market,
    count_markets,
    get_market,
    init_db,
    upsert_markets,
)


def _market(market_id: str = "0xabc", **overrides) -> Market:
    base = dict(
        market_id=market_id,
        slug="will-x-happen",
        question="Will X happen?",
        category="politics",
        market_type="binary",
        parent_event_id=None,
        end_date=datetime(2024, 11, 6, 15, 17, 41, tzinfo=timezone.utc),
        resolved_outcome="YES",
        resolved_value=1.0,
        total_volume_usd=12345.67,
        fetched_at=datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return Market(**base)


@pytest.fixture
def conn():
    c = init_db(":memory:")
    yield c
    c.close()


def test_empty_db_count_is_zero(conn):
    assert count_markets(conn) == 0


def test_insert_then_get_roundtrip(conn):
    m = _market()
    upsert_markets(conn, [m])
    got = get_market(conn, m.market_id)
    assert got == m


def test_count_after_inserts(conn):
    upsert_markets(conn, [_market("0x1"), _market("0x2"), _market("0x3")])
    assert count_markets(conn) == 3


def test_upsert_is_idempotent_on_market_id(conn):
    m = _market("0xdupe", resolved_value=0.0)
    upsert_markets(conn, [m])
    upsert_markets(conn, [m])
    assert count_markets(conn) == 1


def test_upsert_overwrites_existing_row(conn):
    upsert_markets(conn, [_market("0xsame", resolved_value=0.0, total_volume_usd=100.0)])
    upsert_markets(conn, [_market("0xsame", resolved_value=1.0, total_volume_usd=999.0)])
    got = get_market(conn, "0xsame")
    assert got is not None
    assert got.resolved_value == 1.0
    assert got.total_volume_usd == 999.0


def test_get_missing_market_returns_none(conn):
    assert get_market(conn, "does-not-exist") is None
