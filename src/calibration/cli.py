"""calibration command-line entry point. One subcommand per pipeline stage."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from calibration.analysis.snapshots import extract_snapshots
from calibration.polymarket.client import GammaClient
from calibration.polymarket.discovery import discover_markets
from calibration.polymarket.prices import CLOBClient, fetch_market_history
from calibration.storage.repository import (
    get_market,
    get_ticks_for_market,
    init_db,
    insert_price_ticks,
    markets_missing_history,
    markets_with_history,
    upsert_markets,
    upsert_snapshots,
)


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

    p_snap = sub.add_parser("extract-snapshots", help="Stage 3: extract calibration snapshots into price_snapshots")
    p_snap.add_argument("--db", default="data/markets.db")
    p_snap.set_defaults(func=cmd_extract_snapshots)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
