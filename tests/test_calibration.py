from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from calibration.analysis.calibration import (
    bucket,
    bucket_5pct,
    bucket_decile,
    categorize_slug,
    compute_metrics,
    load_calibration_frame,
)
from calibration.storage.repository import (
    Market,
    Snapshot,
    init_db,
    upsert_markets,
    upsert_snapshots,
)


# ---------- categorize_slug ----------

@pytest.mark.parametrize("slug,expected", [
    ("nba-bos-phi-2026-04-24", "sports"),
    ("mlb-tb-tor-2025-09-26", "sports"),
    ("lol-blg-jdg-2026-01-26", "sports"),
    ("wimbledon-cobolli-vs-djokovic", "sports"),
    ("will-ethereum-dip-to-3300-in-august", "crypto"),
    ("btc-price-dec-2024", "crypto"),
    ("will-trump-win-iowa", "politics"),
    ("will-newsom-appoint-a-black-woman", "politics"),
    ("us-x-iran-ceasefire-by-april-7", "geopolitics"),
    ("israeli-forces-enters-lebanon-in-september", "geopolitics"),
    ("will-zelenskyy-wear-a-suit-before-july", "geopolitics"),
    ("oscar-best-picture-2025", "entertainment"),
    ("some-niche-prediction-no-one-cares-about", "other"),
    ("", "other"),
    (None, "other"),
])
def test_categorize_slug(slug, expected):
    assert categorize_slug(slug) == expected


# ---------- bucket() ----------

def _frame(predicted, outcome, volume=None):
    return pd.DataFrame({
        "predicted": predicted,
        "outcome": outcome,
        "volume": volume if volume is not None else [1.0] * len(predicted),
    })


def test_bucket_empty_frame_returns_one_row_per_bucket_with_zero_counts():
    out = bucket(_frame([], []), edges=[0.0, 0.5, 1.0])
    assert len(out) == 2
    assert (out["n_markets"] == 0).all()
    assert out["realized_rate"].isna().all()


def test_bucket_assigns_predicted_to_left_closed_right_open_buckets():
    df = _frame([0.0, 0.05, 0.1, 0.5, 0.99, 1.0], [1, 0, 1, 0, 1, 0])
    out = bucket(df, edges=[0.0, 0.1, 1.0], rng=np.random.default_rng(0))
    assert out.loc[0, "n_markets"] == 2
    assert out.loc[1, "n_markets"] == 4


def test_bucket_predicted_exactly_at_one_lands_in_last_bucket():
    df = _frame([1.0], [1])
    out = bucket(df, edges=[0.0, 0.5, 1.0], rng=np.random.default_rng(0))
    assert out.loc[1, "n_markets"] == 1
    assert out.loc[0, "n_markets"] == 0


def test_bucket_realized_rate_equals_mean_outcome_in_single_bucket_cohort():
    df = _frame([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0])
    out = bucket(df, edges=[0.0, 1.0], rng=np.random.default_rng(0))
    assert out.loc[0, "realized_rate"] == 0.5
    assert out.loc[0, "n_markets"] == 4


def test_bucket_decile_produces_ten_buckets():
    df = _frame(np.linspace(0.05, 0.95, 100), [1] * 100)
    out = bucket_decile(df, n_iter=50, rng=np.random.default_rng(0))
    assert len(out) == 10


def test_bucket_5pct_produces_twenty_buckets():
    df = _frame(np.linspace(0.025, 0.975, 100), [1] * 100)
    out = bucket_5pct(df, n_iter=50, rng=np.random.default_rng(0))
    assert len(out) == 20


def test_volume_weighted_differs_from_market_weighted_on_uneven_volumes():
    # Two markets in one bucket: outcome 1 with volume 99, outcome 0 with volume 1.
    # Market-weighted rate = 0.5; volume-weighted = 0.99.
    df = _frame([0.5, 0.5], [1, 0], volume=[99.0, 1.0])
    market = bucket(df, edges=[0.0, 1.0], rng=np.random.default_rng(0))
    weighted = bucket(df, edges=[0.0, 1.0], weight_col="volume", rng=np.random.default_rng(0))
    assert market.loc[0, "realized_rate"] == 0.5
    assert weighted.loc[0, "realized_rate"] == pytest.approx(0.99)


