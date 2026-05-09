from datetime import datetime, timedelta, timezone

from calibration.analysis.snapshots import extract_snapshots
from calibration.storage.repository import Market, PriceTick

END = datetime(2024, 11, 6, 15, 17, 41, tzinfo=timezone.utc)


def _market(end_date: datetime = END) -> Market:
    return Market(
        market_id="0xa",
        slug="will-x-happen",
        question="Will X happen?",
        category=None,
        market_type="binary",
        parent_event_id=None,
        end_date=end_date,
        resolved_outcome="YES",
        resolved_value=1.0,
        total_volume_usd=1_000_000.0,
        fetched_at=END,
        yes_token_id="tok",
        gamma_event_id="evt",
    )


def _ticks_minutely(span: timedelta, end: datetime = END, price: float = 0.5) -> list[PriceTick]:
    """Generate minute-spaced ticks ending at `end`, going back `span`."""
    n = int(span.total_seconds() // 60) + 1
    return [
        PriceTick(market_id="0xa", timestamp=end - timedelta(minutes=i), price=price + 0.001 * i)
        for i in range(n)
    ]


def test_dense_ticks_yields_all_four_snapshots():
    # 14 days of minute-spaced ticks ending at END.
    ticks = _ticks_minutely(timedelta(days=14))
    snaps = extract_snapshots(_market(), ticks)
    types = {s.snapshot_type for s in snaps}
    assert types == {"close", "1h", "24h", "7d"}


def test_only_3_days_of_history_omits_7d():
    ticks = _ticks_minutely(timedelta(days=3))
    snaps = extract_snapshots(_market(), ticks)
    types = {s.snapshot_type for s in snaps}
    assert "close" in types
    assert "1h" in types
    assert "24h" in types
    assert "7d" not in types  # closest tick is ~4 days off, well outside 12h tol


def test_end_date_in_future_yields_no_snapshots():
    future = datetime.now(timezone.utc) + timedelta(days=10)
    ticks = _ticks_minutely(timedelta(days=14), end=future)
    snaps = extract_snapshots(_market(end_date=future), ticks)
    assert snaps == []


def test_unsorted_input_still_extracts_correctly():
    ticks = _ticks_minutely(timedelta(days=14))
    shuffled = ticks[::-1]  # reversed (decreasing time)
    snaps = extract_snapshots(_market(), shuffled)
    assert {s.snapshot_type for s in snaps} == {"close", "1h", "24h", "7d"}


def test_tick_exactly_at_target_is_selected():
    # Place a tick exactly at end_date - 1h. Add filler ticks elsewhere.
    target_1h = END - timedelta(hours=1)
    ticks = [
        PriceTick(market_id="0xa", timestamp=target_1h, price=0.77),
        PriceTick(market_id="0xa", timestamp=END - timedelta(minutes=30), price=0.99),
        PriceTick(market_id="0xa", timestamp=END - timedelta(hours=2), price=0.10),
    ]
    snaps = extract_snapshots(_market(), ticks)
    one_h = next(s for s in snaps if s.snapshot_type == "1h")
    assert one_h.observed_at == target_1h
    assert one_h.price == 0.77


def test_close_omitted_when_no_tick_within_one_hour_of_end():
    # Last tick is 2 hours before end_date — outside 1h close tolerance.
    ticks = [
        PriceTick(market_id="0xa", timestamp=END - timedelta(hours=2), price=0.5),
        PriceTick(market_id="0xa", timestamp=END - timedelta(hours=24), price=0.5),
    ]
    snaps = extract_snapshots(_market(), ticks)
    types = {s.snapshot_type for s in snaps}
    assert "close" not in types


def test_no_ticks_yields_no_snapshots():
    assert extract_snapshots(_market(), []) == []
