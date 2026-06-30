"""FLB recalibration: fit logit(q) = a + b*logit(p) and report b.

The favorite-longshot bias (FLB) shows up as ``b < 1``: the realized-outcome
curve is flatter than the 45-degree line, so longshots resolve YES less often
than their price implies and favorites resolve YES more often. ``a == 0, b == 1``
is perfect calibration.

Pure numpy/pandas, no sklearn/scipy. The fit is a plain binomial-logit IRLS
(Newton's method on the log-likelihood). Per CLAUDE.md every math function here
has a known-input test in tests/test_recalibration.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from calibration.analysis.metrics import brier_score

_EPS = 1e-6
_NAN = float("nan")


def _logit(p: np.ndarray, eps: float = _EPS) -> np.ndarray:
    """log-odds of p, clipped to [eps, 1-eps] (mirrors log_loss's eps handling
    in metrics.py) so snapshot prices of exactly 0.0/1.0 don't blow up."""
    q = np.clip(np.asarray(p, dtype=float), eps, 1.0 - eps)
    return np.log(q / (1.0 - q))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(np.asarray(z, dtype=float), -709.0, 709.0)  # guard exp overflow
    return 1.0 / (1.0 + np.exp(-z))


# Coefficient magnitude beyond which the fit is treated as separated/degenerate.
# logit coefficients past this make sigmoid saturate (prob ~ 0 or 1); no finite
# MLE exists. Real recalibration b lands near [0.5, 1.5], so this never trips a
# genuine fit — it only catches saturated horizons (e.g. T-close) and lets them
# bail to nan fast instead of grinding all max_iter on every bootstrap resample.
_SEPARATION_GUARD = 30.0


