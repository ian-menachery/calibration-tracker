"""Kalshi candlesticks -> PriceTick time series (the one net-new piece vs PMRA).

PMRA never fetched historical Kalshi prices; our whole method is price-at-horizon,
so we pull the market-candlesticks endpoint and turn it into the same PriceTick
shape the Polymarket path produces, letting analysis/snapshots.extract_snapshots run
unchanged. Series ticker is the prefix of the market ticker (e.g. KXBTCD-...-> KXBTCD).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from calibration.kalshi.client import KalshiClient
from calibration.storage.repository import Market, PriceTick


def _candle_price(c: dict) -> float | None:
    """Close price for a candle in [0,1] dollars: prefer the trade close, fall back to
    the yes bid/ask midpoint. None if the period had no usable price."""
    block = c.get("price") or {}
    val = block.get("close_dollars")
    if val is None:
        yb = (c.get("yes_bid") or {}).get("close_dollars")
        ya = (c.get("yes_ask") or {}).get("close_dollars")
        if yb is not None and ya is not None:
            return (float(yb) + float(ya)) / 2.0
        return None
    return float(val)


def fetch_candles(
    client: KalshiClient, ticker: str, start: datetime, end: datetime, period_interval: int
) -> list[PriceTick]:
    series = ticker.split("-")[0]
    payload = client.get(
        f"/series/{series}/markets/{ticker}/candlesticks",
        start_ts=int(start.timestamp()),
        end_ts=int(end.timestamp()),
        period_interval=period_interval,
    )
    ticks = []
    for c in payload.get("candlesticks") or []:
        price = _candle_price(c)
        if price is None:
            continue
        ticks.append(PriceTick(
            market_id=ticker,
            timestamp=datetime.fromtimestamp(c["end_period_ts"], tz=timezone.utc),
            price=price,
        ))
    return ticks


def fetch_market_candles(client: KalshiClient, market: Market) -> list[PriceTick] | None:
    """Hourly over the last 14 days plus minute over the last 24 hours (mirrors the
    Polymarket Path-C window). Returns None on HTTP error or empty series."""
    end = market.end_date
    try:
        hourly = fetch_candles(client, market.market_id, end - timedelta(days=14), end, period_interval=60)
        minute = fetch_candles(client, market.market_id, end - timedelta(hours=24), end, period_interval=1)
    except httpx.HTTPError:
        return None
    ticks = hourly + minute
    return ticks if ticks else None
