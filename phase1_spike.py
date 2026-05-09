"""Phase 1 spike: confirm Polymarket prices-history is usable. See ARCHITECTURE.md §3.

Kept as a Phase 1 reference. Not used by the v1.x pipeline — the
production CLOB client lives in src/calibration/polymarket/prices.py."""

import statistics
import time
from datetime import datetime, timedelta, timezone

import httpx

CLOB = "https://clob.polymarket.com/prices-history"

# Hardcoded for the spike. Stage 1 will build the slug → token lookup properly.
SLUG = "will-donald-trump-win-the-2024-us-presidential-election"
QUESTION = "Will Donald Trump win the 2024 US Presidential Election?"
YES_TOKEN = "21742633143463906290569050155826241533067272736897614950488156847949938836455"
# umaEndDate / closedTime — actual resolution. Gamma's endDate is scheduled and drifts;
# see NOTES.md.
END_DATE = datetime(2024, 11, 6, 15, 17, 41, tzinfo=timezone.utc)
# 6-month threshold from ARCHITECTURE.md §3. Gamma's market-listing date is not
# the same as the first CLOB tick (see NOTES.md), so probe relative to resolution.
EARLY_PROBE = END_DATE - timedelta(days=180)

# CLOB rejects windows longer than ~14 days regardless of fidelity; see NOTES.md.
SNAPSHOT_WINDOW_DAYS = 14


def fetch_window(token, start, end, fidelity):
    t0 = time.monotonic()
    r = httpx.get(
        CLOB,
        params={
            "market": token,
            "startTs": int(start.timestamp()),
            "endTs": int(end.timestamp()),
            "fidelity": fidelity,
        },
        timeout=60,
    )
    elapsed = time.monotonic() - t0
    r.raise_for_status()
    return r.json().get("history", []), elapsed


def main():
    print("=" * 80)
    print(f"slug:      {SLUG}")
    print(f"question:  {QUESTION}")
    print(f"end_date:  {END_DATE.isoformat()}")
    print(f"yes_token: {YES_TOKEN}")
    print("=" * 80)

    # Snapshot window: last 14 days at minute fidelity, covers all four targets.
    window_start = END_DATE - timedelta(days=SNAPSHOT_WINDOW_DAYS)
    history, elapsed = fetch_window(YES_TOKEN, window_start, END_DATE, fidelity=1)
    if not history:
        raise SystemExit("snapshot window prices-history returned empty")
    ticks = sorted(
        (datetime.fromtimestamp(p["t"], tz=timezone.utc), p["p"]) for p in history
    )
    first_ts, last_ts = ticks[0][0], ticks[-1][0]
    gaps = [(ticks[i + 1][0] - ticks[i][0]).total_seconds() for i in range(len(ticks) - 1)]

    print("[snapshot window -- last 14 days at fidelity=1]")
    print(f"tick_count:      {len(ticks)}")
    print(f"first_tick:      {first_ts.isoformat()}")
    print(f"last_tick:       {last_ts.isoformat()}")
    print(f"span_days:       {(last_ts - first_ts).total_seconds() / 86400:.1f}")
    print(f"median_gap_s:    {statistics.median(gaps):.0f}")
    print(f"request_latency: {elapsed:.2f}s")
    print("=" * 80)

    for label, target in [
        ("close", END_DATE),
        ("1h", END_DATE - timedelta(hours=1)),
        ("24h", END_DATE - timedelta(hours=24)),
        ("7d", END_DATE - timedelta(days=7)),
    ]:
        if target < first_ts or target > last_ts:
            print(f"{label:5s} target={target.isoformat()}  (outside series)")
            continue
        actual, price = min(ticks, key=lambda x: abs((x[0] - target).total_seconds()))
        gap = (actual - target).total_seconds()
        print(
            f"{label:5s} target={target.isoformat()}  "
            f"actual={actual.isoformat()}  gap={gap:+.0f}s  price={price:.4f}"
        )
    print("=" * 80)

    # Viability Q1: confirm CLOB has data >=6 months before resolution.
    start_history, start_elapsed = fetch_window(
        YES_TOKEN, EARLY_PROBE, EARLY_PROBE + timedelta(days=1), fidelity=60
    )
    print("[6mo-back probe -- 1 day at fidelity=60, 180 days before resolution]")
    print(f"probe_window:    {EARLY_PROBE.isoformat()} -> +1d")
    print(f"tick_count:      {len(start_history)}")
    print(f"request_latency: {start_elapsed:.2f}s")
    if start_history:
        first_start_tick = datetime.fromtimestamp(start_history[0]["t"], tz=timezone.utc)
        print(f"first_tick:      {first_start_tick.isoformat()}")
    print("=" * 80)

    history_reaches_back = bool(start_history)
    minute_resolution_ok = statistics.median(gaps) <= 120
    rate_limit_ok = elapsed < 5 and start_elapsed < 5
    print("[viability -- ARCHITECTURE.md sec 3]")
    print(f"Q1 history reaches >=6mo before resolution: {'PASS' if history_reaches_back else 'FAIL'}")
    print(f"Q2 resolution fine enough for T-1h:         {'PASS' if minute_resolution_ok else 'FAIL'}")
    print(f"Q3 rate limit tolerable:                    {'PASS' if rate_limit_ok else 'FAIL'}")


if __name__ == "__main__":
    main()
