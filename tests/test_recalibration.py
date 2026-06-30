"""Known-input tests for the FLB recalibration fit (analysis/recalibration.py)."""

import numpy as np
import pandas as pd
import pytest

from calibration.analysis.recalibration import (
    apply_recalibration,
    fit_logit_recalibration,
    recalibrated_brier,
    recalibration_by_group,
    recalibration_with_ci,
    venue_slope_difference,
)


def _simulate(a_true, b_true, n, seed=0):
    """Draw p ~ U(0.02, 0.98) and y ~ Bernoulli(sigmoid(a + b*logit(p)))."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.02, 0.98, size=n)
    logit_p = np.log(p / (1.0 - p))
    prob = 1.0 / (1.0 + np.exp(-(a_true + b_true * logit_p)))
    y = (rng.uniform(size=n) < prob).astype(float)
    return p, y


def _simulate_two_venues(b_poly, b_kalshi, n_each, seed):
    """Pooled (price, outcome, is_kalshi) with a known slope per venue."""
    pp, yp = _simulate(a_true=0.0, b_true=b_poly, n=n_each, seed=seed)
    pk, yk = _simulate(a_true=0.0, b_true=b_kalshi, n=n_each, seed=seed + 1)
    price = np.concatenate([pp, pk])
    outcome = np.concatenate([yp, yk])
    is_kalshi = np.concatenate([np.zeros(n_each), np.ones(n_each)])
    return price, outcome, is_kalshi


def test_venue_slope_difference_recovers_b3():
    # Polymarket slope 0.8, Kalshi slope 1.05 => true b3 = 0.25.
    price, outcome, k = _simulate_two_venues(0.8, 1.05, n_each=30_000, seed=11)
    res = venue_slope_difference(price, outcome, k, n_iter=200, rng=np.random.default_rng(0))
    assert res["poly_slope"] == pytest.approx(0.8, abs=0.08)
    assert res["kalshi_slope"] == pytest.approx(1.05, abs=0.08)
    assert res["b3"] == pytest.approx(0.25, abs=0.08)
    assert res["b3_ci_lo"] <= res["b3"] <= res["b3_ci_hi"]
    assert res["b3_ci_lo"] > 0.0  # significant difference
    assert res["n_poly"] == 30_000 and res["n_kalshi"] == 30_000


def test_venue_slope_difference_equal_slopes_includes_zero():
    price, outcome, k = _simulate_two_venues(0.9, 0.9, n_each=20_000, seed=21)
    res = venue_slope_difference(price, outcome, k, n_iter=200, rng=np.random.default_rng(0))
    assert res["b3"] == pytest.approx(0.0, abs=0.08)
    assert res["b3_ci_lo"] <= 0.0 <= res["b3_ci_hi"]  # not significant


def test_recovers_known_coefficients():
    p, y = _simulate(a_true=0.3, b_true=0.7, n=40_000, seed=1)
    a, b = fit_logit_recalibration(p, y)
    assert a == pytest.approx(0.3, abs=0.08)
    assert b == pytest.approx(0.7, abs=0.08)
    assert b < 1.0  # FLB signature recovered


def test_perfectly_calibrated_is_identity():
    # y ~ Bernoulli(p) exactly => a ~ 0, b ~ 1.
    p, y = _simulate(a_true=0.0, b_true=1.0, n=40_000, seed=2)
    a, b = fit_logit_recalibration(p, y)
    assert a == pytest.approx(0.0, abs=0.08)
    assert b == pytest.approx(1.0, abs=0.08)


def test_degenerate_all_same_outcome_returns_nan():
    p = np.array([0.2, 0.4, 0.6, 0.8])
    a, b = fit_logit_recalibration(p, np.ones_like(p))
    assert np.isnan(a) and np.isnan(b)


def test_too_few_rows_returns_nan():
    a, b = fit_logit_recalibration(np.array([0.5]), np.array([1.0]))
    assert np.isnan(a) and np.isnan(b)


def test_exact_zero_one_prices_do_not_blow_up():
    # Prices at the clip boundary must stay finite via the eps path.
    p = np.array([0.0, 0.0, 1.0, 1.0, 0.5, 0.5])
    y = np.array([0.0, 1.0, 1.0, 0.0, 1.0, 0.0])
    a, b = fit_logit_recalibration(p, y)
    assert np.isfinite(a) and np.isfinite(b)


def test_apply_recalibration_identity():
    p = np.array([0.1, 0.5, 0.9])
    out = apply_recalibration(p, a=0.0, b=1.0)
    np.testing.assert_allclose(out, p, atol=1e-5)


def test_recalibrated_brier_identity_matches_market():
    p, y = _simulate(a_true=0.0, b_true=1.0, n=2_000, seed=3)
    # identity map => recalibrated Brier equals raw Brier.
    market = float(np.mean((p - y) ** 2))
    assert recalibrated_brier(p, y, 0.0, 1.0) == pytest.approx(market, abs=1e-9)


def test_recalibrated_brier_nan_when_fit_degenerate():
    p = np.array([0.2, 0.8])
    assert np.isnan(recalibrated_brier(p, np.array([1.0, 1.0]), float("nan"), float("nan")))


def test_with_ci_brackets_point_estimate():
    p, y = _simulate(a_true=0.2, b_true=0.6, n=5_000, seed=4)
    rng = np.random.default_rng(42)
    res = recalibration_with_ci(p, y, n_iter=200, rng=rng)
    assert res["b_ci_lo"] <= res["b"] <= res["b_ci_hi"]
    assert res["a_ci_lo"] <= res["a"] <= res["a_ci_hi"]
    assert res["b"] < 1.0
    assert res["n"] == 5_000


def test_with_ci_degenerate_group_has_nan_ci():
    res = recalibration_with_ci(np.array([0.3, 0.7]), np.array([1.0, 1.0]), n_iter=50)
    assert np.isnan(res["b"]) and np.isnan(res["b_ci_lo"])


def test_by_group_one_row_per_subgroup():
    p, y = _simulate(a_true=0.1, b_true=0.8, n=3_000, seed=5)
    df = pd.DataFrame({"predicted": p, "outcome": y, "cat": np.where(p < 0.5, "lo", "hi")})
    out = recalibration_by_group(df, group_col="cat", n_iter=50, rng=np.random.default_rng(0))
    assert set(out["subgroup"]) == {"lo", "hi"}
    assert (out["n"] > 0).all()


def test_by_group_overall_when_no_group_col():
    p, y = _simulate(a_true=0.0, b_true=0.9, n=1_000, seed=6)
    df = pd.DataFrame({"predicted": p, "outcome": y})
    out = recalibration_by_group(df, group_col=None, n_iter=50, rng=np.random.default_rng(0))
    assert len(out) == 1
    assert out.iloc[0]["subgroup"] == "overall"
