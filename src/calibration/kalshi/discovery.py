"""Kalshi settled-binary discovery, by series.

The raw /markets feed is ~99% auto-generated MVE parlay markets, so we discover
per-series: each series ticker (KXBTC, KXNBA, ...) maps cleanly to one of our
categories — the series prefix IS the categorical key, no slug heuristic needed.
Settled binary markets carry a yes/no `result`, native open/close/created times,
and decimal-dollar prices. Maps into the venue-neutral Market dataclass with
venue='kalshi' so the existing scorer runs unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from pydantic import BaseModel, ConfigDict

from calibration.kalshi.client import KalshiClient
from calibration.storage.repository import Market

# Curated series -> our category buckets. Matched-category cross-venue comparison
# uses whichever of these also appear on Polymarket (sports, crypto in practice).
KALSHI_SERIES: dict[str, str] = {
    "KXBTC": "crypto", "KXBTCD": "crypto", "KXETH": "crypto", "KXETHD": "crypto",
    "KXNBA": "sports", "KXNFL": "sports", "KXNHL": "sports", "KXMLB": "sports",
    "KXNBAGAME": "sports", "KXNFLGAME": "sports",
    "KXFED": "other", "KXHIGHNY": "other",
}


class KalshiMarket(BaseModel):
    """Subset of Kalshi /markets fields for a settled binary market."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    ticker: str
    event_ticker: str = ""
    title: str = ""
    market_type: str | None = None
    result: str | None = None  # 'yes' / 'no' for settled binaries
    open_time: datetime | None = None
    close_time: datetime | None = None
    created_time: datetime | None = None
    volume_fp: float | None = None
    notional_value_dollars: float | None = None
    mve_collection_ticker: str | None = None


def _is_settled_binary(m: KalshiMarket) -> bool:
    return (
        m.market_type == "binary"
        and m.result in ("yes", "no")
        and not m.mve_collection_ticker          # drop auto-generated parlays
        and m.close_time is not None
    )


def to_market(m: KalshiMarket, category: str, fetched_at: datetime) -> Market:
    won = m.result == "yes"
    volume = m.notional_value_dollars if m.notional_value_dollars is not None else (m.volume_fp or 0.0)
    return Market(
        market_id=m.ticker,
        slug=m.ticker,
        question=m.title or m.ticker,
        category=category,
        market_type="binary",
        parent_event_id=None,
        end_date=m.close_time,
        resolved_outcome="YES" if won else "NO",
        resolved_value=1.0 if won else 0.0,
        total_volume_usd=volume,
        fetched_at=fetched_at,
        yes_token_id=None,        # Kalshi has no CLOB token; candles are fetched by ticker
        gamma_event_id=None,
        created_at=m.created_time,
        venue="kalshi",
    )


def fetch_settled_markets(
    client: KalshiClient, series: dict[str, str], limit: int = 200, max_per_series: int = 500
) -> Iterator[Market]:
    """Yield settled binary Markets across the given {series_ticker: category} map,
    cursor-paginating each series. `max_per_series` caps each series (settled markets,
    newest first) so the high-frequency daily crypto series don't pull tens of thousands
    of 1-hour markets. Maps each to the venue-neutral Market shape."""
    fetched_at = datetime.now(timezone.utc)
    for series_ticker, category in series.items():
        cursor: str | None = None
        taken = 0
        while taken < max_per_series:
            params = {"series_ticker": series_ticker, "status": "settled", "limit": limit}
            if cursor:
                params["cursor"] = cursor
            body = client.get("/markets", **params) or {}
            for raw in body.get("markets") or []:
                m = KalshiMarket.model_validate(raw)
                if _is_settled_binary(m):
                    yield to_market(m, category, fetched_at)
                    taken += 1
                    if taken >= max_per_series:
                        break
            cursor = body.get("cursor") or ""
            if not cursor:
                break
