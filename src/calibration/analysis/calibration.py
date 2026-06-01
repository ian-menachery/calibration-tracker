"""Stage 4: bucket markets by predicted probability and compute realized rates.

Pure pandas/numpy on data already in SQLite. Categorization uses a slug-prefix
heuristic — see notes/NOTES.md for the v2 plan to replace this with proper Gamma
`events` tags.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Sequence

import numpy as np
import pandas as pd

from calibration.analysis.metrics import bootstrap_ci, brier_score, log_loss
from calibration.storage.repository import get_tags_for_markets, select_snapshot_join

# Tag-based categorizer (v1.1). Iterate this list in order; first bucket
# whose tag-slug set intersects the market's tags wins. Order matters —
# geopolitics is checked before politics so a market tagged both "iran"
# and "trump" lands in geopolitics. Sports comes first because most game
# markets have generic "politics"/"world"/"trump" tags too via meta-events,
# but a sport-specific tag (nba/nfl/etc) reliably means sports. Long tail
# falls through to slug-heuristic fallback.
_CATEGORY_MAPPING: list[tuple[str, frozenset[str]]] = [
    ("sports", frozenset({
        "sports", "games", "nba", "basketball", "nfl", "football", "nhl",
        "hockey", "mlb", "baseball", "soccer", "tennis", "golf", "ufc",
        "boxing", "f1", "formula-1", "esports", "league-of-legends",
        "counter-strike", "dota", "valorant", "olympics", "world-cup",
        "champions-league", "premier-league", "epl", "la-liga",
        "wimbledon", "us-open", "atp", "wta", "cricket", "ipl", "fifa",
    })),
    ("crypto", frozenset({
        "crypto", "crypto-prices", "bitcoin", "ethereum", "solana",
        "cardano", "xrp", "doge", "memecoin", "stablecoin", "defi",
        "altcoin", "btc", "eth", "sol", "ada",
    })),
    ("geopolitics", frozenset({
        "geopolitics", "iran", "israel", "middle-east", "russia",
        "ukraine", "putin", "zelenskyy", "china", "nato", "north-korea",
        "korea", "taiwan", "saudi-arabia", "venezuela", "war", "invasion",
        "ceasefire", "diplomacy-ceasefire", "military-strikes", "nuclear",
        "hostage", "hamas", "hezbollah", "netanyahu", "khamenei",
    })),
    ("politics", frozenset({
        "politics", "trump", "biden", "harris", "kamala", "desantis",
        "election", "elections", "us-election", "2024-election",
        "presidential-election", "primary", "gop", "democrats",
        "democratic", "republican", "republicans", "congress", "senate",
        "house-of-representatives", "supreme-court", "scotus", "scotus-2024",
        "newsom", "sanders", "pelosi", "vance", "vp", "cabinet",
        "gov-shutdown", "impeachment",
    })),
    ("entertainment", frozenset({
        "entertainment", "celebrities", "movies", "music", "oscars",
        "grammys", "emmys", "netflix", "disney", "spotify", "tiktok",
        "taylor-swift", "drake", "kanye", "kardashian", "youtube",
        "streaming", "box-office", "met-gala", "cannes", "halftime",
    })),
]


def categorize_tags(tags: list[str]) -> str | None:
    """Map a list of Polymarket tag slugs to one of our 6 buckets.

    Returns None if no tag matches any bucket — caller should fall through
    to the slug heuristic for those markets.
    """
    tag_set = set(tags)
    for category, slugs in _CATEGORY_MAPPING:
        if tag_set & slugs:
            return category
    return None


# --- legacy slug heuristic (v1) — kept as fallback for markets whose tags
# don't intersect any _CATEGORY_MAPPING bucket ---

# Slug-prefix heuristic. Order matters — first match wins, so geopolitics
# beats politics for the iran/ukraine cases that mention people's names.
_CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("sports", re.compile(
        r"\b(nba|nfl|nhl|mlb|nascar|soccer|tennis|wimbledon|usopen|atp|wta|"
        r"cricipl|cricket|lol|csgo|dota|epl|laliga|f1|ufc|boxing|olympics|"
        r"superbowl|stanley|worldcup|championship|playoff|champions-league)",
        re.I,
    )),
    ("crypto", re.compile(
        r"\b(bitcoin|btc|ethereum|eth-|crypto|solana|sol-|defi|cardano|"
        r"ada-|xrp|usdc|usdt|memecoin|pepe|doge|stablecoin|altcoin)",
        re.I,
    )),
    ("geopolitics", re.compile(
        r"\b(russia|ukraine|putin|zelenskyy|israel|iran|gaza|hamas|hezbollah|"
        r"netanyahu|china|nato|kim-jong|north-korea|taiwan|saudi|venezuela|"
        r"nuclear|war|ceasefire|sanctions|invasion|wmd|missile|hostage)",
        re.I,
    )),
    ("politics", re.compile(
        r"\b(trump|biden|harris|kamala|desantis|election|senator|governor|"
        r"congress|senate|house-of|impeach|nominee|primary|gop|democrat|"
        r"republican|pelosi|newsom|sanders|cabinet|supreme-court|scotus|"
        r"vp|presidential|inauguration|debate)",
        re.I,
    )),
    ("entertainment", re.compile(
        r"\b(oscar|grammy|emmy|movie|netflix|disney|spotify|tiktok|swift|"
        r"kardashian|drake|kanye|streaming|youtube|album|box-office|"
        r"super-bowl-halftime|met-gala|cannes)",
        re.I,
    )),
]


def categorize_slug(slug: str | None) -> str:
    """Bucket a market slug into a coarse category. Returns 'other' if no match.

    Heuristic — see notes/NOTES.md "Replace slug-heuristic categorization" for the
    v2 plan to replace this with Gamma `events` tags.
    """
    if not slug:
        return "other"
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(slug):
            return category
    return "other"


def categorize_market(slug: str | None, tags: list[str]) -> str:
    """v1.1 categorizer: try Gamma tags first, fall back to slug heuristic."""
    if tags:
        cat = categorize_tags(tags)
        if cat is not None:
            return cat
    return categorize_slug(slug)


def load_calibration_frame(
    conn: sqlite3.Connection, snapshot_type: str
) -> pd.DataFrame:
    """Pull markets x price_snapshots into a DataFrame for analysis.

    Categorization (v1.1): each market's category is derived from its
    Gamma tags via `_CATEGORY_MAPPING`; if none of the market's tags
    match a known bucket, falls back to the v1 slug heuristic.
    """
    rows = select_snapshot_join(conn, snapshot_type)
    df = pd.DataFrame(
        rows,
        columns=["market_id", "slug", "predicted", "outcome", "volume", "end_date"],
    )
    if df.empty:
        df["category"] = pd.Series(dtype=str)
        return df
    tags_by_market = get_tags_for_markets(conn, df["market_id"].tolist())
    df["category"] = df.apply(
        lambda row: categorize_market(row["slug"], tags_by_market.get(row["market_id"], [])),
        axis=1,
    )
    return df


def _empty_buckets_frame(edges: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({
        "bucket_lo": edges[:-1],
        "bucket_hi": edges[1:],
        "n_markets": 0,
        "mean_predicted": np.nan,
        "realized_rate": np.nan,
        "ci_lo": np.nan,
        "ci_hi": np.nan,
    })


def bucket(
    df: pd.DataFrame,
    edges: Sequence[float],
    weight_col: str | None = None,
    n_iter: int = 1000,
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    """Bucket df by `predicted` price. Returns one row per bucket with realized
    rate, mean predicted, and bootstrap CI.

    Bucket convention: [lo, hi) — left-closed, right-open. Predicted == 1.0
    is folded into the last bucket so we don't lose it.

    weight_col=None gives market-weighted realized rate (mean of outcomes).
    weight_col='volume' (or any column) gives a weighted mean using that column.
    """
    edges_arr = np.asarray(edges, dtype=float)
    if len(df) == 0:
        return _empty_buckets_frame(edges_arr)

    df = df.copy()
    # right=False means [lo, hi); include_lowest captures predicted == edges[0].
    df["bucket_idx"] = pd.cut(
        df["predicted"], bins=edges_arr, labels=False,
        include_lowest=True, right=False,
    )
    # Predicted exactly at the top edge (1.0) lands in NaN with right=False; fold in.
    last_bucket = len(edges_arr) - 2
    top_edge = edges_arr[-1]
    df.loc[df["predicted"] == top_edge, "bucket_idx"] = last_bucket

    out = _empty_buckets_frame(edges_arr)
    for idx, group in df.groupby("bucket_idx", sort=True):
        idx = int(idx)
        outcomes = group["outcome"].to_numpy()
        if weight_col is None:
            realized = float(outcomes.mean())
            if len(outcomes) >= 2:
                lo, hi = bootstrap_ci(outcomes, np.mean, n_iter=n_iter, rng=rng)
            else:
                lo, hi = realized, realized
        else:
            weights = group[weight_col].to_numpy()
            realized = float(np.average(outcomes, weights=weights))
            pairs = np.column_stack([outcomes, weights])
            if len(outcomes) >= 2:
                def wmean(rows: np.ndarray) -> float:
                    return float(np.average(rows[:, 0], weights=rows[:, 1]))
                lo, hi = bootstrap_ci(pairs, wmean, n_iter=n_iter, rng=rng)
            else:
                lo, hi = realized, realized
        out.loc[idx, "n_markets"] = len(outcomes)
        out.loc[idx, "mean_predicted"] = float(group["predicted"].mean())
        out.loc[idx, "realized_rate"] = realized
        out.loc[idx, "ci_lo"] = lo
        out.loc[idx, "ci_hi"] = hi
    return out


def bucket_decile(df, n_iter=1000, rng=None, weight_col=None):
    return bucket(df, np.arange(0.0, 1.01, 0.1), weight_col=weight_col, n_iter=n_iter, rng=rng)


def bucket_5pct(df, n_iter=1000, rng=None, weight_col=None):
    return bucket(df, np.arange(0.0, 1.01, 0.05), weight_col=weight_col, n_iter=n_iter, rng=rng)


def compute_metrics(df: pd.DataFrame, group_col: str | None = None) -> pd.DataFrame:
    """Brier + log loss overall, or grouped by `group_col` (e.g. 'category')."""
    if group_col is None:
        return pd.DataFrame([{
            "subgroup": "overall",
            "n_markets": len(df),
            "brier_score": brier_score(df["predicted"], df["outcome"]) if len(df) else float("nan"),
            "log_loss": log_loss(df["predicted"], df["outcome"]) if len(df) else float("nan"),
        }])
    rows = []
    for value, group in df.groupby(group_col, observed=True):
        rows.append({
            "subgroup": f"{group_col}={value}",
            "n_markets": len(group),
            "brier_score": brier_score(group["predicted"], group["outcome"]),
            "log_loss": log_loss(group["predicted"], group["outcome"]),
        })
    return pd.DataFrame(rows)
