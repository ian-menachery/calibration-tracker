"""Pure parse/mapping tests for the Kalshi venue module (no network)."""

from datetime import datetime, timezone

from calibration.kalshi.discovery import (
    KalshiMarket,
    _is_settled_binary,
    to_market,
)

_RAW = {
    "ticker": "KXBTCD-26JUN2916-T69299.99",
    "event_ticker": "KXBTCD-26JUN2916",
    "title": "Bitcoin above 69299.99 at noon?",
    "market_type": "binary",
    "result": "yes",
    "open_time": "2026-06-29T15:00:00Z",
    "close_time": "2026-06-29T16:00:00Z",
    "created_time": "2026-06-28T12:00:00Z",
    "volume_fp": "1234.0",
    "notional_value_dollars": "5000.0",
}


def test_to_market_maps_kalshi_fields():
    m = KalshiMarket.model_validate(_RAW)
    mk = to_market(m, "crypto", datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert mk.venue == "kalshi"
    assert mk.market_id == "KXBTCD-26JUN2916-T69299.99"
    assert mk.resolved_outcome == "YES" and mk.resolved_value == 1.0
    assert mk.category == "crypto"
    assert mk.end_date == datetime(2026, 6, 29, 16, 0, tzinfo=timezone.utc)
    assert mk.created_at == datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    assert mk.total_volume_usd == 5000.0  # prefers notional dollars
    assert mk.yes_token_id is None


def test_to_market_no_result_is_no_outcome():
    m = KalshiMarket.model_validate({**_RAW, "result": "no"})
    mk = to_market(m, "crypto", datetime(2026, 6, 30, tzinfo=timezone.utc))
    assert mk.resolved_outcome == "NO" and mk.resolved_value == 0.0


def test_is_settled_binary_excludes_mve_and_unsettled():
    assert _is_settled_binary(KalshiMarket.model_validate(_RAW)) is True
    assert _is_settled_binary(KalshiMarket.model_validate({**_RAW, "mve_collection_ticker": "MVE-1"})) is False
    assert _is_settled_binary(KalshiMarket.model_validate({**_RAW, "result": None})) is False
    assert _is_settled_binary(KalshiMarket.model_validate({**_RAW, "market_type": "scalar"})) is False
