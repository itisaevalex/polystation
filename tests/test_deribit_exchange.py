"""Tests for polystation.exchanges.deribit — structural / offline checks only.

No live Deribit connection is established in this suite.  All tests verify
adapter construction, default state, and the JSON-RPC message formatting
without touching the network.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polystation.exchanges.base import OrderType
from polystation.exchanges.deribit import (
    DERIBIT_WS_MAINNET,
    DERIBIT_WS_TESTNET,
    DeribitExchange,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def testnet_exchange() -> DeribitExchange:
    """DeribitExchange instance pointing at the testnet (default)."""
    return DeribitExchange(api_key="key", api_secret="secret", testnet=True)


@pytest.fixture()
def mainnet_exchange() -> DeribitExchange:
    """DeribitExchange instance pointing at mainnet."""
    return DeribitExchange(api_key="key", api_secret="secret", testnet=False)


@pytest.fixture()
def anon_exchange() -> DeribitExchange:
    """DeribitExchange instance without credentials."""
    return DeribitExchange()


# ---------------------------------------------------------------------------
# Class-level attributes
# ---------------------------------------------------------------------------


class TestDeribitExchangeIdentity:
    def test_name_is_deribit(self, testnet_exchange: DeribitExchange) -> None:
        assert testnet_exchange.name == "deribit"

    def test_name_is_class_attribute(self) -> None:
        assert DeribitExchange.name == "deribit"


# ---------------------------------------------------------------------------
# URL selection
# ---------------------------------------------------------------------------


class TestDeribitUrl:
    def test_testnet_uses_testnet_url(self, testnet_exchange: DeribitExchange) -> None:
        assert testnet_exchange._url == DERIBIT_WS_TESTNET

    def test_mainnet_uses_mainnet_url(self, mainnet_exchange: DeribitExchange) -> None:
        assert mainnet_exchange._url == DERIBIT_WS_MAINNET

    def test_testnet_url_contains_test_domain(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert "test.deribit.com" in testnet_exchange._url

    def test_mainnet_url_contains_www_domain(
        self, mainnet_exchange: DeribitExchange
    ) -> None:
        assert "www.deribit.com" in mainnet_exchange._url

    def test_default_is_testnet(self) -> None:
        ex = DeribitExchange()
        assert ex._url == DERIBIT_WS_TESTNET


# ---------------------------------------------------------------------------
# Initial state before connect()
# ---------------------------------------------------------------------------


class TestDeribitInitialState:
    def test_not_connected_before_connect(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert testnet_exchange._connected is False

    def test_ws_is_none_before_connect(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert testnet_exchange._ws is None

    def test_listen_task_is_none_before_connect(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert testnet_exchange._listen_task is None

    def test_pending_dict_is_empty_before_connect(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert testnet_exchange._pending == {}

    def test_request_id_starts_at_zero(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert testnet_exchange._request_id == 0

    def test_credentials_stored(self, testnet_exchange: DeribitExchange) -> None:
        assert testnet_exchange._api_key == "key"
        assert testnet_exchange._api_secret == "secret"

    def test_anon_exchange_has_empty_credentials(
        self, anon_exchange: DeribitExchange
    ) -> None:
        assert anon_exchange._api_key == ""
        assert anon_exchange._api_secret == ""


# ---------------------------------------------------------------------------
# health_check returns False when disconnected
# ---------------------------------------------------------------------------


class TestDeribitHealthCheckDisconnected:
    @pytest.mark.asyncio
    async def test_health_check_false_when_not_connected(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        result = await testnet_exchange.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_false_for_anon_exchange(
        self, anon_exchange: DeribitExchange
    ) -> None:
        result = await anon_exchange.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# Disconnected state returns safe defaults
# ---------------------------------------------------------------------------


class TestDeribitDisconnectedDefaults:
    @pytest.mark.asyncio
    async def test_cancel_order_returns_false(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert await testnet_exchange.cancel_order("ord-123") is False

    @pytest.mark.asyncio
    async def test_cancel_all_orders_returns_zero(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert await testnet_exchange.cancel_all_orders() == 0

    @pytest.mark.asyncio
    async def test_get_positions_returns_empty_list(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert await testnet_exchange.get_positions() == []

    @pytest.mark.asyncio
    async def test_get_balance_returns_empty_dict(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert await testnet_exchange.get_balance() == {}

    @pytest.mark.asyncio
    async def test_get_midpoint_returns_none(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert await testnet_exchange.get_midpoint("BTC-PERPETUAL") is None

    @pytest.mark.asyncio
    async def test_get_price_returns_none(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        assert await testnet_exchange.get_price("BTC-PERPETUAL", "BUY") is None

    @pytest.mark.asyncio
    async def test_get_orderbook_returns_empty_book(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        book = await testnet_exchange.get_orderbook("BTC-PERPETUAL")
        assert book.symbol == "BTC-PERPETUAL"
        assert book.bids == []
        assert book.asks == []

    @pytest.mark.asyncio
    async def test_place_order_returns_rejected(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        result = await testnet_exchange.place_order(
            symbol="BTC-PERPETUAL", side="BUY", price=50000.0, size=1.0
        )
        assert result.status == "rejected"
        assert result.order_id == ""
        assert result.error is not None


# ---------------------------------------------------------------------------
# JSON-RPC message format produced by _send
# ---------------------------------------------------------------------------


class TestDeribitSendMessageFormat:
    """Verify the JSON-RPC envelope structure without a real connection."""

    @pytest.mark.asyncio
    async def test_send_raises_connection_error_when_not_connected(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        with pytest.raises(ConnectionError, match="Not connected to Deribit"):
            await testnet_exchange._send("public/test")

    @pytest.mark.asyncio
    async def test_send_increments_request_id(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        """Each call to _send should increment _request_id by 1."""
        # Simulate a connected state with a mock WebSocket.
        mock_ws = AsyncMock()
        # The future will never be resolved — we only care about the send call.
        sent_messages: list[str] = []

        async def fake_send(msg: str) -> None:
            sent_messages.append(msg)
            # Manually resolve the pending future so _send returns.
            data = json.loads(msg)
            rid = data["id"]
            future = testnet_exchange._pending.get(rid)
            if future and not future.done():
                future.set_result({"version": "1.2.3"})

        mock_ws.send = fake_send
        testnet_exchange._ws = mock_ws
        testnet_exchange._connected = True

        await testnet_exchange._send("public/test", {})
        assert testnet_exchange._request_id == 1

        await testnet_exchange._send("public/test", {})
        assert testnet_exchange._request_id == 2

    @pytest.mark.asyncio
    async def test_send_produces_valid_jsonrpc_envelope(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        """_send must emit a JSON-RPC 2.0 object with id, method, and params."""
        captured: list[dict] = []

        async def fake_send(msg: str) -> None:
            data = json.loads(msg)
            captured.append(data)
            rid = data["id"]
            future = testnet_exchange._pending.get(rid)
            if future and not future.done():
                future.set_result({"version": "2.0.1"})

        mock_ws = AsyncMock()
        mock_ws.send = fake_send
        testnet_exchange._ws = mock_ws
        testnet_exchange._connected = True

        await testnet_exchange._send("public/test", {"key": "value"})

        assert len(captured) == 1
        envelope = captured[0]
        assert envelope["jsonrpc"] == "2.0"
        assert "id" in envelope
        assert envelope["method"] == "public/test"
        assert envelope["params"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_send_omits_params_when_none(
        self, testnet_exchange: DeribitExchange
    ) -> None:
        """When params is None, the 'params' key should be absent from the message."""
        captured: list[dict] = []

        async def fake_send(msg: str) -> None:
            data = json.loads(msg)
            captured.append(data)
            rid = data["id"]
            future = testnet_exchange._pending.get(rid)
            if future and not future.done():
                future.set_result({})

        mock_ws = AsyncMock()
        mock_ws.send = fake_send
        testnet_exchange._ws = mock_ws
        testnet_exchange._connected = True

        await testnet_exchange._send("public/test")
        assert "params" not in captured[0]


# ---------------------------------------------------------------------------
# place_order side routing
# ---------------------------------------------------------------------------


class TestDeribitPlaceOrderRouting:
    """Verify that BUY/SELL maps to the correct Deribit method."""

    def _make_connected_exchange(self) -> tuple[DeribitExchange, list[str]]:
        ex = DeribitExchange(api_key="k", api_secret="s", testnet=True)
        methods_called: list[str] = []

        async def fake_send(
            method: str, params: dict | None = None
        ) -> dict:
            methods_called.append(method)
            return {
                "order": {
                    "order_id": "dbt-1",
                    "order_state": "open",
                    "average_price": 50000.0,
                    "filled_amount": 0.0,
                }
            }

        ex._send = fake_send  # type: ignore[method-assign]
        return ex, methods_called

    @pytest.mark.asyncio
    async def test_buy_uses_private_buy(self) -> None:
        ex, methods = self._make_connected_exchange()
        await ex.place_order("BTC-PERPETUAL", "BUY", 50000.0, 1.0)
        assert methods[0] == "private/buy"

    @pytest.mark.asyncio
    async def test_sell_uses_private_sell(self) -> None:
        ex, methods = self._make_connected_exchange()
        await ex.place_order("BTC-PERPETUAL", "SELL", 50000.0, 1.0)
        assert methods[0] == "private/sell"

    @pytest.mark.asyncio
    async def test_buy_case_insensitive(self) -> None:
        ex, methods = self._make_connected_exchange()
        await ex.place_order("BTC-PERPETUAL", "buy", 50000.0, 1.0)
        assert methods[0] == "private/buy"

    @pytest.mark.asyncio
    async def test_market_order_omits_price_param(self) -> None:
        ex = DeribitExchange(api_key="k", api_secret="s", testnet=True)
        received_params: list[dict] = []

        async def fake_send(method: str, params: dict | None = None) -> dict:
            received_params.append(params or {})
            return {
                "order": {
                    "order_id": "mkt-1",
                    "order_state": "open",
                    "average_price": 50100.0,
                    "filled_amount": 1.0,
                }
            }

        ex._send = fake_send  # type: ignore[method-assign]
        await ex.place_order(
            "BTC-PERPETUAL", "BUY", 50000.0, 1.0, order_type=OrderType.MARKET
        )
        assert received_params[0].get("type") == "market"
        assert "price" not in received_params[0]


# ---------------------------------------------------------------------------
# OrderResult mapping
# ---------------------------------------------------------------------------


class TestDeribitOrderResultMapping:
    @pytest.mark.asyncio
    async def test_open_order_state_maps_to_accepted(self) -> None:
        ex = DeribitExchange()

        async def fake_send(method: str, params: dict | None = None) -> dict:
            return {
                "order": {
                    "order_id": "dbt-42",
                    "order_state": "open",
                    "average_price": 50000.0,
                    "filled_amount": 0.0,
                }
            }

        ex._send = fake_send  # type: ignore[method-assign]
        result = await ex.place_order("BTC-PERPETUAL", "BUY", 50000.0, 1.0)
        assert result.status == "accepted"
        assert result.order_id == "dbt-42"

    @pytest.mark.asyncio
    async def test_non_open_order_state_maps_to_filled(self) -> None:
        ex = DeribitExchange()

        async def fake_send(method: str, params: dict | None = None) -> dict:
            return {
                "order": {
                    "order_id": "dbt-99",
                    "order_state": "filled",
                    "average_price": 50100.0,
                    "filled_amount": 1.0,
                }
            }

        ex._send = fake_send  # type: ignore[method-assign]
        result = await ex.place_order("BTC-PERPETUAL", "BUY", 50000.0, 1.0)
        assert result.status == "filled"

    @pytest.mark.asyncio
    async def test_exception_produces_rejected_result(self) -> None:
        ex = DeribitExchange()

        async def fake_send(method: str, params: dict | None = None) -> dict:
            raise RuntimeError("order rejected by exchange")

        ex._send = fake_send  # type: ignore[method-assign]
        result = await ex.place_order("BTC-PERPETUAL", "BUY", 50000.0, 1.0)
        assert result.status == "rejected"
        assert "order rejected by exchange" in (result.error or "")
