"""calibration command-line entry point. One subcommand per pipeline stage."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from calibration.polymarket.client import GammaClient
from calibration.polymarket.discovery import discover_markets
from calibration.storage.repository import init_db, upsert_markets


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibration")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover", help="Stage 1: fetch resolved binary markets from Gamma")
    p_discover.add_argument("--since", required=True, help="ISO date, e.g. 2024-01-01")
    p_discover.add_argument("--volume-floor", type=float, default=1_000_000.0)
    p_discover.add_argument("--db", default="data/markets.db")
    p_discover.set_defaults(func=cmd_discover)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