def _fit_irls(
    design: np.ndarray,
    y: np.ndarray,
    eps: float = _EPS,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> np.ndarray | None:
    """Binomial-logit IRLS (Newton) for an arbitrary design matrix. Returns the
    coefficient vector, or None for a degenerate fit: <2 rows, all outcomes
    identical, a singular step, or coefficients diverging past the separation
    guard (no finite MLE — the saturated case)."""
    y = np.asarray(y, dtype=float)
    if len(y) < 2 or np.unique(y).size < 2:
        return None
    beta = np.zeros(design.shape[1])
    for _ in range(max_iter):
        mu = _sigmoid(design @ beta)
        w = np.clip(mu * (1.0 - mu), eps, None)  # IRLS variance weights
        hessian = design.T @ (w[:, None] * design)
        grad = design.T @ (y - mu)
        try:
            step = np.linalg.solve(hessian, grad)
        except np.linalg.LinAlgError:
            return None
        beta = beta + step
        if not np.all(np.isfinite(beta)) or np.max(np.abs(beta)) > _SEPARATION_GUARD:
            return None  # diverging -> separated, no finite MLE
        if np.max(np.abs(step)) < tol:
            break
    return beta


def fit_logit_recalibration(
    predicted,
    outcome,
    eps: float = _EPS,
    max_iter: int = 50,
    tol: float = 1e-8,
) -> tuple[float, float]:
    """Fit logit(q) = a + b*logit(p) by IRLS. Returns (a, b), or (nan, nan) for a
    degenerate fit (see _fit_irls)."""
    x = _logit(predicted, eps)
    design = np.column_stack([np.ones_like(x), x])  # columns: [1, logit(p)]
    beta = _fit_irls(design, outcome, eps=eps, max_iter=max_iter, tol=tol)
    if beta is None:
        return (_NAN, _NAN)
    return (float(beta[0]), float(beta[1]))


def apply_recalibration(predicted, a: float, b: float, eps: float = _EPS) -> np.ndarray:
    """Map raw price p to recalibrated probability q-hat = sigmoid(a + b*logit(p))."""
    return _sigmoid(a + b * _logit(predicted, eps))


def recalibrated_brier(predicted, outcome, a: float, b: float) -> float:
    """Brier of the recalibrated probabilities. If the map improves on the raw
    market Brier, the *recalibrated* market becomes the benchmark a model must beat."""
    if not (np.isfinite(a) and np.isfinite(b)):
        return _NAN
    return brier_score(apply_recalibration(predicted, a, b), outcome)


def recalibration_with_ci(
    predicted,
    outcome,
    n_iter: int = 1000,
    rng: np.random.Generator | None = None,
    alpha: float = 0.05,
) -> dict:
    """Point estimate of (a, b) plus bootstrap CIs and the market/recalibrated Brier.

    Paired bootstrap: each resample refits once and yields both a and b, so the
    two CIs share resamples (and it's half the IRLS fits of a per-coefficient
    bootstrap). nanquantile tolerates the rare degenerate resample.
    """
    p = np.asarray(predicted, dtype=float)
    y = np.asarray(outcome, dtype=float)
    a, b = fit_logit_recalibration(p, y)
    out = {
        "n": int(len(y)),
        "a": a,
        "b": b,
        "a_ci_lo": _NAN,
        "a_ci_hi": _NAN,
        "b_ci_lo": _NAN,
        "b_ci_hi": _NAN,
        "brier_market": brier_score(p, y) if len(y) else _NAN,
        "brier_recal": recalibrated_brier(p, y, a, b),
    }
    if len(y) >= 2 and np.isfinite(b):
        if rng is None:
            rng = np.random.default_rng()
        n = len(y)
        a_s = np.empty(n_iter)
        b_s = np.empty(n_iter)
        for i in range(n_iter):
            idx = rng.integers(0, n, size=n)
            a_s[i], b_s[i] = fit_logit_recalibration(p[idx], y[idx])
        out["a_ci_lo"], out["a_ci_hi"] = np.nanquantile(a_s, [alpha / 2, 1.0 - alpha / 2])
        out["b_ci_lo"], out["b_ci_hi"] = np.nanquantile(b_s, [alpha / 2, 1.0 - alpha / 2])
    return out


def predict_band(
    predicted,
    outcome,
    p_grid,
    n_iter: int = 1000,
    rng: np.random.Generator | None = None,
    alpha: float = 0.05,
) -> dict:
    """Recalibrated probability q-hat = sigmoid(a+b*logit(p)) on a price grid, with a
    bootstrap band. Returns {p, q_lo, q_hat, q_hi} (arrays aligned to p_grid).

    q_hat is the full-sample point estimate; q_lo/q_hi are the (alpha/2, 1-alpha/2)
    quantiles of the recalibrated prob across bootstrap refits. The band feeds
    conservative Kelly sizing: size a YES off q_lo and a NO off q_hi (the bound that
    shrinks the edge). Returns nan bands for a degenerate fit.
    """
    p = np.asarray(predicted, dtype=float)
    y = np.asarray(outcome, dtype=float)
    grid = np.asarray(p_grid, dtype=float)
    a, b = fit_logit_recalibration(p, y)
    point = apply_recalibration(grid, a, b) if np.isfinite(b) else np.full_like(grid, _NAN)
    nan = np.full_like(grid, _NAN)
    if len(y) < 2 or not np.isfinite(b):
        return {"p": grid, "q_lo": nan, "q_hat": point, "q_hi": nan}
    if rng is None:
        rng = np.random.default_rng()
    n = len(y)
    samples = np.empty((n_iter, len(grid)))
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        ai, bi = fit_logit_recalibration(p[idx], y[idx])
        samples[i] = apply_recalibration(grid, ai, bi)  # nan row if a resample degenerates
    return {
        "p": grid,
        "q_lo": np.nanquantile(samples, alpha / 2, axis=0),
        "q_hat": point,
        "q_hi": np.nanquantile(samples, 1.0 - alpha / 2, axis=0),
    }


def recalibration_by_group(
    df: pd.DataFrame,
    group_col: str | None = None,
    n_iter: int = 1000,
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    """Fit recalibration overall (group_col=None) or once per value of group_col.

    Expects df with 'predicted' and 'outcome' columns (the shape returned by
    load_calibration_frame). Returns one row per subgroup.
    """
    if group_col is None:
        groups: list[tuple[str, pd.DataFrame]] = [("overall", df)]
    else:
        groups = [(str(v), g) for v, g in df.groupby(group_col, observed=True)]
    rows = []
    for label, g in groups:
        res = recalibration_with_ci(
            g["predicted"].to_numpy(), g["outcome"].to_numpy(), n_iter=n_iter, rng=rng
        )
        rows.append({"subgroup": label, **res})
    return pd.DataFrame(rows)


def _interaction_b3(price: np.ndarray, outcome: np.ndarray, k: np.ndarray, eps: float = _EPS):
    """Fit logit(P) = b0 + b1*logit(p) + b2*k + b3*(k*logit(p)). Returns (b1, b3) or None.
    b1 is the reference-venue slope; b1+b3 the other venue's slope; b3 the difference."""
    x = _logit(price, eps)
    design = np.column_stack([np.ones_like(x), x, k, k * x])  # [1, logit(p), kalshi, kalshi*logit(p)]
    beta = _fit_irls(design, outcome, eps=eps)
    if beta is None:
        return None
    return (float(beta[1]), float(beta[3]))


def venue_slope_difference(
    price,
    outcome,
    is_kalshi,
    n_iter: int = 1000,
    rng: np.random.Generator | None = None,
    alpha: float = 0.05,
) -> dict:
    """Pooled two-venue interaction test of the FLB slope difference.

    Fits one logistic calibration in logit space over rows from both venues with a
    kalshi 0/1 indicator and its interaction with logit(price). Reports b3 (the
    Kalshi-minus-Polymarket slope difference) with a bootstrap CI by resampling the
    pooled rows and refitting. b3 CI excluding 0 => the slopes differ significantly.
    """
    p = np.asarray(price, dtype=float)
    y = np.asarray(outcome, dtype=float)
    k = np.asarray(is_kalshi, dtype=float)
    fit = _interaction_b3(p, y, k)
    out = {
        "n": int(len(y)),
        "n_poly": int(np.sum(k == 0)),
        "n_kalshi": int(np.sum(k == 1)),
        "poly_slope": _NAN,
        "kalshi_slope": _NAN,
        "b3": _NAN,
        "b3_ci_lo": _NAN,
        "b3_ci_hi": _NAN,
    }
    if fit is None:
        return out
    b1, b3 = fit
    out["poly_slope"] = b1
    out["kalshi_slope"] = b1 + b3
    out["b3"] = b3
    if rng is None:
        rng = np.random.default_rng()
    n = len(y)
    samples = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        r = _interaction_b3(p[idx], y[idx], k[idx])
        samples[i] = r[1] if r is not None else _NAN
    out["b3_ci_lo"] = float(np.nanquantile(samples, alpha / 2))
    out["b3_ci_hi"] = float(np.nanquantile(samples, 1.0 - alpha / 2))
    return out
