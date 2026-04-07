"""Signal kernel — momentum/mean-reversion price signals."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, TYPE_CHECKING

from polystation.core.kernel import Kernel
from polystation.kernels import register

if TYPE_CHECKING:
    from polystation.core.engine import TradingEngine

logger = logging.getLogger(__name__)


@register
class SignalKernel(Kernel):
    """Price signal trading kernel.

    Tracks a rolling window of price samples and generates BUY/SELL signals
    based on either momentum or mean-reversion logic.

    Parameters:
        token_id: Token to trade.
        lookback: Number of price samples to keep for signal calculation.
        poll_interval: Seconds between price checks.
        size: Order size when a signal fires.
        strategy: ``"momentum"`` buys on rising prices and sells on falling
            ones; ``"mean_reversion"`` does the opposite.
        threshold: Minimum fractional price change required to trigger a
            signal (e.g. ``0.02`` = 2 %).
    """

    name = "signal"

    def __init__(
        self,
        token_id: str,
        lookback: int = 10,
        poll_interval: float = 30.0,
        size: float = 50,
        strategy: str = "momentum",
        threshold: float = 0.02,
    ) -> None:
        super().__init__()
        self.token_id = token_id
        self.lookback = lookback
        self.poll_interval = poll_interval
        self.size = size
        self.strategy = strategy
        self.threshold = threshold
        self._price_history: deque[float] = deque(maxlen=lookback)
        self._task: asyncio.Task[None] | None = None
        self._signals_fired: int = 0

    async def start(self) -> None:
        """Start the price-polling loop as a background asyncio task."""
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "SignalKernel started: token=%s strategy=%s lookback=%d threshold=%.4f",
            self.token_id[:20],
            self.strategy,
            self.lookback,
            self.threshold,
        )

    async def stop(self) -> None:
        """Stop the price-polling loop.

        Cancels the background task and awaits its completion before returning.
        """
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("SignalKernel stopped after %d signals", self._signals_fired)

    async def _run_loop(self) -> None:
        """Poll for price signals at ``poll_interval`` second intervals."""
        while True:
            try:
                await self._check_signal()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error in signal check")
            await asyncio.sleep(self.poll_interval)

    async def _check_signal(self) -> None:
        """Fetch the latest midpoint, update history, and fire an order on signal.

        Compares the oldest and newest prices in the rolling window.  A signal
        is emitted when the fractional change exceeds ``self.threshold``.
        The direction of the trade depends on ``self.strategy``:

        - ``"momentum"``: BUY when rising, SELL when falling.
        - ``"mean_reversion"``: BUY when dipping, SELL when spiking.
        """
        if not self.engine or not self.engine.market_data:
            return

        mid = self.engine.market_data.get_midpoint(self.token_id)
        if mid is None:
            return

        self._price_history.append(mid)

        # Need at least two data points to compute a change.
        if len(self._price_history) < 2:
            return

        oldest = self._price_history[0]
        newest = self._price_history[-1]

        if oldest == 0:
            return

        change = (newest - oldest) / oldest

        signal: str | None = None

        if self.strategy == "momentum":
            if change > self.threshold:
                signal = "BUY"
            elif change < -self.threshold:
                signal = "SELL"
        elif self.strategy == "mean_reversion":
            if change < -self.threshold:
                signal = "BUY"
            elif change > self.threshold:
                signal = "SELL"

        if signal and self.engine.execution and self.engine.orders:
            order = self.engine.orders.create_order(
                token_id=self.token_id,
                side=signal,
                price=mid,
                size=self.size,
                kernel_name=self.name,
            )
            self.engine.execution.submit_order(order)
            self._signals_fired += 1
            logger.info(
                "Signal fired: %s @ %.4f (change=%.4f, strategy=%s)",
                signal,
                mid,
                change,
                self.strategy,
            )

    def feed_price(self, price: float) -> bool:
        """Push a price sample and evaluate whether a signal fires.

        Provides a synchronous entry point for unit testing the signal logic
        without a running event loop or live market data.  The history window
        and signal counter are updated exactly as they would be in
        ``_check_signal()``.

        Args:
            price: Mid-price sample to add to the rolling history.

        Returns:
            True if the signal condition was met after adding *price*, False
            otherwise (including when the window is not yet full).
        """
        self._price_history.append(price)

        if len(self._price_history) < 2:
            return False

        oldest = self._price_history[0]
        newest = self._price_history[-1]

        if oldest == 0:
            return False

        change = (newest - oldest) / oldest

        signal: str | None = None
        if self.strategy == "momentum":
            if change > self.threshold:
                signal = "BUY"
            elif change < -self.threshold:
                signal = "SELL"
        elif self.strategy == "mean_reversion":
            if change < -self.threshold:
                signal = "BUY"
            elif change > self.threshold:
                signal = "SELL"

        if signal:
            self._signals_fired += 1
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        """Return a dict summarising the kernel's current state.

        Returns:
            Base status dict extended with signal-specific fields:
            ``token_id``, ``strategy``, ``lookback``, ``threshold``,
            ``size``, ``price_history_len``, ``latest_price``, and
            ``signals_fired``.
        """
        base = super().get_status()
        prices = list(self._price_history)
        base.update(
            {
                "token_id": self.token_id,
                "strategy": self.strategy,
                "lookback": self.lookback,
                "threshold": self.threshold,
                "size": self.size,
                "price_history_len": len(prices),
                "latest_price": prices[-1] if prices else None,
                "signals_fired": self._signals_fired,
            }
        )
        return base
