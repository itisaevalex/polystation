"""Market maker kernel — places symmetric bid/ask orders around the midpoint."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from polystation.core.kernel import Kernel
from polystation.kernels import register

if TYPE_CHECKING:
    from polystation.core.engine import TradingEngine

logger = logging.getLogger(__name__)


@register
class MarketMakerKernel(Kernel):
    """Simple market making strategy.

    Places symmetric bid and ask orders around the current midpoint.
    Refreshes orders at a configurable interval.

    Parameters:
        token_id: The token to market-make on.
        spread: Half-spread in price units (e.g. ``0.02`` = 2 cents each side).
        size: Order size per side.
        refresh_interval: Seconds between order refreshes.
        max_position: Maximum net position before the buy side is paused.
    """

    name = "market-maker"

    def __init__(
        self,
        token_id: str,
        spread: float = 0.02,
        size: float = 50,
        refresh_interval: float = 30.0,
        max_position: float = 500,
    ) -> None:
        super().__init__()
        self.token_id = token_id
        self.spread = spread
        self.size = size
        self.refresh_interval = refresh_interval
        self.max_position = max_position
        self._task: asyncio.Task[None] | None = None
        self._cycle_count: int = 0

    async def start(self) -> None:
        """Start the market making loop as a background asyncio task."""
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "MarketMakerKernel started: token=%s spread=%.4f size=%.0f",
            self.token_id[:20],
            self.spread,
            self.size,
        )

    async def stop(self) -> None:
        """Stop the market making loop and cancel all open orders for this kernel.

        Cancels the background task, awaits its completion, then asks the
        execution engine to cancel every outstanding order tagged with this
        kernel's name.
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Cancel all our open orders via the execution layer.
        if self.engine and self.engine.execution:
            self.engine.execution.cancel_all(kernel_name=self.name)

        logger.info(
            "MarketMakerKernel stopped after %d cycles", self._cycle_count
        )

    async def _run_loop(self) -> None:
        """Continuously refresh quotes at ``refresh_interval`` second intervals."""
        while True:
            try:
                await self._refresh_quotes()
                self._cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in market maker cycle")
            await asyncio.sleep(self.refresh_interval)

    async def _refresh_quotes(self) -> None:
        """Cancel stale orders and place a fresh bid/ask pair around the midpoint.

        Skips the cycle silently when market data or a midpoint price is not
        yet available.  Clamps prices to the [0.01, 0.99] binary market range.
        Respects ``max_position``: the buy side is skipped once the net
        position reaches the cap; the sell side is skipped when there is
        nothing to sell.
        """
        if not self.engine or not self.engine.market_data:
            logger.warning("No market data available — skipping cycle")
            return

        mid = self.engine.market_data.get_midpoint(self.token_id)
        if mid is None:
            logger.warning(
                "No midpoint for %s — skipping cycle", self.token_id[:20]
            )
            return

        # Cancel existing orders placed by this kernel before quoting fresh ones.
        if self.engine.execution:
            self.engine.execution.cancel_all(kernel_name=self.name)

        # Symmetric spread around mid, clamped to valid binary-market range.
        bid_price = max(0.01, min(0.99, round(mid - self.spread, 4)))
        ask_price = max(0.01, min(0.99, round(mid + self.spread, 4)))

        net_size: float = 0.0
        if self.engine.portfolio:
            position = self.engine.portfolio.get_position(self.token_id)
            net_size = position.size if position else 0.0

        if self.engine.execution and self.engine.orders:
            # Buy side — only quote when we have room to take on more position.
            if net_size < self.max_position:
                bid_order = self.engine.orders.create_order(
                    token_id=self.token_id,
                    side="BUY",
                    price=bid_price,
                    size=self.size,
                    kernel_name=self.name,
                )
                self.engine.execution.submit_order(bid_order)

            # Sell side — only quote when we hold inventory to deliver.
            if net_size > 0:
                sell_size = min(self.size, net_size)
                ask_order = self.engine.orders.create_order(
                    token_id=self.token_id,
                    side="SELL",
                    price=ask_price,
                    size=sell_size,
                    kernel_name=self.name,
                )
                self.engine.execution.submit_order(ask_order)

        logger.debug(
            "MM cycle: mid=%.4f bid=%.4f ask=%.4f net_pos=%.0f",
            mid,
            bid_price,
            ask_price,
            net_size,
        )

    def get_status(self) -> dict[str, Any]:
        """Return a dict summarising the kernel's current state.

        Returns:
            Base status dict extended with market-maker-specific fields:
            ``token_id``, ``spread``, ``size``, ``refresh_interval``,
            ``max_position``, and ``cycle_count``.
        """
        base = super().get_status()
        base.update(
            {
                "token_id": self.token_id,
                "spread": self.spread,
                "size": self.size,
                "refresh_interval": self.refresh_interval,
                "max_position": self.max_position,
                "cycle_count": self._cycle_count,
            }
        )
        return base
