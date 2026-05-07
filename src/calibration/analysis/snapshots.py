"""Stage 3: extract calibration snapshots from raw price history.

Pure function — no API calls, no SQL. For each market we want four prices:
  - close: latest tick at or before end_date (within 1h tolerance)
  - 1h:    closest tick to end_date - 1 hour    (within 30 min tolerance)
  - 24h:   closest tick to end_date - 24 hours  (within 2 h tolerance)
  - 7d:    closest tick to end_date - 7 days    (within 12 h tolerance)

Tolerances reflect Phase 1 spike findings: minute-fidelity gives ~22s gaps for
1h/24h, hourly fidelity gives ~30 min gaps for 7d. If no tick falls within
tolerance, that snapshot is OMITTED — never invented (per CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from calibration.storage.repository import Market, PriceTick, Snapshot

# (snapshot_type, offset_from_end_date, tolerance)
_OFFSET_TARGETS = [
    ("1h",  timedelta(hours=1),  timedelta(minutes=30)),
    ("24h", timedelta(hours=24), timedelta(hours=2)),
    ("7d",  timedelta(days=7),   timedelta(hours=12)),
]
_CLOSE_TOLERANCE = timedelta(hours=1)


def extract_snapshots(market: Market, ticks: Iterable[PriceTick]) -> list[Snapshot]:
    # Defensive: end_date in the future shouldn't happen post discover (closed=true),
    # but if it does, we have nothing meaningful to anchor against.
    if market.end_date > datetime.now(timezone.utc):
        return []

    sorted_ticks = sorted(ticks, key=lambda t: t.timestamp)
    if not sorted_ticks:
        return []

    out: list[Snapshot] = []

    # Close: latest tick at or before end_date, within tolerance.
    pre_end = [t for t in sorted_ticks if t.timestamp <= market.end_date]
    if pre_end:
        last = pre_end[-1]
        if (market.end_date - last.timestamp) <= _CLOSE_TOLERANCE:
            out.append(Snapshot(
                market_id=market.market_id,
                snapshot_type="close",
                price=last.price,
                observed_at=last.timestamp,
            ))

    # 1h, 24h, 7d: direction-agnostic closest tick to target, within tolerance.
    for label, offset, tol in _OFFSET_TARGETS:
        target = market.end_date - offset
        closest = min(sorted_ticks, key=lambda t: abs((t.timestamp - target).total_seconds()))
        if abs(closest.timestamp - target) <= tol:
            out.append(Snapshot(
                market_id=market.market_id,
                snapshot_type=label,
                price=closest.price,
                observed_at=closest.timestamp,
            ))

    return out
