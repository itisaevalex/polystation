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
        """Fetch active markets via events endpoint for better diversity.

        Uses the events API to get one representative market per event,
        avoiding the problem of a single multi-market event (e.g. "2028
        Presidential Election") flooding results with dozens of sub-markets.
        Falls back to the flat markets endpoint on error.
        """
        try:
            return self._markets_via_events(limit)
        except Exception:
            logger.warning("Events-based fetch failed, falling back to flat markets")
            return self._flat_active_markets(limit)

    def _markets_via_events(self, limit: int) -> list[MarketInfo]:
        """Fetch events and extract the highest-volume market from each."""
        resp = requests.get(
            f"{self.host}/events",
            params={
                "limit": str(limit),
                "active": "true",
                "closed": "false",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        events = resp.json()

        results: list[MarketInfo] = []
        for event in events:
            markets = event.get("markets", [])
            if not markets:
                continue
            # Filter to open sub-markets only
            open_markets = [m for m in markets if not m.get("closed", False)]
            if not open_markets:
                continue
            # Pick the sub-market with the highest volume
            best = max(open_markets, key=lambda m: float(m.get("volumeNum", 0) or 0))
            results.append(MarketInfo.from_gamma(best))

        # Sort by volume descending
        results.sort(key=lambda m: m.volume, reverse=True)
        return results[:limit]

    def _flat_active_markets(self, limit: int) -> list[MarketInfo]:
        """Flat market list (no event dedup) — used as fallback."""
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

    def get_all_markets(self, page_size: int = 100, max_pages: int = 100) -> list[MarketInfo]:
        """Paginate through ALL active open markets from the Gamma API.

        Warning: there are ~50,000+ active markets. This can take a while.
        Use ``get_markets_page`` for incremental loading instead.
        """
        all_markets: list[MarketInfo] = []
        offset = 0
        for _ in range(max_pages):
            resp = requests.get(
                f"{self.host}/markets",
                params={
                    "limit": str(page_size),
                    "active": "true",
                    "closed": "false",
                    "offset": str(offset),
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_markets.extend(MarketInfo.from_gamma(m) for m in batch)
            offset += page_size
        logger.info("Loaded %d total active markets", len(all_markets))
        return all_markets

    def get_markets_page(self, offset: int = 0, limit: int = 100,
                         order: str = "volumeNum") -> list[MarketInfo]:
        """Fetch a single page of active open markets with ordering."""
        resp = requests.get(
            f"{self.host}/markets",
            params={
                "limit": str(limit),
                "active": "true",
                "closed": "false",
                "offset": str(offset),
                "order": order,
                "ascending": "false",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [MarketInfo.from_gamma(m) for m in resp.json()]

    def search_markets(self, query: str, limit: int = 100) -> list[MarketInfo]:
        """Search active open markets by keyword in the question text.

        The Gamma API ``slug`` parameter does partial matching on the slug
        field, which is derived from the question text.
        """
        resp = requests.get(
            f"{self.host}/markets",
            params={
                "limit": str(limit),
                "active": "true",
                "closed": "false",
                "slug": query,
                "order": "volumeNum",
                "ascending": "false",
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
