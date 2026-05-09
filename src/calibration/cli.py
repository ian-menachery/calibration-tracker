"""calibration command-line entry point. One subcommand per pipeline stage."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from calibration.analysis.calibration import (
    bucket_5pct,
    bucket_decile,
    compute_metrics,
    load_calibration_frame,
)
from calibration.analysis.snapshots import extract_snapshots
from calibration.polymarket.client import GammaClient
from calibration.polymarket.discovery import discover_markets
from calibration.polymarket.prices import CLOBClient, fetch_market_history
from calibration.polymarket.tags import fetch_event_tags
from calibration.reporting.charts import plot_calibration_curve
from calibration.storage.repository import (
    get_market,
    get_ticks_for_market,
    init_db,
    insert_market_tags,
    insert_price_ticks,
    markets_missing_history,
    markets_missing_tags,
    markets_with_history,
    upsert_markets,
    upsert_snapshots,
)

SNAPSHOT_TYPES = ("close", "1h", "24h", "7d")


def cmd_discover(args: argparse.Namespace) -> int:
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Discovering markets since {since.date()} (volume floor=${args.volume_floor:.0f}) ...")
    with GammaClient() as client:
        markets, stats = discover_markets(client, since=since, volume_floor=args.volume_floor)
    print(f"Fetched {stats.fetched} markets; {stats.kept} kept after filtering ({stats.skipped} skipped).")

    conn = init_db(db_path)
    try:
        upsert_markets(conn, markets)
    finally:
        conn.close()
    print(f"Wrote {stats.kept} markets to {db_path}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    out_dir = Path(args.out)
    figures_dir = out_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    all_buckets: list[pd.DataFrame] = []
    all_metrics: list[pd.DataFrame] = []
    conn = init_db(db_path)
    try:
        for snap in SNAPSHOT_TYPES:
            df = load_calibration_frame(conn, snap)
            if df.empty:
                print(f"[{snap}] no rows; skipping")
                continue
            df["volume_quartile"] = pd.qcut(
                df["volume"], q=4, labels=["q1", "q2", "q3", "q4"], duplicates="drop"
            )
            for label, edges_fn in [("decile", bucket_decile), ("pct5", bucket_5pct)]:
                for weighting, weight_col in [("market", None), ("volume", "volume")]:
                    buckets = edges_fn(df, n_iter=args.bootstrap, rng=rng, weight_col=weight_col)
                    buckets["snapshot_type"] = snap
                    buckets["bucketing"] = label
                    buckets["weighting"] = weighting
                    all_buckets.append(buckets)

            metrics_overall = compute_metrics(df)
            metrics_cat = compute_metrics(df, group_col="category")
            metrics_vol = compute_metrics(df, group_col="volume_quartile")
            for m in (metrics_overall, metrics_cat, metrics_vol):
                m["snapshot_type"] = snap
                all_metrics.append(m)

            decile_market = bucket_decile(df, n_iter=args.bootstrap, rng=rng, weight_col=None)
            chart_path = figures_dir / f"calibration_{snap}.png"
            plot_calibration_curve(
                decile_market,
                title=f"Calibration: T-{snap} (market-weighted, decile)",
                save_to=chart_path,
            )
            br = compute_metrics(df).loc[0]
            print(f"[{snap}] n={int(br['n_markets']):>5,}  "
                  f"brier={br['brier_score']:.4f}  log_loss={br['log_loss']:.4f}  "
                  f"-> {chart_path}")
    finally:
        conn.close()

    if all_buckets:
        pd.concat(all_buckets, ignore_index=True).to_csv(out_dir / "calibration_buckets.csv", index=False)
    if all_metrics:
        pd.concat(all_metrics, ignore_index=True).to_csv(out_dir / "calibration_metrics.csv", index=False)
    print(f"Wrote bucket-level + metrics CSVs to {out_dir}/")
    return 0


def cmd_fetch_tags(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        pairs = markets_missing_tags(conn)
        if args.limit is not None:
            pairs = pairs[: args.limit]

        print(f"Fetching tags for {len(pairs)} markets ...")
        fetched = 0
        skipped = 0
        with GammaClient() as client:
            for i, (mid, evt_id) in enumerate(pairs, 1):
                tags = fetch_event_tags(client, evt_id)
                if not tags:
                    skipped += 1
                else:
                    insert_market_tags(conn, [(mid, t) for t in tags])
                    fetched += 1
                if i % 50 == 0:
                    print(f"  [{i}/{len(pairs)}] {fetched} fetched, {skipped} skipped")
        print(f"Done. Fetched tags for {fetched} markets, skipped {skipped} (HTTP error or no tags).")
    finally:
        conn.close()
    return 0


def cmd_extract_snapshots(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        market_ids = markets_with_history(conn)
        print(f"Extracting snapshots for {len(market_ids)} markets ...")
        total = 0
        for mid in market_ids:
            market = get_market(conn, mid)
            if market is None:
                continue
            ticks = get_ticks_for_market(conn, mid)
            snaps = extract_snapshots(market, ticks)
            if snaps:
                upsert_snapshots(conn, snaps)
                total += len(snaps)
        print(f"Wrote {total} snapshots to {db_path}.")
    finally:
        conn.close()
    return 0


def cmd_fetch_prices(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        if args.all:
            market_ids = [r[0] for r in conn.execute("SELECT market_id FROM markets").fetchall()]
        else:
            market_ids = markets_missing_history(conn)
        if args.limit is not None:
            market_ids = market_ids[: args.limit]

        print(f"Fetching prices for {len(market_ids)} markets ...")
        fetched = 0
        skipped = 0
        with CLOBClient() as client:
            for i, mid in enumerate(market_ids, 1):
                market = get_market(conn, mid)
                if market is None:
                    skipped += 1
                    continue
                ticks = fetch_market_history(client, market)
                if ticks is None:
                    print(f"  [{i}/{len(market_ids)}] skip {market.slug[:60]}: error or no data")
                    skipped += 1
                    continue
                insert_price_ticks(conn, ticks)
                fetched += 1
                if i % 50 == 0:
                    print(f"  [{i}/{len(market_ids)}] {fetched} fetched, {skipped} skipped")
        print(f"Done. Fetched {fetched} markets, skipped {skipped}.")
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibration")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover", help="Stage 1: fetch resolved binary markets from Gamma")
    p_discover.add_argument("--since", required=True, help="ISO date, e.g. 2024-01-01")
    p_discover.add_argument("--volume-floor", type=float, default=1_000_000.0)
    p_discover.add_argument("--db", default="data/markets.db")
    p_discover.set_defaults(func=cmd_discover)

    p_fetch = sub.add_parser("fetch-prices", help="Stage 2: fetch CLOB price history per market")
    p_fetch.add_argument("--db", default="data/markets.db")
    p_fetch.add_argument("--limit", type=int, default=None, help="cap markets per run")
    p_fetch.add_argument("--all", action="store_true", help="re-fetch even markets that already have ticks")
    p_fetch.set_defaults(func=cmd_fetch_prices)

    p_tags = sub.add_parser("fetch-tags", help="v1.1: fetch category tags per market via Gamma /events/{id}")
    p_tags.add_argument("--db", default="data/markets.db")
    p_tags.add_argument("--limit", type=int, default=None, help="cap markets per run")
    p_tags.set_defaults(func=cmd_fetch_tags)

    p_snap = sub.add_parser("extract-snapshots", help="Stage 3: extract calibration snapshots into price_snapshots")
    p_snap.add_argument("--db", default="data/markets.db")
    p_snap.set_defaults(func=cmd_extract_snapshots)

    p_an = sub.add_parser("analyze", help="Stage 4: bucket markets, compute Brier/log loss, save calibration charts")
    p_an.add_argument("--db", default="data/markets.db")
    p_an.add_argument("--out", default="reports", help="output directory for CSVs and figures/")
    p_an.add_argument("--bootstrap", type=int, default=1000, help="bootstrap iterations for per-bucket CIs")
    p_an.add_argument("--seed", type=int, default=42, help="rng seed for reproducible bootstrap CIs")
    p_an.set_defaults(func=cmd_analyze)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
