"""Stage 2: fetch CLOB price history per market.

Path C from the Phase 3 plan: per market, fetch hourly fidelity for the last
14 days plus minute fidelity for the last 24 hours, and store both. CLOB caps
windows at ~14 days regardless of fidelity (see notes/NOTES.md).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from calibration.storage.repository import Market, PriceTick

CLOB_BASE_URL = "https://clob.polymarket.com"


class CLOBClient:
    def __init__(
        self,
        base_url: str = CLOB_BASE_URL,
        request_delay_s: float = 0.2,
        timeout_s: float = 60.0,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._request_delay_s = request_delay_s

    def get(self, path: str, **params: Any) -> Any:
        time.sleep(self._request_delay_s)
        r = self._client.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CLOBClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def fetch_window(
    client: CLOBClient,
    market_id: str,
    token: str,
    start: datetime,
    end: datetime,
    fidelity: int,
) -> list[PriceTick]:
    payload = client.get(
        "/prices-history",
        market=token,
        startTs=int(start.timestamp()),
        endTs=int(end.timestamp()),
        fidelity=fidelity,
    )
    history = payload.get("history") or []
    return [
        PriceTick(
            market_id=market_id,
            timestamp=datetime.fromtimestamp(p["t"], tz=timezone.utc),
            price=p["p"],
        )
        for p in history
    ]


def fetch_order_book(client: CLOBClient, token: str) -> dict | None:
    """Fetch the live CLOB order book for a token and normalize it best-first.

    The CLOB returns bids ascending and asks descending (best price last) with string
    values; we parse to floats and sort bids desc / asks asc so the best level is first
    (what vwap_fill expects). Returns {bids, asks, best_bid, best_ask} or None on HTTP
    error / empty book.
    """
    try:
        book = client.get("/book", token_id=token)
    except httpx.HTTPError:
        return None
    bids = sorted(((float(b["price"]), float(b["size"])) for b in book.get("bids") or []),
                  key=lambda x: x[0], reverse=True)
    asks = sorted(((float(a["price"]), float(a["size"])) for a in book.get("asks") or []),
                  key=lambda x: x[0])
    if not bids or not asks:
        return None
    return {"bids": bids, "asks": asks, "best_bid": bids[0][0], "best_ask": asks[0][0]}


def fetch_market_history(client: CLOBClient, market: Market) -> list[PriceTick] | None:
    """Path C fetch: hourly 14d + minute 24h. Returns None on any HTTP/network
    error or empty response. httpx.HTTPError covers HTTPStatusError (4xx/5xx)
    plus connection-level failures like RemoteProtocolError, ConnectError, and
    ReadTimeout — any of which can hit during a multi-thousand-market backfill.
    Skipped markets get picked up on the next --resume run.
    """
    if market.yes_token_id is None:
        return None
    end = market.end_date
    try:
        hourly = fetch_window(
            client, market.market_id, market.yes_token_id,
            end - timedelta(days=14), end, fidelity=60,
        )
        minute = fetch_window(
            client, market.market_id, market.yes_token_id,
            end - timedelta(hours=24), end, fidelity=1,
        )
    except httpx.HTTPError:
        return None
    ticks = hourly + minute
    return ticks if ticks else None
