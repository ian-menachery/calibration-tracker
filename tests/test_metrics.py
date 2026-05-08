import numpy as np
import pytest

from calibration.analysis.metrics import bootstrap_ci, brier_score, log_loss


# ---------- brier_score ----------

def test_brier_score_perfect_predictions():
    assert brier_score([1.0, 0.0], [1, 0]) == 0.0


def test_brier_score_maximally_wrong():
    assert brier_score([0.0, 1.0], [1, 0]) == 1.0


def test_brier_score_chance_is_quarter():
    # Always predict 0.5 against any binary outcomes -> 0.25.
    assert brier_score([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.25


def test_brier_score_known_value():
    # Each squared error: (0.7-1)^2 = 0.09, (0.3-0)^2 = 0.09. Mean = 0.09.
    assert brier_score([0.7, 0.3], [1, 0]) == pytest.approx(0.09)


def test_brier_score_accepts_numpy_arrays():
    p = np.array([0.2, 0.8])
    y = np.array([0, 1])
    assert brier_score(p, y) == pytest.approx(0.04)


# ---------- log_loss ----------

def test_log_loss_at_half_with_yes():
    # -ln(0.5) = ln(2) ~= 0.693
    assert log_loss([0.5], [1]) == pytest.approx(np.log(2))


def test_log_loss_perfect_prediction_clamped_finite():
    # p=1, y=1 with eps clamp: -ln(1-eps) ~= eps. Should be very small but finite.
    result = log_loss([1.0], [1])
    assert np.isfinite(result)
    assert result < 1e-10


def test_log_loss_zero_prediction_yes_outcome_does_not_diverge():
    # p=0, y=1 would naively give -ln(0) = inf. Clamp prevents that.
    result = log_loss([0.0], [1])
    assert np.isfinite(result)


def test_log_loss_symmetric_for_swapped_classes():
    a = log_loss([0.3, 0.7], [0, 1])
    b = log_loss([0.7, 0.3], [1, 0])
    assert a == pytest.approx(b)


# ---------- bootstrap_ci ----------

def test_bootstrap_ci_deterministic_with_seeded_rng():
    values = np.array([0.0, 0.1, 0.5, 0.9, 1.0])
    a = bootstrap_ci(values, np.mean, n_iter=200, rng=np.random.default_rng(42))
    b = bootstrap_ci(values, np.mean, n_iter=200, rng=np.random.default_rng(42))
    assert a == b


def test_bootstrap_ci_low_lt_high():
    rng = np.random.default_rng(7)
    values = np.array([0.1, 0.2, 0.5, 0.8, 0.9])
    lo, hi = bootstrap_ci(values, np.mean, n_iter=200, rng=rng)
    assert lo < hi


def test_bootstrap_ci_brackets_point_estimate_for_large_sample():
    # With n=500 uniform samples, the 95% CI of the mean should contain
    # the actual sample mean.
    sample = np.random.default_rng(0).uniform(0, 1, size=500)
    point = float(np.mean(sample))
    lo, hi = bootstrap_ci(sample, np.mean, n_iter=500, rng=np.random.default_rng(1))
    assert lo <= point <= hi


def test_bootstrap_ci_works_on_2d_pairs():
    # Resample (outcome, weight) pairs and compute weighted mean.
    pairs = np.array([[0.0, 1.0], [1.0, 1.0], [0.0, 2.0], [1.0, 2.0]])
    def weighted_mean(rows: np.ndarray) -> float:
        return float(np.average(rows[:, 0], weights=rows[:, 1]))
    rng = np.random.default_rng(123)
    lo, hi = bootstrap_ci(pairs, weighted_mean, n_iter=200, rng=rng)
    assert 0.0 <= lo <= hi <= 1.0
