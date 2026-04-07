"""Unified market data client wrapping the Polymarket CLOB REST API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"


@dataclass
class MarketPrice:
    """Snapshot of pricing data for a single token."""

    token_id: str
    midpoint: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    last_trade: float | None = None
    last_trade_side: str | None = None


class MarketDataClient:
    """Read-only market data from Polymarket CLOB and Gamma APIs.

    Uses py-clob-client for CLOB endpoints and raw requests for Gamma.
    All methods are synchronous (CLOB client is sync).
    """

    def __init__(self, host: str = CLOB_HOST) -> None:
        self._client = ClobClient(host, chain_id=POLYGON)
        logger.info("MarketDataClient initialized (host=%s)", host)

    def health(self) -> bool:
        """Check if the CLOB API is up."""
        try:
            resp = self._client.get_ok()
            return resp == "OK"
        except Exception:
            return False

    def server_time(self) -> int:
        """Return server Unix timestamp."""
        return int(self._client.get_server_time())

    def get_markets(self, next_cursor: str = "MA==") -> dict[str, Any]:
        """Fetch a page of markets from the CLOB API."""
        return self._client.get_markets(next_cursor=next_cursor)

    def get_market(self, condition_id: str) -> dict[str, Any]:
        """Fetch a single market by condition ID."""
        return self._client.get_market(condition_id)

    def get_simplified_markets(self, next_cursor: str = "MA==") -> dict[str, Any]:
        """Fetch lightweight market list."""
        return self._client.get_simplified_markets(next_cursor=next_cursor)

    def get_order_book(self, token_id: str) -> Any:
        """Fetch the full order book for a token."""
        return self._client.get_order_book(token_id)

    def get_midpoint(self, token_id: str) -> float | None:
        """Get mid-market price for a token. Returns None on error."""
        try:
            resp = self._client.get_midpoint(token_id)
            mid = resp.get("mid") if isinstance(resp, dict) else None
            return float(mid) if mid else None
        except Exception:
            logger.warning("Failed to get midpoint for %s", token_id)
            return None

    def get_price(self, token_id: str, side: str) -> float | None:
        """Get best price for a token on the given side (BUY/SELL)."""
        try:
            resp = self._client.get_price(token_id, side)
            price = resp.get("price") if isinstance(resp, dict) else None
            return float(price) if price else None
        except Exception:
            logger.warning("Failed to get price for %s side=%s", token_id, side)
            return None

    def get_spread(self, token_id: str) -> float | None:
        """Get bid-ask spread for a token."""
        try:
            resp = self._client.get_spread(token_id)
            spread = resp.get("spread") if isinstance(resp, dict) else None
            return float(spread) if spread else None
        except Exception:
            logger.warning("Failed to get spread for %s", token_id)
            return None

    def get_last_trade_price(self, token_id: str) -> MarketPrice:
        """Get last trade price and side for a token."""
        try:
            resp = self._client.get_last_trade_price(token_id)
            if isinstance(resp, dict):
                return MarketPrice(
                    token_id=token_id,
                    last_trade=float(resp["price"]) if resp.get("price") else None,
                    last_trade_side=resp.get("side"),
                )
        except Exception:
            logger.warning("Failed to get last trade for %s", token_id)
        return MarketPrice(token_id=token_id)

    def get_tick_size(self, token_id: str) -> float | None:
        """Get minimum tick size for a token."""
        try:
            resp = self._client.get_tick_size(token_id)
            return float(resp) if resp else None
        except Exception:
            logger.warning("Failed to get tick size for %s", token_id)
            return None

    def get_full_pricing(self, token_id: str) -> MarketPrice:
        """Fetch all pricing data for a token in one call."""
        mp = MarketPrice(token_id=token_id)
        mp.midpoint = self.get_midpoint(token_id)
        mp.best_bid = self.get_price(token_id, "BUY")
        mp.best_ask = self.get_price(token_id, "SELL")
        mp.spread = self.get_spread(token_id)
        last = self.get_last_trade_price(token_id)
        mp.last_trade = last.last_trade
        mp.last_trade_side = last.last_trade_side
        return mp
