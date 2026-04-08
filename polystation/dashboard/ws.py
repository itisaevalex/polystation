"""WebSocket hub for real-time dashboard updates."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks all active WebSocket connections and fans out broadcasts.

    Supports per-client market subscriptions so that book_update messages are
    only delivered to clients that have subscribed to the relevant token.
    """

    def __init__(self) -> None:
        self.active: list[WebSocket] = []
        # Maps each WebSocket to the set of token_ids it has subscribed to
        self._subscriptions: dict[int, set[str]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        self._subscriptions[id(ws)] = set()
        logger.debug("WebSocket connected — %d active", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        self._subscriptions.pop(id(ws), None)
        logger.debug("WebSocket disconnected — %d active", len(self.active))

    def subscribe_market(self, ws: WebSocket, token_id: str) -> None:
        """Add *token_id* to the subscription set for *ws*.

        Args:
            ws: The WebSocket connection requesting the subscription.
            token_id: Market token identifier to subscribe to.
        """
        subs = self._subscriptions.get(id(ws))
        if subs is not None:
            subs.add(token_id)
            logger.debug("WS %d subscribed to %s", id(ws), token_id[:16])

    def unsubscribe_market(self, ws: WebSocket, token_id: str) -> None:
        """Remove *token_id* from the subscription set for *ws*.

        Args:
            ws: The WebSocket connection cancelling the subscription.
            token_id: Market token identifier to unsubscribe from.
        """
        subs = self._subscriptions.get(id(ws))
        if subs is not None:
            subs.discard(token_id)
            logger.debug("WS %d unsubscribed from %s", id(ws), token_id[:16])

    async def broadcast_book_update(self, token_id: str, data: dict) -> None:
        """Send a book_update message to every client subscribed to *token_id*.

        Removes stale connections silently so a single broken client does not
        prevent other subscribers from receiving the message.

        Args:
            token_id: Market token identifier that received the update.
            data: Serialisable order book data to send.
        """
        msg = json.dumps({"type": "book_update", "token_id": token_id, "data": data})
        dead: list[WebSocket] = []
        for ws in self.active[:]:
            subs = self._subscriptions.get(id(ws), set())
            if token_id not in subs:
                continue
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast(self, data: dict) -> None:
        """Send *data* as JSON text to every connected client.

        Removes stale connections silently so a single broken client does not
        prevent other subscribers from receiving the message.
        """
        msg = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in self.active[:]:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_personal(self, ws: WebSocket, data: dict) -> None:
        """Send *data* to a single connected client."""
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            self.disconnect(ws)


# Module-level singleton shared across all handlers
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Accept a WebSocket connection and keep it alive until disconnected.

    The server can push updates via ``manager.broadcast()``.  Clients may
    send subscription or ping messages; unrecognised messages are echoed back
    for diagnostics.

    Recognised message types:
    - ``ping``: responds with ``pong``.
    - ``subscribe``: legacy topic subscription acknowledgement.
    - ``subscribe_market``: subscribe to book_update events for a token_id.
    - ``unsubscribe_market``: cancel a market subscription.
    """
    await manager.connect(ws)
    # Send a welcome frame so the client knows the handshake succeeded
    await manager.send_personal(ws, {"type": "connected", "message": "Polystation WebSocket ready"})
    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                msg = {"raw": text}

            msg_type = msg.get("type", "unknown")

            if msg_type == "ping":
                await manager.send_personal(ws, {"type": "pong"})
            elif msg_type == "subscribe":
                # Acknowledge subscription — the server pushes all topics
                # unconditionally in this implementation; per-topic filtering
                # is left as a future enhancement.
                await manager.send_personal(ws, {"type": "subscribed", "topic": msg.get("topic")})
            elif msg_type == "subscribe_market":
                token_id = msg.get("token_id", "")
                if token_id:
                    manager.subscribe_market(ws, token_id)
                    await manager.send_personal(
                        ws, {"type": "subscribed_market", "token_id": token_id}
                    )
            elif msg_type == "unsubscribe_market":
                token_id = msg.get("token_id", "")
                if token_id:
                    manager.unsubscribe_market(ws, token_id)
                    await manager.send_personal(
                        ws, {"type": "unsubscribed_market", "token_id": token_id}
                    )
            else:
                # Echo unknown messages back for debugging
                await manager.send_personal(ws, {"type": "echo", "payload": msg})

    except WebSocketDisconnect:
        manager.disconnect(ws)
