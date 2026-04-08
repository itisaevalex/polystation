"""Trading engine — manages kernel lifecycle and shared infrastructure."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from polystation.core.events import EventBus
from polystation.core.kernel import Kernel

logger = logging.getLogger(__name__)


class TradingEngine:
    """Central coordinator for the Polystation trading system.

    Manages:
    - Kernel lifecycle (register, start, stop)
    - Shared event bus for inter-component communication
    - Market data client (attached in Phase 2)
    - Portfolio tracking (attached in Phase 3)
    - Order execution (attached in Phase 3)
    """

    def __init__(self) -> None:
        self.events = EventBus()
        self.kernels: dict[str, Kernel] = {}
        self._running = False

        # Placeholders — attached in later phases
        self.market_data: Any = None
        self.portfolio: Any = None
        self.execution: Any = None
        self.exchanges: dict[str, Any] = {}  # name -> Exchange adapter
        self.db: Any = None  # StateDatabase — attached in persistence phase

    def register_exchange(self, exchange: Any) -> None:
        """Register an exchange adapter with the engine.

        Args:
            exchange: A connected :class:`~polystation.exchanges.base.Exchange`
                instance.  It is stored under ``exchange.name``.
        """
        self.exchanges[exchange.name] = exchange
        logger.info("Registered exchange: %s", exchange.name)

    def get_exchange(self, name: str) -> Any | None:
        """Look up a registered exchange by name.

        Args:
            name: Short exchange identifier (e.g. ``"polymarket"``).

        Returns:
            The registered exchange adapter, or None when not found.
        """
        return self.exchanges.get(name)

    def register_kernel(self, kernel: Kernel) -> None:
        """Register a kernel with the engine. Does not start it."""
        if kernel.name in self.kernels:
            raise ValueError(f"Kernel '{kernel.name}' is already registered")
        self.kernels[kernel.name] = kernel
        logger.info("Registered kernel: %s", kernel.name)

    async def start_kernel(self, name: str) -> None:
        """Initialize and start a registered kernel by name."""
        kernel = self.kernels.get(name)
        if kernel is None:
            raise KeyError(f"No kernel registered with name '{name}'")
        if kernel.status == "running":
            logger.warning("Kernel '%s' is already running", name)
            return

        try:
            await kernel.initialize(self)
            await kernel.start()
            kernel.status = "running"
            logger.info("Kernel '%s' started", name)
            await self.events.publish("kernel.started", name=name)
        except Exception as exc:
            kernel.set_error(str(exc))
            logger.exception("Failed to start kernel '%s'", name)
            raise

    async def stop_kernel(self, name: str) -> None:
        """Stop a running kernel by name."""
        kernel = self.kernels.get(name)
        if kernel is None:
            raise KeyError(f"No kernel registered with name '{name}'")
        if kernel.status != "running":
            logger.warning("Kernel '%s' is not running (status: %s)", name, kernel.status)
            return

        try:
            kernel.status = "stopping"
            await kernel.stop()
            kernel.status = "stopped"
            logger.info("Kernel '%s' stopped", name)
            await self.events.publish("kernel.stopped", name=name)
        except Exception as exc:
            kernel.set_error(str(exc))
            logger.exception("Error stopping kernel '%s'", name)

    async def start(self) -> None:
        """Start the engine (event loop). Kernels must be started individually."""
        self._running = True
        logger.info("TradingEngine started — %d kernels registered", len(self.kernels))
        await self.events.publish("engine.started")

    async def stop(self) -> None:
        """Stop all running kernels and shut down the engine."""
        logger.info("TradingEngine shutting down")
        running = [k for k in self.kernels.values() if k.status == "running"]
        for kernel in running:
            await self.stop_kernel(kernel.name)
        self._running = False
        await self.events.publish("engine.stopped")
        logger.info("TradingEngine stopped")

    def get_status(self) -> dict[str, Any]:
        """Return engine and kernel status summary."""
        return {
            "running": self._running,
            "kernels": {name: k.get_status() for name, k in self.kernels.items()},
        }
