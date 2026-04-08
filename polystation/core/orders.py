"""Order lifecycle management — tracking, state transitions, history."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    """All states an order can occupy from creation through settlement."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class Order:
    """Represents a single order through its full lifecycle.

    Attributes:
        id: Internal order identifier, e.g. "ORD-000001".
        token_id: Polymarket token identifier for the outcome.
        side: "BUY" or "SELL".
        price: Requested limit price between 0 and 1.
        size: Requested number of shares.
        status: Current lifecycle state.
        order_type: Time-in-force type (GTC, FOK, GTD, FAK).
        filled_size: Cumulative shares filled so far.
        avg_fill_price: Volume-weighted average fill price.
        market_id: Optional parent market identifier.
        kernel_name: Name of the kernel that placed this order.
        created_at: ISO-8601 timestamp of order creation.
        updated_at: ISO-8601 timestamp of the last status change.
        server_order_id: Order ID returned by the CLOB server.
        error: Human-readable error message if rejected.
    """

    id: str
    token_id: str
    side: str           # "BUY" / "SELL"
    price: float
    size: float
    status: OrderStatus = OrderStatus.PENDING
    order_type: str = "GTC"   # GTC, FOK, IOC, GTD, MARKET
    expiry: str = ""           # ISO-8601 expiry timestamp for GTD orders
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    market_id: str = ""
    kernel_name: str = ""     # Which kernel placed this order
    exchange: str = ""         # Exchange adapter name (e.g. "polymarket")
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = ""
    server_order_id: str = ""
    error: str = ""

    @property
    def remaining_size(self) -> float:
        """Shares still to be filled."""
        return max(0.0, self.size - self.filled_size)

    @property
    def is_active(self) -> bool:
        """True while the order can still receive fills or be cancelled."""
        return self.status in (
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the order to a JSON-safe dict."""
        return {
            "id": self.id,
            "token_id": self.token_id,
            "side": self.side,
            "price": self.price,
            "size": self.size,
            "filled_size": self.filled_size,
            "remaining_size": self.remaining_size,
            "avg_fill_price": self.avg_fill_price,
            "status": self.status.value,
            "order_type": self.order_type,
            "expiry": self.expiry,
            "market_id": self.market_id,
            "kernel_name": self.kernel_name,
            "exchange": self.exchange,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "server_order_id": self.server_order_id,
            "error": self.error,
            "is_active": self.is_active,
        }


class OrderManager:
    """Tracks all orders across all kernels.

    Provides a central registry for creating, updating, and querying orders.
    The sequential ``ORD-NNNNNN`` ID scheme makes logs easy to correlate.
    """

    def __init__(self) -> None:
        self.orders: dict[str, Order] = {}
        self._next_id: int = 0

    def create_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        market_id: str = "",
        kernel_name: str = "",
        order_type: str = "GTC",
        exchange: str = "",
        expiry: str = "",
    ) -> Order:
        """Create, register, and return a new order in PENDING state.

        Args:
            token_id: Polymarket token identifier for the outcome.
            side: "BUY" or "SELL".
            price: Limit price between 0 and 1.
            size: Number of shares requested.
            market_id: Optional parent market identifier.
            kernel_name: Name of the kernel placing the order.
            order_type: Time-in-force type. Defaults to "GTC".
            exchange: Exchange adapter name (e.g. "polymarket").
            expiry: ISO-8601 expiry timestamp for GTD orders.

        Returns:
            The newly created Order.
        """
        self._next_id += 1
        order_id = f"ORD-{self._next_id:06d}"
        order = Order(
            id=order_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            market_id=market_id,
            kernel_name=kernel_name,
            order_type=order_type,
            exchange=exchange,
            expiry=expiry,
        )
        self.orders[order_id] = order
        logger.info(
            "Order created: %s %s %.0f @ %.4f (%s)",
            order_id,
            side,
            size,
            price,
            kernel_name,
        )
        return order

    def update_status(
        self,
        order_id: str,
        status: OrderStatus,
        server_order_id: str = "",
        error: str = "",
    ) -> Order | None:
        """Transition an order to a new status.

        Args:
            order_id: Internal order identifier.
            status: Target OrderStatus value.
            server_order_id: CLOB-assigned ID to store, if provided.
            error: Error message to attach on rejection.

        Returns:
            Updated Order, or None if *order_id* is unknown.
        """
        order = self.orders.get(order_id)
        if order is None:
            logger.warning("Order %s not found", order_id)
            return None
        order.status = status
        order.updated_at = datetime.now().isoformat()
        if server_order_id:
            order.server_order_id = server_order_id
        if error:
            order.error = error
        logger.info("Order %s → %s", order_id, status.value)
        return order

    def record_fill(
        self,
        order_id: str,
        fill_price: float,
        fill_size: float,
    ) -> Order | None:
        """Record a partial or full fill against an order.

        Updates ``filled_size`` and ``avg_fill_price`` using a running
        volume-weighted average, then transitions the order to FILLED or
        PARTIALLY_FILLED as appropriate.

        Args:
            order_id: Internal order identifier.
            fill_price: Price at which shares were filled.
            fill_size: Number of shares filled in this event.

        Returns:
            Updated Order, or None if *order_id* is unknown.
        """
        order = self.orders.get(order_id)
        if order is None:
            return None
        total_cost = order.avg_fill_price * order.filled_size + fill_price * fill_size
        order.filled_size += fill_size
        order.avg_fill_price = (
            total_cost / order.filled_size if order.filled_size > 0 else 0.0
        )
        order.updated_at = datetime.now().isoformat()
        if order.filled_size >= order.size:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        logger.info(
            "Order %s filled %.0f @ %.4f (total filled: %.0f/%.0f)",
            order_id,
            fill_size,
            fill_price,
            order.filled_size,
            order.size,
        )
        return order

    def get_active_orders(self, kernel_name: str | None = None) -> list[Order]:
        """Return all active orders, optionally filtered to one kernel.

        Args:
            kernel_name: When provided, only orders from this kernel are
                returned.

        Returns:
            List of active Order objects.
        """
        orders = [o for o in self.orders.values() if o.is_active]
        if kernel_name:
            orders = [o for o in orders if o.kernel_name == kernel_name]
        return orders

    def get_order(self, order_id: str) -> Order | None:
        """Look up a single order by its internal ID."""
        return self.orders.get(order_id)

    def get_all_orders(self, limit: int = 100) -> list[Order]:
        """Return the most recent orders sorted by creation time descending.

        Args:
            limit: Maximum number of orders to return. Defaults to 100.

        Returns:
            List of Order objects, most-recent first.
        """
        orders = sorted(
            self.orders.values(), key=lambda o: o.created_at, reverse=True
        )
        return orders[:limit]

    def get_summary(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of order book state.

        Returns:
            Dict with total, active, and filled order counts plus the 20
            most-recent orders serialized as dicts.
        """
        active = [o for o in self.orders.values() if o.is_active]
        filled = [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
        return {
            "total_orders": len(self.orders),
            "active_orders": len(active),
            "filled_orders": len(filled),
            "orders": [o.to_dict() for o in self.get_all_orders(20)],
        }
