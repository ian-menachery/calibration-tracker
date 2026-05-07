"""Stage 1 (Discovery): fetch resolved markets from Gamma.

This module holds the pydantic model for raw Gamma rows and the paginated
fetcher. The filter + map to storage `Market` dataclass lives alongside
in this module (added in 2c).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from pydantic import BaseModel, ConfigDict, Field, field_validator

from calibration.polymarket.client import GammaClient
from calibration.storage.repository import Market

_BARE_OFFSET_RE = re.compile(r"[+-]\d{2}$")


class GammaMarket(BaseModel):
    """Subset of Gamma /markets fields we care about for Stage 1."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # condition_id is the only true PK; everything else can be missing on weird
    # rows (test markets, partial migrations) and we filter them out downstream.
    condition_id: str = Field(alias="conditionId")
    slug: str = ""
    question: str = ""
    market_type: str | None = Field(default=None, alias="marketType")
    neg_risk: bool = Field(default=False, alias="negRisk")
    neg_risk_market_id: str | None = Field(default=None, alias="negRiskMarketID")
    outcomes: list[str] = Field(default_factory=list)
    outcome_prices: list[str] = Field(default_factory=list, alias="outcomePrices")
    clob_token_ids: list[str] = Field(default_factory=list, alias="clobTokenIds")
    uma_end_date: datetime | None = Field(default=None, alias="umaEndDate")
    volume_num: float | None = Field(default=None, alias="volumeNum")
    uma_resolution_status: str | None = Field(default=None, alias="umaResolutionStatus")
    closed: bool = False

    # outcomes, outcomePrices, clobTokenIds come back as JSON-encoded strings, not arrays.
    # See NOTES.md — known Polymarket gotcha.
    @field_validator("outcomes", "outcome_prices", "clob_token_ids", mode="before")
    @classmethod
    def _parse_json_string(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v

    # Polymarket sometimes emits timezone offsets without minutes (e.g. `+00`
    # instead of `+00:00`), which pydantic's strict parser rejects. Some markets
    # also have outright garbage values like 'NOW*()'. Pad bare offsets and
    # return None for unparseable strings so the market gets filtered out
    # downstream rather than crashing the whole fetch.
    @field_validator("uma_end_date", mode="before")
    @classmethod
    def _normalize_dt(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        candidate = v + ":00" if _BARE_OFFSET_RE.search(v) else v
        try:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            return None
        return candidate


def fetch_resolved_markets_raw(
    client: GammaClient,
    since: datetime,
    volume_min: float = 0.0,
    limit: int = 500,
) -> Iterator[GammaMarket]:
    """Yield resolved markets from Gamma with end_date >= since across all pages.

    Sorts by volumeNum descending so we can stop once we drop below `volume_min`.
    This avoids Gamma's ~100k offset cap on `closed=true` queries — at small
    floors there are too many low-volume markets to paginate through linearly.
    """
    offset = 0
    since_iso = since.isoformat()
    while True:
        page = client.get(
            "/markets",
            closed="true",
            end_date_min=since_iso,
            order="volumeNum",
            ascending="false",
            limit=limit,
            offset=offset,
        )
        if not page:
            return
        for raw in page:
            m = GammaMarket.model_validate(raw)
            if m.volume_num is not None and m.volume_num < volume_min:
                # Sorted volumeNum desc; once below the floor every subsequent row is too.
                return
            yield m
        if len(page) < limit:
            return
        offset += limit


@dataclass(frozen=True)
class DiscoverStats:
    fetched: int
    kept: int

    @property
    def skipped(self) -> int:
        return self.fetched - self.kept


def _is_eligible_binary(m: GammaMarket, volume_floor: float) -> bool:
    """Phase 2 binary scope: standalone (non-negRisk), 2-outcome, cleanly resolved.

    Multi-outcome (negRisk) markets are deferred to Phase 6.
    """
    if not m.closed:
        return False
    if m.neg_risk:
        return False
    if len(m.outcomes) != 2 or len(m.clob_token_ids) != 2:
        return False
    if m.uma_end_date is None:
        return False
    if m.volume_num is None or m.volume_num < volume_floor:
        return False
    # Cleanly resolved: prices are exactly [0, 1] (one winner, no ties / cancellation).
    if sorted(m.outcome_prices) != ["0", "1"]:
        return False
    return True


def _to_market(m: GammaMarket, fetched_at: datetime) -> Market:
    # outcome[0] is our reference outcome; resolved_value is relative to it.
    won = m.outcome_prices[0] == "1"
    return Market(
        market_id=m.condition_id,
        slug=m.slug,
        question=m.question,
        category=None,
        market_type="binary",
        parent_event_id=None,
        end_date=m.uma_end_date,
        resolved_outcome="YES" if won else "NO",
        resolved_value=1.0 if won else 0.0,
        total_volume_usd=m.volume_num,
        fetched_at=fetched_at,
    )


def discover_markets(
    client: GammaClient,
    since: datetime,
    volume_floor: float = 1000.0,
) -> tuple[list[Market], DiscoverStats]:
    """Stage 1 entry point: fetch + filter + map to storage Market dataclass."""
    fetched_at = datetime.now(timezone.utc)
    fetched = 0
    kept: list[Market] = []
    for raw in fetch_resolved_markets_raw(client, since=since, volume_min=volume_floor):
        fetched += 1
        if _is_eligible_binary(raw, volume_floor):
            kept.append(_to_market(raw, fetched_at))
    return kept, DiscoverStats(fetched=fetched, kept=len(kept))
