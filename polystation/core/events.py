"""Simple async event bus for inter-component communication."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

Callback = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """Publish/subscribe event bus for trading engine components.

    Components publish events (e.g. "order.filled", "detection.keyword")
    and other components subscribe to react. All callbacks are async.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callback) -> None:
        """Register *callback* for *event*. Callback must be an async function."""
        self._subscribers[event].append(callback)
        logger.debug("Subscribed to '%s': %s", event, callback.__qualname__)

    def unsubscribe(self, event: str, callback: Callback) -> None:
        """Remove *callback* from *event* subscribers."""
        subs = self._subscribers.get(event, [])
        if callback in subs:
            subs.remove(callback)

    async def publish(self, event: str, **data: Any) -> None:
        """Fire *event* and await all subscriber callbacks with **data."""
        for cb in self._subscribers.get(event, []):
            try:
                await cb(**data)
            except Exception:
                logger.exception("Error in subscriber %s for event '%s'", cb.__qualname__, event)

    def publish_sync(self, event: str, **data: Any) -> None:
        """Fire event from synchronous code by scheduling on the running loop."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event, **data))
        except RuntimeError:
            logger.debug("No running event loop — skipping publish of '%s'", event)
