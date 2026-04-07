"""WebSocket hub for real-time dashboard updates."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks all active WebSocket connections and fans out broadcasts."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        logger.debug("WebSocket connected — %d active", len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        logger.debug("WebSocket disconnected — %d active", len(self.active))

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
            else:
                # Echo unknown messages back for debugging
                await manager.send_personal(ws, {"type": "echo", "payload": msg})

    except WebSocketDisconnect:
        manager.disconnect(ws)
