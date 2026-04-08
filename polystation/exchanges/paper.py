"""Paper exchange for backtesting — simulated fills with configurable slippage."""
from __future__ import annotations

import logging
from typing import Any

from polystation.exchanges.base import (
    Exchange,
    ExchangeOrderBook,
    ExchangePosition,
    OrderResult,
    OrderType,
)

logger = logging.getLogger(__name__)


class PaperExchange(Exchange):
    """Simulated exchange for backtesting and paper trading.

    All orders are immediately filled at the requested price adjusted for
    slippage.  No external network calls are made.

    Args:
        initial_balance: Starting USD balance. Defaults to 10 000.
        slippage_bps: One-way slippage in basis points. Defaults to 5 bps.
    """

    name = "paper"

    def __init__(
        self,
        initial_balance: float = 10000.0,
        slippage_bps: float = 5.0,
    ) -> None:
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.slippage_bps = slippage_bps
        self._positions: dict[str, ExchangePosition] = {}
        self._prices: dict[str, float] = {}  # symbol -> current price
        self._order_counter = 0
        self._trade_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """No-op — paper exchange requires no connection."""

    async def disconnect(self) -> None:
        """No-op — paper exchange requires no disconnection."""

    # ------------------------------------------------------------------
    # Price feed (used by BacktestEngine to inject historical data)
    # ------------------------------------------------------------------

    def set_price(self, symbol: str, price: float) -> None:
        """Set the current price for a symbol.

        Called by the backtesting engine to replay historical price data.

        Args:
            symbol: Token or instrument identifier.
            price: Current market price.
        """
        self._prices[symbol] = price

    # ------------------------------------------------------------------
    # Exchange interface
    # ------------------------------------------------------------------

    async def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
    ) -> OrderResult:
        """Simulate an immediate fill with configurable slippage.

        Args:
            symbol: Token or instrument identifier.
            side: ``"BUY"`` or ``"SELL"``.
            price: Requested limit price.
            size: Number of shares.
            order_type: Time-in-force (informational only — all orders fill immediately).

        Returns:
            :class:`OrderResult` with status ``"filled"`` on success or
            ``"rejected"`` when the balance is insufficient.
        """
        slippage = price * (self.slippage_bps / 10000)
        fill_price = price + slippage if side == "BUY" else price - slippage
        fill_price = max(0.001, fill_price)

        cost = fill_price * size
        if side == "BUY" and cost > self.balance:
            return OrderResult(
                order_id="",
                status="rejected",
                error="Insufficient balance",
            )

        self._order_counter += 1
        oid = f"PAPER-{self._order_counter:06d}"

        if side == "BUY":
            self.balance -= cost
        else:
            self.balance += cost

        # Update position (long-only model)
        pos = self._positions.get(symbol)
        if pos is None:
            pos = ExchangePosition(
                symbol=symbol, side="LONG", size=0, avg_entry_price=0
            )
            self._positions[symbol] = pos

        if side == "BUY":
            total_cost = pos.avg_entry_price * pos.size + fill_price * size
            pos.size += size
            pos.avg_entry_price = total_cost / pos.size if pos.size > 0 else 0.0
        else:
            pos.size = max(0.0, pos.size - size)

        self._trade_log.append(
            {
                "order_id": oid,
                "symbol": symbol,
                "side": side,
                "price": fill_price,
                "size": size,
                "balance": self.balance,
            }
        )

        logger.debug(
            "PaperExchange fill: %s %s %.4f @ %.4f — balance=%.2f",
            oid, side, size, fill_price, self.balance,
        )

        return OrderResult(
            order_id=oid,
            status="filled",
            filled_price=fill_price,
            filled_size=size,
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Always succeeds — paper orders have no resting state."""
        return True

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """Always succeeds — returns 0 (no resting orders to cancel)."""
        return 0

    async def get_orderbook(self, symbol: str) -> ExchangeOrderBook:
        """Return a synthetic one-level order book centred on the current price.

        Args:
            symbol: Token or instrument identifier.

        Returns:
            :class:`ExchangeOrderBook` with one bid and one ask level.
        """
        price = self._prices.get(symbol, 0.5)
        return ExchangeOrderBook(
            symbol=symbol,
            bids=[(price - 0.01, 1000.0)],
            asks=[(price + 0.01, 1000.0)],
        )

    async def get_positions(self) -> list[ExchangePosition]:
        """Return all open positions with non-zero size.

        Returns:
            List of :class:`ExchangePosition` objects.
        """
        return [p for p in self._positions.values() if p.size > 0]

    async def get_balance(self) -> dict[str, float]:
        """Return the current simulated USD balance.

        Returns:
            Mapping ``{"USD": <current_balance>}``.
        """
        return {"USD": self.balance}

    async def get_midpoint(self, symbol: str) -> float | None:
        """Return the current price for *symbol*, or None if not set.

        Args:
            symbol: Token or instrument identifier.

        Returns:
            Current price, or None when no price has been set.
        """
        return self._prices.get(symbol)

    async def get_price(self, symbol: str, side: str) -> float | None:
        """Return the slippage-adjusted price for *symbol* on *side*.

        Args:
            symbol: Token or instrument identifier.
            side: ``"BUY"`` or ``"SELL"``.

        Returns:
            Slippage-adjusted price, or None when no price has been set.
        """
        price = self._prices.get(symbol)
        if price is None:
            return None
        slippage = price * (self.slippage_bps / 10000)
        return price + slippage if side == "BUY" else price - slippage

    async def health_check(self) -> bool:
        """Paper exchange is always healthy.

        Returns:
            Always ``True``.
        """
        return True

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------

    def get_pnl(self) -> float:
        """Calculate total P&L from the initial balance (mark-to-market).

        Open positions are valued at the last known price for each symbol,
        falling back to the average entry price when no price is available.

        Returns:
            Floating P&L in USD (positive = profit).
        """
        mtm = self.balance
        for pos in self._positions.values():
            mark_price = self._prices.get(pos.symbol, pos.avg_entry_price)
            mtm += pos.size * mark_price
        return mtm - self.initial_balance

    def reset(self) -> None:
        """Reset the exchange to its initial state.

        Clears all positions, prices, orders, and the trade log, and restores
        the balance to ``initial_balance``.
        """
        self.balance = self.initial_balance
        self._positions.clear()
        self._prices.clear()
        self._order_counter = 0
        self._trade_log.clear()
        logger.debug("PaperExchange reset to initial state")
