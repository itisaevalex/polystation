"""Order book model with computed spread, midpoint, and depth properties."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PriceLevel:
    """Single price level in the order book."""

    price: float
    size: float


@dataclass
class OrderBook:
    """Snapshot of an order book for a single token."""

    token_id: str
    market_id: str = ""
    timestamp: str = ""
    bids: list[PriceLevel] = field(default_factory=list)
    asks: list[PriceLevel] = field(default_factory=list)
    tick_size: float = 0.01
    last_trade_price: float | None = None

    @property
    def best_bid(self) -> PriceLevel | None:
        """Highest bid level, or None if the book is empty."""
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> PriceLevel | None:
        """Lowest ask level, or None if the book is empty."""
        return self.asks[0] if self.asks else None

    @property
    def spread(self) -> float | None:
        """Bid-ask spread, or None when either side is empty."""
        if self.best_bid and self.best_ask:
            return round(self.best_ask.price - self.best_bid.price, 6)
        return None

    @property
    def midpoint(self) -> float | None:
        """Mid-market price, or None when either side is empty."""
        if self.best_bid and self.best_ask:
            return round((self.best_bid.price + self.best_ask.price) / 2, 6)
        return None

    @property
    def bid_depth(self) -> float:
        """Total size across all bid levels."""
        return sum(level.size for level in self.bids)

    @property
    def ask_depth(self) -> float:
        """Total size across all ask levels."""
        return sum(level.size for level in self.asks)

    @classmethod
    def from_clob_response(cls, token_id: str, raw: Any) -> OrderBook:
        """Parse a py-clob-client OrderBookSummary or dict into an OrderBook."""
        if hasattr(raw, "__dict__"):
            data: dict[str, Any] = vars(raw)
        elif isinstance(raw, dict):
            data = raw
        else:
            logger.warning("Unrecognised order book response type for token %s: %s", token_id, type(raw))
            return cls(token_id=token_id)

        bids = [PriceLevel(float(b["price"]), float(b["size"])) for b in data.get("bids", [])]
        asks = [PriceLevel(float(a["price"]), float(a["size"])) for a in data.get("asks", [])]
        # Bids descending (highest first), asks ascending (lowest first)
        bids.sort(key=lambda lv: lv.price, reverse=True)
        asks.sort(key=lambda lv: lv.price)

        ltp = data.get("last_trade_price")

        return cls(
            token_id=token_id,
            market_id=data.get("market", ""),
            timestamp=data.get("timestamp", ""),
            bids=bids,
            asks=asks,
            tick_size=float(data.get("tick_size", "0.01")),
            last_trade_price=float(ltp) if ltp else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the order book snapshot for JSON output or dashboard use."""
        return {
            "token_id": self.token_id,
            "market_id": self.market_id,
            "timestamp": self.timestamp,
            "best_bid": {"price": self.best_bid.price, "size": self.best_bid.size} if self.best_bid else None,
            "best_ask": {"price": self.best_ask.price, "size": self.best_ask.size} if self.best_ask else None,
            "spread": self.spread,
            "midpoint": self.midpoint,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
            "last_trade_price": self.last_trade_price,
        }
