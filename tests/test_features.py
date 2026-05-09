import math
from datetime import datetime, timedelta, timezone

import pytest

from calibration.modeling.features import (
    build_features_for_market,
    compute_drift,
    compute_max_abs_move,
    compute_realized_vol,
    compute_sign_flip_count,
)
from calibration.storage.repository import Market, PriceTick, Snapshot


END = datetime(2024, 11, 6, 15, 17, 41, tzinfo=timezone.utc)
T7D = END - timedelta(days=7)
T14D = END - timedelta(days=14)
BUILT = datetime(2026, 5, 8, tzinfo=timezone.utc)


# ---------- compute_drift ----------

def test_drift_positive():
    assert compute_drift(0.5, 0.7) == pytest.approx(0.2)


def test_drift_negative():
    assert compute_drift(0.7, 0.5) == pytest.approx(-0.2)


def test_drift_zero():
    assert compute_drift(0.5, 0.5) == 0.0


# ---------- compute_realized_vol ----------

def test_vol_constant_price_is_zero():
    assert compute_realized_vol([0.5, 0.5, 0.5, 0.5]) == 0.0


def test_vol_two_or_fewer_ticks_returns_none():
    assert compute_realized_vol([]) is None
    assert compute_realized_vol([0.5]) is None
    assert compute_realized_vol([0.5, 0.6]) is None  # 1 diff is not enough for sample variance


def test_vol_known_alternating_sequence():
    # diffs of [0.5, 0.6, 0.5, 0.6] -> [+0.1, -0.1, +0.1]; mean=1/30; sample stddev computable.
    v = compute_realized_vol([0.5, 0.6, 0.5, 0.6])
    assert v is not None
    # Expected: diffs=[0.1,-0.1,0.1], mean≈0.0333, var≈((0.0667)^2+(-0.1333)^2+(0.0667)^2)/2 ≈ 0.0133, stddev ≈ 0.1155
    assert v == pytest.approx(0.11547, rel=1e-3)


# ---------- compute_max_abs_move ----------

def test_max_move_simple():
    assert compute_max_abs_move([0.5, 0.6, 0.4]) == pytest.approx(0.2)


def test_max_move_too_few_ticks():
    assert compute_max_abs_move([]) is None
    assert compute_max_abs_move([0.5]) is None


def test_max_move_zero_for_constant_price():
    assert compute_max_abs_move([0.5, 0.5, 0.5]) == 0.0


# ---------- compute_sign_flip_count ----------

def test_sign_flips_zero_when_all_same_side():
    assert compute_sign_flip_count([0.4, 0.4, 0.3, 0.45]) == 0
    assert compute_sign_flip_count([0.6, 0.7, 0.55, 0.99]) == 0


def test_sign_flips_one_crossing_up():
    assert compute_sign_flip_count([0.4, 0.6]) == 1


def test_sign_flips_multiple_crossings():
    assert compute_sign_flip_count([0.4, 0.6, 0.4, 0.6]) == 3


def test_sign_flips_at_exactly_half_counts_as_above():
    # Convention: 0.5 is treated as >=0.5 (strict-< on the lower side)
    assert compute_sign_flip_count([0.4, 0.5]) == 1
    assert compute_sign_flip_count([0.5, 0.5]) == 0
    assert compute_sign_flip_count([0.5, 0.4]) == 1


def test_sign_flips_empty_or_singleton():
    assert compute_sign_flip_count([]) == 0
    assert compute_sign_flip_count([0.5]) == 0


# ---------- build_features_for_market ----------

def _market(market_id: str = "0xa", **overrides) -> Market:
    base = dict(
        market_id=market_id,
        slug="will-trump-win-iowa",
        question="Will Trump win Iowa?",
        category=None,
        market_type="binary",
        parent_event_id=None,
        end_date=END,
        resolved_outcome="YES",
        resolved_value=1.0,
        total_volume_usd=10_000_000.0,
        fetched_at=BUILT,
        yes_token_id="tok",
        gamma_event_id="evt",
    )
    base.update(overrides)
    return Market(**base)


def _snapshot_t7d(price: float = 0.7) -> Snapshot:
    return Snapshot(
        market_id="0xa", snapshot_type="7d", price=price, observed_at=T7D
    )


