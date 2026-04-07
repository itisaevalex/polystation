"""Tests for polystation.infra.redis_client — RedisManager graceful degradation and live round-trips."""
from __future__ import annotations

import pytest

from polystation.infra.redis_client import REDIS_AVAILABLE, RedisManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_redis_running() -> bool:
    """Return True if a local Redis instance is reachable."""
    if not REDIS_AVAILABLE:
        return False
    try:
        import redis

        client = redis.from_url("redis://localhost:6379/0", decode_responses=True)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


REDIS_RUNNING = _is_redis_running()


# ---------------------------------------------------------------------------
# Graceful degradation — Redis unavailable (bad URL or package missing)
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """RedisManager must be safe to use even when Redis is not reachable."""

    def _offline_manager(self) -> RedisManager:
        """Return a manager that is guaranteed not to connect."""
        return RedisManager(redis_url="redis://127.0.0.1:19999/0")  # unreachable port

    def test_connected_is_false_when_unreachable(self) -> None:
        rm = self._offline_manager()
        assert rm.connected is False

    def test_publish_trade_noop(self) -> None:
        rm = self._offline_manager()
        rm.publish_trade({"token_id": "abc", "side": "BUY", "price": 0.5, "size": 10})

    def test_publish_event_noop(self) -> None:
        rm = self._offline_manager()
        rm.publish_event("test.event", {"detail": "x"})

    def test_snapshot_portfolio_noop(self) -> None:
        rm = self._offline_manager()
        rm.snapshot_portfolio({"realized_pnl": 42.0})

    def test_snapshot_positions_noop(self) -> None:
        rm = self._offline_manager()
        rm.snapshot_positions({"position_count": 3})

    def test_heartbeat_noop(self) -> None:
        rm = self._offline_manager()
        rm.heartbeat()

    def test_dead_letter_noop(self) -> None:
        rm = self._offline_manager()
        rm.dead_letter({"token_id": "abc"}, reason="test failure")

    def test_get_trade_history_returns_empty_list(self) -> None:
        rm = self._offline_manager()
        result = rm.get_trade_history()
        assert result == []

    def test_get_trade_history_with_count_returns_empty_list(self) -> None:
        rm = self._offline_manager()
        result = rm.get_trade_history(count=100)
        assert result == []

    def test_get_portfolio_snapshot_returns_none(self) -> None:
        rm = self._offline_manager()
        result = rm.get_portfolio_snapshot()
        assert result is None

    def test_get_queue_depth_returns_zero(self) -> None:
        rm = self._offline_manager()
        result = rm.get_queue_depth("polystation:trades")
        assert result == 0

    def test_close_does_not_raise(self) -> None:
        rm = self._offline_manager()
        rm.close()  # should be a no-op

    def test_close_sets_connected_false(self) -> None:
        rm = self._offline_manager()
        rm.close()
        assert rm.connected is False

    def test_double_close_does_not_raise(self) -> None:
        rm = self._offline_manager()
        rm.close()
        rm.close()


# ---------------------------------------------------------------------------
# Live round-trip tests — only when Redis is actually running
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not REDIS_RUNNING, reason="Local Redis not available")
class TestLiveRedis:
    """Integration tests that require a running Redis instance on localhost:6379."""

    def _manager(self) -> RedisManager:
        rm = RedisManager(redis_url="redis://localhost:6379/0")
        assert rm.connected, "Expected Redis to be connected for live tests"
        return rm

    def _flush_keys(self, rm: RedisManager) -> None:
        """Remove test keys to avoid cross-test pollution."""
        try:
            rm._client.delete(
                "polystation:trades",
                "polystation:portfolio:snapshot",
                "polystation:heartbeat",
            )
        except Exception:
            pass

    def test_connected_is_true(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)
        assert rm.connected is True
        rm.close()

    def test_publish_trade_and_get_trade_history_round_trip(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)

        trade = {"token_id": "tok123", "side": "BUY", "price": 0.75, "size": 20}
        rm.publish_trade(trade)

        history = rm.get_trade_history(count=1)
        assert len(history) == 1
        assert history[0]["token_id"] == "tok123"
        assert history[0]["side"] == "BUY"
        rm.close()

    def test_publish_multiple_trades_order(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)

        rm.publish_trade({"token_id": "first", "side": "BUY", "price": 0.5, "size": 1})
        rm.publish_trade({"token_id": "second", "side": "SELL", "price": 0.6, "size": 2})

        history = rm.get_trade_history(count=2)
        assert len(history) == 2
        # lpush means most recent is index 0
        assert history[0]["token_id"] == "second"
        assert history[1]["token_id"] == "first"
        rm.close()

    def test_heartbeat_sets_key(self) -> None:
        import time

        rm = self._manager()
        self._flush_keys(rm)

        rm.heartbeat()

        raw = rm._client.get("polystation:heartbeat")
        assert raw is not None
        ts = float(raw)
        assert abs(ts - time.time()) < 5.0  # within 5 seconds
        rm.close()

    def test_heartbeat_ttl_is_set(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)

        rm.heartbeat()
        ttl = rm._client.ttl("polystation:heartbeat")
        assert 0 < ttl <= 15
        rm.close()

    def test_snapshot_portfolio_and_get_round_trip(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)

        data = {"realized_pnl": 123.45, "total_pnl": 200.0, "position_count": 5}
        rm.snapshot_portfolio(data)

        result = rm.get_portfolio_snapshot()
        assert result is not None
        assert result["realized_pnl"] == pytest.approx(123.45)
        assert result["position_count"] == 5
        rm.close()

    def test_get_portfolio_snapshot_returns_none_when_absent(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)

        result = rm.get_portfolio_snapshot()
        assert result is None
        rm.close()

    def test_get_queue_depth(self) -> None:
        rm = self._manager()
        self._flush_keys(rm)

        assert rm.get_queue_depth("polystation:trades") == 0
        rm.publish_trade({"token_id": "x", "side": "BUY", "price": 0.5, "size": 1})
        rm.publish_trade({"token_id": "y", "side": "BUY", "price": 0.5, "size": 1})
        assert rm.get_queue_depth("polystation:trades") == 2
        rm.close()

    def test_dead_letter_stores_entry(self) -> None:
        rm = self._manager()
        try:
            rm._client.delete("polystation:dead_letter")
        except Exception:
            pass

        rm.dead_letter({"token_id": "bad_tok"}, reason="price out of range")

        depth = rm.get_queue_depth("polystation:dead_letter")
        assert depth == 1
        raw = rm._client.lrange("polystation:dead_letter", 0, 0)
        import json

        entry = json.loads(raw[0])
        assert entry["reason"] == "price out of range"
        assert entry["token_id"] == "bad_tok"
        rm.close()

    def test_close_sets_connected_false(self) -> None:
        rm = self._manager()
        assert rm.connected is True
        rm.close()
        assert rm.connected is False

    def test_methods_are_noop_after_close(self) -> None:
        rm = self._manager()
        rm.close()

        # None of these should raise after close
        rm.publish_trade({"token_id": "x"})
        rm.heartbeat()
        assert rm.get_trade_history() == []
        assert rm.get_portfolio_snapshot() is None
        assert rm.get_queue_depth("polystation:trades") == 0
