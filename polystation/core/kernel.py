"""Base class for all trading strategy kernels."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from polystation.core.engine import TradingEngine

logger = logging.getLogger(__name__)

KernelStatus = Literal["stopped", "starting", "running", "stopping", "error"]


class Kernel(ABC):
    """Abstract base class for a pluggable trading strategy.

    Each kernel is an independent trading agent that receives access to
    the shared TradingEngine for market data, order execution, and
    portfolio information.

    Subclasses must implement start(), stop(), and get_status().
    """

    name: str = "unnamed"

    def __init__(self) -> None:
        self.status: KernelStatus = "stopped"
        self.engine: TradingEngine | None = None
        self._error: str | None = None

    async def initialize(self, engine: TradingEngine) -> None:
        """Called by the engine before start(). Stores engine reference."""
        self.engine = engine
        self.status = "starting"
        logger.info("Kernel '%s' initializing", self.name)

    @abstractmethod
    async def start(self) -> None:
        """Start the kernel's trading logic. Called after initialize()."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the kernel. Cancel pending work."""
        ...

    def get_status(self) -> dict[str, Any]:
        """Return kernel status as a serializable dict."""
        return {
            "name": self.name,
            "status": self.status,
            "error": self._error,
        }

    def set_error(self, error: str) -> None:
        """Mark kernel as errored with a message."""
        self.status = "error"
        self._error = error
        logger.error("Kernel '%s' error: %s", self.name, error)
