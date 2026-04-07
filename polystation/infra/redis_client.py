"""Optional Redis integration for durability and cross-process messaging."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.info("redis package not installed — Redis features disabled")


class RedisManager:
    """Optional Redis client. All methods are no-ops when Redis is unavailable or disconnected."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self.connected = False
        self._client: Any = None

        if not REDIS_AVAILABLE:
            logger.info("Redis not available (package not installed)")
            return

        try:
            self._client = redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
            self.connected = True
            logger.info("Redis connected: %s", redis_url)
        except Exception as exc:
            logger.warning("Redis connection failed (%s) — running without Redis", exc)
            self._client = None

    def publish_trade(self, trade_data: dict[str, Any]) -> None:
        """Push a trade record to the trades list.

        Args:
            trade_data: Dict containing trade details to persist.
        """
        if not self.connected or not self._client:
            return
        try:
            self._client.lpush("polystation:trades", json.dumps(trade_data, default=str))
            self._client.ltrim("polystation:trades", 0, 9999)
        except Exception as exc:
            logger.warning("Redis publish_trade failed: %s", exc)

    def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event to the events PubSub channel.

        Args:
            event_type: String type identifier for the event.
            data: Additional event payload to merge into the message.
        """
        if not self.connected or not self._client:
            return
        try:
            payload = json.dumps({"type": event_type, "ts": time.time(), **data}, default=str)
            self._client.publish("polystation:events", payload)
        except Exception as exc:
            logger.warning("Redis publish_event failed: %s", exc)

    def snapshot_portfolio(self, portfolio_data: dict[str, Any]) -> None:
        """Store a portfolio snapshot with 60s TTL.

        Args:
            portfolio_data: Portfolio state dict to snapshot.
        """
        if not self.connected or not self._client:
            return
        try:
            self._client.setex(
                "polystation:portfolio:snapshot",
                60,
                json.dumps(portfolio_data, default=str),
            )
        except Exception as exc:
            logger.warning("Redis snapshot_portfolio failed: %s", exc)

    def snapshot_positions(self, positions_data: dict[str, Any]) -> None:
        """Store positions snapshot with 60s TTL.

        Args:
            positions_data: Positions state dict to snapshot.
        """
        if not self.connected or not self._client:
            return
        try:
            self._client.setex(
                "polystation:positions:snapshot",
                60,
                json.dumps(positions_data, default=str),
            )
        except Exception as exc:
            logger.warning("Redis snapshot_positions failed: %s", exc)

    def heartbeat(self) -> None:
        """Set a heartbeat key with 15s TTL."""
        if not self.connected or not self._client:
            return
        try:
            self._client.setex("polystation:heartbeat", 15, str(time.time()))
        except Exception as exc:
            logger.warning("Redis heartbeat failed: %s", exc)

    def dead_letter(self, trade_data: dict[str, Any], reason: str) -> None:
        """Push a failed trade to the dead-letter queue.

        Args:
            trade_data: The trade dict that failed processing.
            reason: Human-readable description of the failure reason.
        """
        if not self.connected or not self._client:
            return
        try:
            entry = {"timestamp": time.time(), "reason": reason, **trade_data}
            self._client.lpush("polystation:dead_letter", json.dumps(entry, default=str))
            self._client.ltrim("polystation:dead_letter", 0, 999)
        except Exception as exc:
            logger.warning("Redis dead_letter failed: %s", exc)

    def get_trade_history(self, count: int = 50) -> list[dict[str, Any]]:
        """Read recent trades from Redis.

        Args:
            count: Maximum number of recent trades to return.

        Returns:
            List of trade dicts, most recent first.  Empty list when Redis is
            unavailable or an error occurs.
        """
        if not self.connected or not self._client:
            return []
        try:
            raw = self._client.lrange("polystation:trades", 0, count - 1)
            return [json.loads(r) for r in raw]
        except Exception:
            return []

    def get_portfolio_snapshot(self) -> dict[str, Any] | None:
        """Read the latest portfolio snapshot.

        Returns:
            Portfolio dict from the last snapshot, or None when unavailable.
        """
        if not self.connected or not self._client:
            return None
        try:
            raw = self._client.get("polystation:portfolio:snapshot")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def get_queue_depth(self, queue_name: str) -> int:
        """Get the length of a Redis list.

        Args:
            queue_name: Full Redis key of the list to measure.

        Returns:
            Number of items in the list, or 0 when Redis is unavailable.
        """
        if not self.connected or not self._client:
            return 0
        try:
            return self._client.llen(queue_name) or 0
        except Exception:
            return 0

    def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self.connected = False
