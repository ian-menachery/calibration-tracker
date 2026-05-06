"""Polymarket Gamma API client. All HTTP lives here per CLAUDE.md."""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://gamma-api.polymarket.com"


class GammaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        request_delay_s: float = 0.2,
        timeout_s: float = 30.0,
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

    def __enter__(self) -> "GammaClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
