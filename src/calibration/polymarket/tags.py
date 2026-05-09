"""Stage v1.1b: fetch category tags per market via Gamma /events/{id}.

Mirrors the prices.py pattern: thin module that catches httpx.HTTPError
and returns None on transient failure, so the caller can skip and the
next --resume run picks up missing markets via markets_missing_tags.
"""

from __future__ import annotations

import httpx

from calibration.polymarket.client import GammaClient


def fetch_event_tags(client: GammaClient, event_id: str) -> list[str] | None:
    """Pull the tag slugs from a Gamma event.

    Returns None on any HTTP/network error (caller skips, --resume picks
    up next run). Returns an empty list if the event genuinely has no
    tags — caller should distinguish if it cares; we treat it as a skip
    too since there's nothing to insert.
    """
    try:
        payload = client.get(f"/events/{event_id}")
    except httpx.HTTPError:
        return None
    tags = payload.get("tags") or []
    return [t["slug"] for t in tags if isinstance(t, dict) and t.get("slug")]
