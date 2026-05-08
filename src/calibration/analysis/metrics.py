"""Calibration metrics: Brier score, log loss, bootstrap confidence intervals.

Pure math. All functions take numpy arrays / sequences and return floats or
tuples. Per CLAUDE.md every function in this module must have a known-input
test in tests/test_metrics.py.
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np


def brier_score(
    predictions: Sequence[float] | np.ndarray,
    outcomes: Sequence[float] | np.ndarray,
) -> float:
    """Mean squared error of probability predictions vs binary outcomes.

    Range [0, 1]. 0 = perfect calibration; 0.25 = always predicting 0.5
    (chance); 1 = maximally wrong (always predicted opposite of outcome).
    """
    p = np.asarray(predictions, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    return float(np.mean((p - y) ** 2))


def log_loss(
    predictions: Sequence[float] | np.ndarray,
    outcomes: Sequence[float] | np.ndarray,
    eps: float = 1e-15,
) -> float:
    """Binary cross-entropy. Predictions are clipped to [eps, 1-eps] so 0/1
    inputs don't produce -inf when outcomes disagree.
    """
    p = np.clip(np.asarray(predictions, dtype=float), eps, 1.0 - eps)
    y = np.asarray(outcomes, dtype=float)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def bootstrap_ci(
    values: Sequence | np.ndarray,
    statistic: Callable[[np.ndarray], float],
    n_iter: int = 1000,
    alpha: float = 0.05,
    rng: np.random.Generator | None = None,
) -> tuple[float, float]:
    """Non-parametric bootstrap CI. Resamples row indices of `values` with
    replacement `n_iter` times, applies `statistic` to each resample, returns
    (alpha/2, 1-alpha/2) quantiles.

    `values` may be 1D (e.g. outcomes) or 2D (e.g. (outcome, weight) pairs);
    the integer-index resampling preserves row alignment in the 2D case.
    Pass an `rng` for deterministic results.
    """
    if rng is None:
        rng = np.random.default_rng()
    arr = np.asarray(values)
    n = len(arr)
    samples = np.empty(n_iter, dtype=float)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        samples[i] = statistic(arr[idx])
    return (
        float(np.quantile(samples, alpha / 2)),
        float(np.quantile(samples, 1.0 - alpha / 2)),
    )
