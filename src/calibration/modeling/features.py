"""v2.0: feature engineering for the predict-miscalibration pipeline.

Pure compute on data already loaded by the storage layer. This module
takes Python objects (Market, Snapshot, list[PriceTick], list[str]) and
returns TrainingFeatures rows. No SQL, no HTTP — just math.

Per CLAUDE.md, every helper here has a known-input test in
tests/test_features.py.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Sequence

from calibration.analysis.calibration import categorize_market
from calibration.storage.repository import (
    Market,
    PriceTick,
    Snapshot,
    TrainingFeatures,
)

# Tolerance for matching the T-14d anchor against raw_price_history.
# Hourly fidelity in the 14-day cache means a 12h window always contains
# at least one tick for markets whose cache reaches back to T-14d.
_T14D_TOLERANCE = timedelta(hours=12)


def compute_drift(price_start: float, price_end: float) -> float:
    return price_end - price_start


def compute_realized_vol(prices: Sequence[float]) -> float | None:
    """Sample-stddev of consecutive price differences. None if <3 ticks."""
    if len(prices) < 3:
        return None
    diffs = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    mean = sum(diffs) / len(diffs)
    var = sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)
    return math.sqrt(var)


def compute_max_abs_move(prices: Sequence[float]) -> float | None:
    if len(prices) < 2:
        return None
    return max(abs(prices[i + 1] - prices[i]) for i in range(len(prices) - 1))


def compute_sign_flip_count(prices: Sequence[float]) -> int:
    """Number of times consecutive prices straddle 0.5."""
    if len(prices) < 2:
        return 0
    flips = 0
    for i in range(len(prices) - 1):
        a, b = prices[i], prices[i + 1]
        if (a < 0.5 and b >= 0.5) or (a >= 0.5 and b < 0.5):
            flips += 1
    return flips


def _price_at_target(
    ticks: Sequence[PriceTick], target: datetime, tol: timedelta
) -> float | None:
    """Closest tick to `target` within `tol`; None if no tick in range."""
    candidates = [t for t in ticks if abs(t.timestamp - target) <= tol]
    if not candidates:
        return None
    return min(candidates, key=lambda t: abs(t.timestamp - target)).price


def build_features_for_market(
    market: Market,
    snapshot_t7d: Snapshot,
    ticks: Sequence[PriceTick],
    tags: list[str],
    built_at: datetime,
) -> TrainingFeatures:
    """Construct one TrainingFeatures row for a market.

    Caller is responsible for filtering: market.resolved_value not None,
    snapshot_t7d.snapshot_type == '7d', and ticks belong to this market.
    """
    end_date = market.end_date
    target_t7d = end_date - timedelta(days=7)
    target_t14d = end_date - timedelta(days=14)

    target = (snapshot_t7d.price - market.resolved_value) ** 2

    sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)

    # T-14d → T-7d window for trajectory features
    window_ticks = [t for t in sorted_ticks if target_t14d <= t.timestamp <= target_t7d]
    window_prices = [t.price for t in window_ticks]

    price_t14d = _price_at_target(sorted_ticks, target_t14d, _T14D_TOLERANCE)

    if sorted_ticks:
        first_tick_ts = sorted_ticks[0].timestamp
        # max(., 0) defends against the (theoretical) case where the cache's
        # first tick is later than T-7d for a very short market.
        market_age = max((target_t7d - first_tick_ts).total_seconds() / 86400.0, 0.0)
        total_lifespan = (end_date - first_tick_ts).total_seconds() / 86400.0
    else:
        market_age = None
        total_lifespan = None

    log_vol = (
        math.log1p(market.total_volume_usd) if market.total_volume_usd is not None else None
    )

    category = categorize_market(market.slug, tags)
    price_t7d = snapshot_t7d.price
    drift = (price_t7d - price_t14d) if price_t14d is not None else None
    vol = compute_realized_vol(window_prices)
    max_move = compute_max_abs_move(window_prices)
    flips = compute_sign_flip_count(window_prices)

    return TrainingFeatures(
        market_id=market.market_id,
        snapshot_type="7d",
        target=target,
        category=category,
        tag_count=len(tags),
        log_total_volume_usd=log_vol,
        market_age_days_at_t7d=market_age,
        total_market_lifespan_days=total_lifespan,
        price_t7d=price_t7d,
        price_t7d_dist_to_half=abs(price_t7d - 0.5),
        price_t7d_above_half=1 if price_t7d > 0.5 else 0,
        price_t14d=price_t14d,
        drift_t14d_to_t7d=drift,
        realized_vol_t14d_to_t7d=vol,
        max_abs_move_t14d_to_t7d=max_move,
        sign_flip_count_t14d_to_t7d=flips,
        end_date_dow=end_date.weekday(),
        end_date_month=end_date.month,
        end_date_year=end_date.year,
        built_at=built_at,
    )
