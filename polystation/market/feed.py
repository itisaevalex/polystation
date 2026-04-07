"""Real-time order book feed over WebSocket with automatic reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets

logger = logging.getLogger(__name__)

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
PING_INTERVAL = 10  # seconds — mitigates the known silent-freeze bug (#292)
RECONNECT_DELAYS = [1, 2, 4, 8, 15, 30]  # exponential backoff, caps at 30 s

Callback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class MarketFeed:
    """WebSocket feed for real-time Polymarket order book updates.

    Sends a WebSocket PING every 10 s to work around the known silent-freeze
    bug (#292). Reconnects with exponential backoff on any disconnection.
    """

    def __init__(self, url: str = WS_URL) -> None:
        self.url = url
        self._subscriptions: set[str] = set()
        self._callbacks: list[Callback] = []
        self._ws: Any = None
        self._running = False
        self._reconnect_attempt = 0

    def on_message(self, callback: Callback) -> None:
        """Register an async callback invoked for every incoming message."""
        self._callbacks.append(callback)

    def subscribe(self, token_id: str) -> None:
        """Queue *token_id* for subscription on the next (re)connect."""
        self._subscriptions.add(token_id)

    def unsubscribe(self, token_id: str) -> None:
        """Remove *token_id* from the subscription set."""
        self._subscriptions.discard(token_id)

    async def start(self) -> None:
        """Run the feed indefinitely, reconnecting on any error."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as exc:
                if not self._running:
                    break
                delay = RECONNECT_DELAYS[min(self._reconnect_attempt, len(RECONNECT_DELAYS) - 1)]
                logger.warning("Feed disconnected (%s), reconnecting in %ds...", exc, delay)
                self._reconnect_attempt += 1
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Signal the feed to stop and close the WebSocket."""
        self._running = False
        if self._ws is not None:
            await self._ws.close()

    async def _connect_and_listen(self) -> None:
        """Open the WebSocket, send subscriptions, then consume messages."""
        async with websockets.connect(self.url) as ws:
            self._ws = ws
            self._reconnect_attempt = 0
            logger.info("WebSocket connected to %s", self.url)

            for token_id in self._subscriptions:
                msg = json.dumps({"type": "subscribe", "channel": "market", "assets_id": token_id})
                await ws.send(msg)
                logger.debug("Subscribed to token %s", token_id)

            ping_task = asyncio.create_task(self._ping_loop(ws))
            try:
                async for raw_msg in ws:
                    try:
                        data: dict[str, Any] = json.loads(raw_msg)
                        for cb in self._callbacks:
                            await cb(data)
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON message received: %s", raw_msg[:100])
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

    async def _ping_loop(self, ws: Any) -> None:
        """Send periodic WebSocket PINGs to keep the connection alive."""
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                await ws.ping()
            except Exception:
                break  # connection lost; outer loop will reconnect
