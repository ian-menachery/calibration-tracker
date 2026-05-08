"""Calibration curve plotting. Static matplotlib output saved to PNG."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend so CLI runs headless

import matplotlib.pyplot as plt
import pandas as pd


def plot_calibration_curve(
    buckets: pd.DataFrame, title: str, save_to: Path | None = None
) -> Path | None:
    """Scatter mean_predicted vs realized_rate with bootstrap CI whiskers and a
    y=x reference line. Skips empty buckets. If save_to is given, writes the
    PNG and returns its path; otherwise just shows the figure (returns None).
    """
    valid = buckets[buckets["n_markets"] > 0].copy()
    fig, ax = plt.subplots(figsize=(6, 6))
    if not valid.empty:
        yerr_lower = valid["realized_rate"] - valid["ci_lo"]
        yerr_upper = valid["ci_hi"] - valid["realized_rate"]
        ax.errorbar(
            valid["mean_predicted"], valid["realized_rate"],
            yerr=[yerr_lower, yerr_upper],
            fmt="o", capsize=4, color="tab:blue", label="bucket (95% CI)",
        )
    ax.plot([0, 1], [0, 1], "--", color="gray", alpha=0.6, label="perfect calibration")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Realized rate")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_aspect("equal")
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    if save_to is not None:
        save_to.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_to, dpi=120)
        plt.close(fig)
        return save_to
    plt.close(fig)
    return None
