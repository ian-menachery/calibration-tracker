"""Known-input tests for the sized-rule math (analysis/edge.py) and the q-band."""

import numpy as np
import pytest

from calibration.analysis.edge import (
    edge,
    fractional_kelly,
    kalshi_fee,
    kelly_fraction,
    net_edge,
    passes_universe,
    side_for,
    simulate_position,
)
from calibration.analysis.recalibration import predict_band


def test_edge_and_side():
    assert edge(0.5, 0.6) == pytest.approx(0.1)
    assert side_for(0.5, 0.6) == "YES"   # fair > price -> back favorite
    assert side_for(0.10, 0.05) == "NO"  # fair < price -> fade longshot
    assert side_for(0.4, 0.4) is None


def test_kelly_fraction_yes_and_no():
    # YES: (q - p)/(1 - p) = (0.6 - 0.5)/0.5 = 0.2
    assert kelly_fraction(0.6, 0.5, "YES") == pytest.approx(0.2)
    # NO: (p - q)/p = (0.5 - 0.4)/0.5 = 0.2
    assert kelly_fraction(0.4, 0.5, "NO") == pytest.approx(0.2)


def test_kelly_fraction_clips_negative_to_zero():
    # Edge is actually on the other side -> Kelly clipped to 0, never short the thesis.
    assert kelly_fraction(0.4, 0.5, "YES") == 0.0
    assert kelly_fraction(0.6, 0.5, "NO") == 0.0


def test_kelly_fraction_handles_boundary_prices():
    assert kelly_fraction(0.9, 1.0, "YES") == 0.0  # p==1, no upside
    assert kelly_fraction(0.1, 0.0, "NO") == 0.0   # p==0, no upside


def test_fractional_kelly_scales_and_clips():
    assert fractional_kelly(0.2, 0.25) == pytest.approx(0.05)
    assert fractional_kelly(-0.3, 0.5) == 0.0


def test_net_edge_subtracts_costs():
    assert net_edge(0.10, 0.02, 0.0) == pytest.approx(0.08)
    assert net_edge(0.02, 0.03, 0.0) == pytest.approx(-0.01)  # eaten by spread


def test_kalshi_fee_is_p_times_one_minus_p():
    assert kalshi_fee(0.5) == pytest.approx(0.07 * 0.25)
    assert kalshi_fee(0.0) == 0.0
    assert kalshi_fee(1.0) == 0.0


def test_passes_universe_filter():
    assert passes_universe(2_000_000.0) is True
    assert passes_universe(500_000.0) is False           # below floor
    assert passes_universe(2_000_000.0, disputed=True) is False
    assert passes_universe(2_000_000.0, market_type="multi") is False
    assert passes_universe(None) is False


def test_simulate_position_yes_and_no():
    # YES, fair 0.6 > price 0.5, no spread: win pays 1 -> +0.5, loss -> -0.5.
    assert simulate_position(0.5, 0.6, 1.0) == ("YES", pytest.approx(0.1), pytest.approx(0.5))
    assert simulate_position(0.5, 0.6, 0.0) == ("YES", pytest.approx(0.1), pytest.approx(-0.5))
    # NO, fair 0.4 < price 0.5: NO wins when outcome=0 -> (1-0)-0.5 = +0.5.
    assert simulate_position(0.5, 0.4, 0.0) == ("NO", pytest.approx(0.1), pytest.approx(0.5))


def test_simulate_position_spread_reduces_pnl_and_flat_is_none():
    side, pred, pnl = simulate_position(0.5, 0.6, 1.0, half_spread=0.02)
    assert side == "YES" and pnl == pytest.approx(0.48)
    assert simulate_position(0.5, 0.5, 1.0) is None


def _simulate(a_true, b_true, n, seed):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.02, 0.98, size=n)
    prob = 1.0 / (1.0 + np.exp(-(a_true + b_true * np.log(p / (1.0 - p)))))
    y = (rng.uniform(size=n) < prob).astype(float)
    return p, y


def test_predict_band_brackets_point_and_orders():
    p, y = _simulate(0.0, 0.7, 8_000, seed=7)  # FLB: b<1
    grid = np.array([0.05, 0.5, 0.95])
    band = predict_band(p, y, grid, n_iter=200, rng=np.random.default_rng(0))
    assert np.all(band["q_lo"] <= band["q_hat"] + 1e-9)
    assert np.all(band["q_hat"] <= band["q_hi"] + 1e-9)
    # b<1 pulls a longshot price up and a favorite price down toward 0.5.
    assert band["q_hat"][0] > 0.05   # longshot fair prob above its price
    assert band["q_hat"][2] < 0.95   # favorite fair prob below its price


def test_predict_band_degenerate_returns_nan_band():
    grid = np.array([0.2, 0.8])
    band = predict_band(np.array([0.3, 0.7]), np.array([1.0, 1.0]), grid, n_iter=20)
    assert np.isnan(band["q_lo"]).all() and np.isnan(band["q_hi"]).all()
