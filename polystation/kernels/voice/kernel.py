"""Voice recognition kernel — monitors audio streams for keywords and triggers trades."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, TYPE_CHECKING

from polystation.core.kernel import Kernel
from polystation.kernels import register

if TYPE_CHECKING:
    from polystation.core.engine import TradingEngine

logger = logging.getLogger(__name__)


@register
class VoiceKernel(Kernel):
    """Trading kernel that monitors audio streams for keywords.

    Wraps the existing StreamTrader (synchronous) in a background thread.
    Supports YouTube, Twitter/X, and radio audio sources.

    Parameters:
        source_type: One of ``"youtube"``, ``"twitter"``, or ``"radio"``.
        url: Stream URL to monitor.  When omitted the source falls back to
            the URL configured in ``config/sources/<source_type>.yaml``.
        debug: Enable DEBUG-level logging inside the StreamTrader loop.
    """

    name = "voice"

    def __init__(
        self,
        source_type: str = "youtube",
        url: str | None = None,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self.source_type = source_type
        self.url = url
        self.debug = debug
        self._thread: threading.Thread | None = None
        self._trader: Any = None  # StreamTrader instance

    async def start(self) -> None:
        """Start monitoring an audio stream in a background thread.

        Resolves the correct AudioSource subclass for ``self.source_type``,
        constructs a StreamTrader, and launches it in a daemon thread so
        that the blocking I/O loop does not stall the asyncio event loop.

        Raises:
            ValueError: If ``source_type`` is not one of the supported values.
        """
        from polystation.config import get_config
        from polystation.sources.base import StreamTrader
        from polystation.sources.youtube import YouTubeSource
        from polystation.sources.twitter import TwitterSource
        from polystation.sources.radio import RadioSource

        config = get_config()
        config.ensure_paths()

        source_map: dict[str, type] = {
            "youtube": YouTubeSource,
            "twitter": TwitterSource,
            "radio": RadioSource,
        }

        source_cls = source_map.get(self.source_type)
        if source_cls is None:
            raise ValueError(
                f"Unknown source type: {self.source_type!r}. "
                f"Available: {list(source_map.keys())}"
            )

        source = source_cls(self.url, config)
        self._trader = StreamTrader(source=source, config=config, debug=self.debug)

        # Run the blocking StreamTrader.start() in a background thread so the
        # asyncio event loop remains responsive.
        self._thread = threading.Thread(
            target=self._trader.start,
            name=f"voice-kernel-{self.source_type}",
            daemon=True,
        )
        self._thread.start()
        logger.info("VoiceKernel started: source=%s", self.source_type)

    async def stop(self) -> None:
        """Stop the audio stream monitoring.

        StreamTrader does not yet expose a clean stop signal, so we clear the
        references and rely on the daemon thread being reaped when the process
        exits.  A proper stop mechanism should be added to StreamTrader in a
        future iteration.

        Todo:
            Add an explicit stop-event to StreamTrader so the thread can be
            joined cleanly without waiting for process exit.
        """
        logger.info("VoiceKernel stopping (source=%s)", self.source_type)
        # TODO: send a stop-event to StreamTrader once it supports one.
        self._trader = None
        self._thread = None

    def get_status(self) -> dict[str, Any]:
        """Return a dict summarising the kernel's current state.

        Returns:
            Base status dict extended with voice-specific fields:
            ``source_type``, ``url``, and ``thread_alive``.
        """
        base = super().get_status()
        base.update(
            {
                "source_type": self.source_type,
                "url": self.url,
                "thread_alive": self._thread.is_alive() if self._thread else False,
            }
        )
        return base