def test_bucket_ci_lo_le_realized_le_ci_hi():
    df = _frame([0.5] * 50, [1, 0] * 25)
    out = bucket(df, edges=[0.0, 1.0], n_iter=200, rng=np.random.default_rng(42))
    row = out.loc[0]
    assert row["ci_lo"] <= row["realized_rate"] <= row["ci_hi"]


# ---------- load_calibration_frame ----------

def test_load_calibration_frame_roundtrip():
    conn = init_db(":memory:")
    try:
        m = Market(
            market_id="0xa",
            slug="nba-bos-phi-2026-04-24",
            question="?",
            category=None,
            market_type="binary",
            parent_event_id=None,
            end_date=datetime(2026, 4, 25, tzinfo=timezone.utc),
            resolved_outcome="YES",
            resolved_value=1.0,
            total_volume_usd=5_000_000.0,
            fetched_at=datetime(2026, 5, 8, tzinfo=timezone.utc),
            yes_token_id="tok",
        )
        upsert_markets(conn, [m])
        upsert_snapshots(conn, [
            Snapshot(market_id="0xa", snapshot_type="1h", price=0.88,
                     observed_at=datetime(2026, 4, 25, 1, tzinfo=timezone.utc)),
        ])
        df = load_calibration_frame(conn, "1h")
        assert len(df) == 1
        assert df.loc[0, "predicted"] == 0.88
        assert df.loc[0, "outcome"] == 1.0
        assert df.loc[0, "category"] == "sports"
    finally:
        conn.close()


# ---------- compute_metrics ----------

def test_compute_metrics_overall():
    df = _frame([0.7, 0.3], [1, 0])
    out = compute_metrics(df)
    assert len(out) == 1
    assert out.loc[0, "subgroup"] == "overall"
    assert out.loc[0, "n_markets"] == 2
    assert out.loc[0, "brier_score"] == pytest.approx(0.09)


def test_compute_metrics_grouped_returns_one_row_per_group():
    df = pd.DataFrame({
        "predicted": [0.7, 0.3, 0.5, 0.5],
        "outcome": [1, 0, 1, 0],
        "category": ["sports", "sports", "politics", "politics"],
    })
    out = compute_metrics(df, group_col="category")
    assert set(out["subgroup"]) == {"category=sports", "category=politics"}
    assert (out["n_markets"] == 2).all()


def test_load_calibration_frame_filters_to_requested_snapshot_type():
    conn = init_db(":memory:")
    try:
        m = Market(
            market_id="0xa", slug="x", question="?", category=None,
            market_type="binary", parent_event_id=None,
            end_date=datetime(2026, 4, 25, tzinfo=timezone.utc),
            resolved_outcome="YES", resolved_value=1.0, total_volume_usd=1e6,
            fetched_at=datetime(2026, 5, 8, tzinfo=timezone.utc),
            yes_token_id="tok",
        )
        upsert_markets(conn, [m])
        obs = datetime(2026, 4, 25, 1, tzinfo=timezone.utc)
        upsert_snapshots(conn, [
            Snapshot(market_id="0xa", snapshot_type="1h", price=0.9, observed_at=obs),
            Snapshot(market_id="0xa", snapshot_type="7d", price=0.5, observed_at=obs),
        ])
        df_1h = load_calibration_frame(conn, "1h")
        df_7d = load_calibration_frame(conn, "7d")
        assert len(df_1h) == 1
        assert len(df_7d) == 1
        assert df_1h.loc[0, "predicted"] == 0.9
        assert df_7d.loc[0, "predicted"] == 0.5
    finally:
        conn.close()
