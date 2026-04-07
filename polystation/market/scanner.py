"""Market discovery via the Polymarket Gamma REST API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

GAMMA_HOST = "https://gamma-api.polymarket.com"


def _float_or_none(value: Any) -> float | None:
    """Coerce *value* to float, returning None on failure or falsy input."""
    try:
        return float(value) if value else None
    except (ValueError, TypeError):
        return None


def _parse_json_list(value: Any) -> list[Any]:
    """Return *value* as a list, JSON-decoding it first if it is a string."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


@dataclass
class MarketInfo:
    """Lightweight market metadata from the Gamma API."""

    condition_id: str
    question: str
    slug: str
    active: bool
    closed: bool
    volume: float
    liquidity: float
    best_bid: float | None
    best_ask: float | None
    last_trade_price: float | None
    token_ids: list[str]
    outcomes: list[str]
    image: str
    neg_risk: bool

    @classmethod
    def from_gamma(cls, data: dict[str, Any]) -> MarketInfo:
        """Construct a MarketInfo from a raw Gamma API market dict."""
        return cls(
            condition_id=data.get("conditionId", data.get("condition_id", "")),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            active=bool(data.get("active", False)),
            closed=bool(data.get("closed", False)),
            volume=float(data.get("volumeNum", data.get("volume", 0)) or 0),
            liquidity=float(data.get("liquidityNum", data.get("liquidity", 0)) or 0),
            best_bid=_float_or_none(data.get("bestBid")),
            best_ask=_float_or_none(data.get("bestAsk")),
            last_trade_price=_float_or_none(data.get("lastTradePrice")),
            token_ids=_parse_json_list(data.get("clobTokenIds", [])),
            outcomes=_parse_json_list(data.get("outcomes", [])),
            image=data.get("image", ""),
            neg_risk=bool(data.get("negRisk", False)),
        )


class MarketScanner:
    """Discover and search Polymarket markets via the Gamma API."""

    def __init__(self, host: str = GAMMA_HOST, timeout: int = 15) -> None:
        self.host = host
        self.timeout = timeout

    def get_active_markets(self, limit: int = 50) -> list[MarketInfo]:
        """Fetch active, non-closed markets sorted by descending volume."""
        resp = requests.get(
            f"{self.host}/markets",
            params={
                "limit": str(limit),
                "active": "true",
                "closed": "false",
                "order": "volumeNum",
                "ascending": "false",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [MarketInfo.from_gamma(m) for m in resp.json()]

    def search_markets(self, query: str, limit: int = 20) -> list[MarketInfo]:
        """Search active markets by slug keyword."""
        resp = requests.get(
            f"{self.host}/markets",
            params={
                "limit": str(limit),
                "active": "true",
                "closed": "false",
                "slug": query,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [MarketInfo.from_gamma(m) for m in resp.json()]

    def get_events(self, limit: int = 20, active: bool = True) -> list[dict[str, Any]]:
        """Fetch events (groups of related markets)."""
        resp = requests.get(
            f"{self.host}/events",
            params={
                "limit": str(limit),
                "active": str(active).lower(),
                "closed": "false",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def get_trending(self, limit: int = 10) -> list[MarketInfo]:
        """Get markets with the highest 24-hour volume."""
        resp = requests.get(
            f"{self.host}/markets",
            params={
                "limit": str(limit),
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [MarketInfo.from_gamma(m) for m in resp.json()]