def _ticks_hourly(window_start: datetime, window_end: datetime, price: float = 0.5) -> list[PriceTick]:
    """Generate hourly ticks across [window_start, window_end] at constant price."""
    ticks = []
    t = window_start
    while t <= window_end:
        ticks.append(PriceTick(market_id="0xa", timestamp=t, price=price))
        t = t + timedelta(hours=1)
    return ticks


def test_build_features_target_is_squared_residual():
    # price 0.7, resolved YES (1.0) -> target = (0.7-1.0)^2 = 0.09
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(0.7),
        _ticks_hourly(T14D, T7D, price=0.7),
        tags=["trump", "politics"],
        built_at=BUILT,
    )
    assert f.target == pytest.approx(0.09)


def test_build_features_happy_path():
    # 14 days of hourly ticks, drift from 0.6 → 0.7 within window (mocked via single price; drift uses t14d ↔ t7d)
    ticks = _ticks_hourly(T14D, T7D, price=0.7)
    # Override the T-14d tick to be 0.6 so drift is +0.1
    ticks[0] = PriceTick(market_id="0xa", timestamp=T14D, price=0.6)
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(0.7),
        ticks,
        tags=["trump", "politics"],
        built_at=BUILT,
    )
    assert f.market_id == "0xa"
    assert f.snapshot_type == "7d"
    assert f.category == "politics"  # from tags
    assert f.tag_count == 2
    assert f.price_t7d == 0.7
    assert f.price_t7d_dist_to_half == pytest.approx(0.2)
    assert f.price_t7d_above_half == 1
    assert f.price_t14d == pytest.approx(0.6)
    assert f.drift_t14d_to_t7d == pytest.approx(0.1)
    assert f.end_date_year == 2024
    assert f.end_date_month == 11
    assert f.log_total_volume_usd == pytest.approx(math.log1p(10_000_000.0))


def test_build_features_no_t14d_data_yields_none_drift():
    # Only ticks from T-5d onward; no T-14d coverage
    ticks = _ticks_hourly(END - timedelta(days=5), T7D, price=0.7)
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(0.7),
        ticks,
        tags=["politics"],
        built_at=BUILT,
    )
    assert f.price_t14d is None
    assert f.drift_t14d_to_t7d is None


def test_build_features_constant_price_window():
    ticks = _ticks_hourly(T14D, T7D, price=0.5)
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(0.5),
        ticks,
        tags=["politics"],
        built_at=BUILT,
    )
    assert f.realized_vol_t14d_to_t7d == 0.0
    assert f.max_abs_move_t14d_to_t7d == 0.0
    assert f.sign_flip_count_t14d_to_t7d == 0
    # price exactly at 0.5 → not above_half (strict >)
    assert f.price_t7d_above_half == 0
    assert f.price_t7d_dist_to_half == 0.0


def test_build_features_no_ticks_at_all():
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(0.7),
        ticks=[],
        tags=["politics"],
        built_at=BUILT,
    )
    assert f.market_age_days_at_t7d is None
    assert f.total_market_lifespan_days is None
    assert f.price_t14d is None
    assert f.drift_t14d_to_t7d is None
    assert f.realized_vol_t14d_to_t7d is None
    assert f.max_abs_move_t14d_to_t7d is None
    assert f.sign_flip_count_t14d_to_t7d == 0


def test_build_features_market_age_uses_first_tick():
    # First tick is 100 days before end_date; market is 100 days old in total
    first_ts = END - timedelta(days=100)
    ticks = [PriceTick(market_id="0xa", timestamp=first_ts, price=0.5)]
    ticks.extend(_ticks_hourly(T14D, T7D, price=0.5))
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(0.5),
        ticks,
        tags=["politics"],
        built_at=BUILT,
    )
    assert f.market_age_days_at_t7d == pytest.approx(93.0, abs=0.01)  # 100 - 7
    assert f.total_market_lifespan_days == pytest.approx(100.0, abs=0.01)


def test_build_features_target_perfect_calibration():
    # price 1.0, resolved YES (1.0) -> target = 0
    f = build_features_for_market(
        _market(),
        _snapshot_t7d(1.0),
        _ticks_hourly(T14D, T7D, price=1.0),
        tags=["politics"],
        built_at=BUILT,
    )
    assert f.target == 0.0
