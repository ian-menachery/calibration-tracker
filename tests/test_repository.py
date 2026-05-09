from datetime import datetime, timedelta, timezone

import pytest

from calibration.storage.repository import (
    Market,
    PriceTick,
    Snapshot,
    TrainingFeatures,
    count_markets,
    count_training_features,
    get_market,
    get_tags_for_market,
    get_ticks_for_market,
    get_training_features,
    init_db,
    insert_market_tags,
    insert_price_ticks,
    markets_missing_history,
    markets_missing_tags,
    upsert_markets,
    upsert_snapshots,
    upsert_training_features,
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
        yes_token_id="21742633143463906290569050155826241533067272736897614950488156847949938836455",
        gamma_event_id="158299",
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


# ---------- raw_price_history ----------

def _tick(market_id: str, minute_offset: int, price: float) -> PriceTick:
    base = datetime(2024, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
    return PriceTick(
        market_id=market_id,
        timestamp=base + timedelta(minutes=minute_offset),
        price=price,
    )


def test_insert_price_ticks_roundtrip(conn):
    upsert_markets(conn, [_market("0xa")])
    ticks = [_tick("0xa", 0, 0.5), _tick("0xa", 60, 0.6), _tick("0xa", 120, 0.7)]
    insert_price_ticks(conn, ticks)
    got = get_ticks_for_market(conn, "0xa")
    assert got == ticks


def test_get_ticks_for_market_returns_sorted(conn):
    upsert_markets(conn, [_market("0xa")])
    insert_price_ticks(conn, [_tick("0xa", 120, 0.7), _tick("0xa", 0, 0.5), _tick("0xa", 60, 0.6)])
    got = get_ticks_for_market(conn, "0xa")
    assert [t.price for t in got] == [0.5, 0.6, 0.7]


def test_insert_price_ticks_is_idempotent(conn):
    upsert_markets(conn, [_market("0xa")])
    t = _tick("0xa", 0, 0.5)
    insert_price_ticks(conn, [t])
    insert_price_ticks(conn, [t])
    assert len(get_ticks_for_market(conn, "0xa")) == 1


def test_get_ticks_for_missing_market_returns_empty(conn):
    assert get_ticks_for_market(conn, "0xnope") == []


# ---------- price_snapshots ----------

def _snapshot(market_id: str, snapshot_type: str, price: float) -> Snapshot:
    return Snapshot(
        market_id=market_id,
        snapshot_type=snapshot_type,
        price=price,
        observed_at=datetime(2024, 11, 6, 14, 17, 41, tzinfo=timezone.utc),
    )


def test_upsert_snapshots_roundtrip(conn):
    upsert_markets(conn, [_market("0xa")])
    snaps = [_snapshot("0xa", "1h", 0.99), _snapshot("0xa", "24h", 0.63)]
    upsert_snapshots(conn, snaps)
    rows = conn.execute(
        "SELECT snapshot_type, price FROM price_snapshots WHERE market_id = ? ORDER BY snapshot_type",
        ("0xa",),
    ).fetchall()
    assert rows == [("1h", 0.99), ("24h", 0.63)]


def test_upsert_snapshots_overwrites_on_conflict(conn):
    upsert_markets(conn, [_market("0xa")])
    upsert_snapshots(conn, [_snapshot("0xa", "1h", 0.50)])
    upsert_snapshots(conn, [_snapshot("0xa", "1h", 0.99)])
    rows = conn.execute(
        "SELECT price FROM price_snapshots WHERE market_id = ? AND snapshot_type = ?",
        ("0xa", "1h"),
    ).fetchall()
    assert rows == [(0.99,)]


# ---------- markets_missing_history ----------

def test_markets_missing_history_empty_when_all_have_ticks(conn):
    upsert_markets(conn, [_market("0xa"), _market("0xb")])
    insert_price_ticks(conn, [_tick("0xa", 0, 0.5), _tick("0xb", 0, 0.5)])
    assert markets_missing_history(conn) == []


def test_markets_missing_history_returns_unticked_markets(conn):
    upsert_markets(conn, [_market("0xa"), _market("0xb"), _market("0xc")])
    insert_price_ticks(conn, [_tick("0xa", 0, 0.5)])
    assert sorted(markets_missing_history(conn)) == ["0xb", "0xc"]


# ---------- market_tags ----------

def test_insert_market_tags_roundtrip(conn):
    upsert_markets(conn, [_market("0xa")])
    insert_market_tags(conn, [("0xa", "sports"), ("0xa", "nba")])
    assert get_tags_for_market(conn, "0xa") == ["nba", "sports"]  # ORDER BY tag_slug


def test_insert_market_tags_is_idempotent(conn):
    upsert_markets(conn, [_market("0xa")])
    insert_market_tags(conn, [("0xa", "sports")])
    insert_market_tags(conn, [("0xa", "sports")])
    assert get_tags_for_market(conn, "0xa") == ["sports"]


def test_get_tags_for_missing_market_returns_empty(conn):
    assert get_tags_for_market(conn, "0xnope") == []


def test_markets_missing_tags_skips_markets_without_event_id(conn):
    # Two markets — one with event_id set (eligible for fetch-tags) and one without.
    upsert_markets(conn, [
        _market("0xa", gamma_event_id="evt-1"),
        _market("0xb", gamma_event_id=None),
    ])
    pairs = markets_missing_tags(conn)
    assert pairs == [("0xa", "evt-1")]  # 0xb is excluded because event_id is None


def test_markets_missing_tags_excludes_already_tagged_markets(conn):
    upsert_markets(conn, [
        _market("0xa", gamma_event_id="evt-1"),
        _market("0xb", gamma_event_id="evt-2"),
    ])
    insert_market_tags(conn, [("0xa", "sports")])
    pairs = markets_missing_tags(conn)
    assert pairs == [("0xb", "evt-2")]


# ---------- training_features (v2.0a) ----------

def _features(market_id: str = "0xa", **overrides) -> TrainingFeatures:
    base = dict(
        market_id=market_id,
        snapshot_type="7d",
        target=0.09,
        category="sports",
        tag_count=3,
        log_total_volume_usd=14.5,
        market_age_days_at_t7d=120.0,
        total_market_lifespan_days=127.0,
        price_t7d=0.7,
        price_t7d_dist_to_half=0.2,
        price_t7d_above_half=1,
        price_t14d=0.6,
        drift_t14d_to_t7d=0.1,
        realized_vol_t14d_to_t7d=0.05,
        max_abs_move_t14d_to_t7d=0.08,
        sign_flip_count_t14d_to_t7d=0,
        end_date_dow=2,
        end_date_month=11,
        end_date_year=2024,
        built_at=datetime(2026, 5, 8, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TrainingFeatures(**base)


def test_training_features_empty_db(conn):
    assert count_training_features(conn) == 0
    assert get_training_features(conn) == []


def test_training_features_roundtrip(conn):
    upsert_markets(conn, [_market("0xa")])
    f = _features("0xa")
    upsert_training_features(conn, [f])
    got = get_training_features(conn)
    assert got == [f]


def test_training_features_idempotent_overwrites_on_market_id(conn):
    upsert_markets(conn, [_market("0xa")])
    upsert_training_features(conn, [_features("0xa", target=0.05)])
    upsert_training_features(conn, [_features("0xa", target=0.10)])
    assert count_training_features(conn) == 1
    got = get_training_features(conn)
    assert got[0].target == 0.10


def test_training_features_returns_sorted_by_market_id(conn):
    upsert_markets(conn, [_market("0xa"), _market("0xb"), _market("0xc")])
    upsert_training_features(conn, [_features("0xc"), _features("0xa"), _features("0xb")])
    got = get_training_features(conn)
    assert [f.market_id for f in got] == ["0xa", "0xb", "0xc"]


def test_training_features_handles_null_optional_fields(conn):
    """All Optional[...] fields should roundtrip None correctly (SQLite NULL)."""
    upsert_markets(conn, [_market("0xa")])
    f = _features(
        "0xa",
        category=None,
        tag_count=None,
        log_total_volume_usd=None,
        market_age_days_at_t7d=None,
        total_market_lifespan_days=None,
        price_t14d=None,
        drift_t14d_to_t7d=None,
        realized_vol_t14d_to_t7d=None,
        max_abs_move_t14d_to_t7d=None,
        sign_flip_count_t14d_to_t7d=None,
        end_date_dow=None,
        end_date_month=None,
        end_date_year=None,
    )
    upsert_training_features(conn, [f])
    got = get_training_features(conn)
    assert got == [f]
