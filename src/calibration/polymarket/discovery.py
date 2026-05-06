"""Stage 1 (Discovery): fetch resolved markets from Gamma.

This module holds the pydantic model for raw Gamma rows and the paginated
fetcher. The filter + map to storage `Market` dataclass lives alongside
in this module (added in 2c).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field, field_validator

from calibration.polymarket.client import GammaClient

_BARE_OFFSET_RE = re.compile(r"[+-]\d{2}$")


class GammaMarket(BaseModel):
    """Subset of Gamma /markets fields we care about for Stage 1."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    condition_id: str = Field(alias="conditionId")
    slug: str
    question: str
    market_type: str = Field(alias="marketType")
    neg_risk: bool = Field(default=False, alias="negRisk")
    neg_risk_market_id: str | None = Field(default=None, alias="negRiskMarketID")
    outcomes: list[str]
    outcome_prices: list[str] = Field(alias="outcomePrices")
    clob_token_ids: list[str] = Field(alias="clobTokenIds")
    uma_end_date: datetime | None = Field(default=None, alias="umaEndDate")
    volume_num: float | None = Field(default=None, alias="volumeNum")
    uma_resolution_status: str | None = Field(default=None, alias="umaResolutionStatus")
    closed: bool

    # outcomes, outcomePrices, clobTokenIds come back as JSON-encoded strings, not arrays.
    # See NOTES.md — known Polymarket gotcha.
    @field_validator("outcomes", "outcome_prices", "clob_token_ids", mode="before")
    @classmethod
    def _parse_json_string(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    # Polymarket sometimes emits timezone offsets without minutes (e.g. `+00` instead
    # of `+00:00`), which pydantic's strict ISO parser rejects. Pad before parsing.
    @field_validator("uma_end_date", mode="before")
    @classmethod
    def _normalize_dt(cls, v: object) -> object:
        if isinstance(v, str) and _BARE_OFFSET_RE.search(v):
            return v + ":00"
        return v


def fetch_resolved_markets_raw(
    client: GammaClient,
    since: datetime,
    limit: int = 500,
) -> Iterator[GammaMarket]:
    """Yield resolved markets from Gamma with end_date >= since across all pages.

    Uses Gamma's `closed=true` filter (per NOTES.md, required to surface resolved
    markets) and `end_date_min` for the time window.
    """
    offset = 0
    since_iso = since.isoformat()
    while True:
        page = client.get(
            "/markets",
            closed="true",
            end_date_min=since_iso,
            limit=limit,
            offset=offset,
        )
        if not page:
            return
        for raw in page:
            yield GammaMarket.model_validate(raw)
        if len(page) < limit:
            return
        offset += limit
