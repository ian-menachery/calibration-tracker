"""Kalshi public API client. All HTTP lives here per CLAUDE.md.

Public settled-market and candlestick reads need NO authentication, so there is no
RSA-PSS signing and no `cryptography` dependency — the locked stack stays intact.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        request_delay_s: float = 0.2,   # ~5 req/s, well under Kalshi's ~10 req/s
        timeout_s: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._request_delay_s = request_delay_s
        self._max_retries = max_retries

    def get(self, path: str, **params: Any) -> Any:
        """GET with rate-limit sleep and capped backoff on 429/5xx."""
        delay = self._request_delay_s
        for attempt in range(self._max_retries + 1):
            time.sleep(self._request_delay_s)
            r = self._client.get(path, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self._max_retries:
                    r.raise_for_status()
                time.sleep(min(delay, 8.0))
                delay *= 2
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")  # loop returns or raises

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
