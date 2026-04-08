"""Tests for polystation.exchanges.binance — structural / offline checks only.

No live Binance connection is established.  All tests verify adapter
construction, HMAC signing, URL selection, and default safe-return behaviour
without touching the network.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest

from polystation.exchanges.base import OrderType
from polystation.exchanges.binance import (
    BINANCE_FAPI,
    BINANCE_REST,
    BinanceExchange,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def spot_exchange() -> BinanceExchange:
    """Spot exchange on mainnet."""
    return BinanceExchange(api_key="apikey", api_secret="secret", futures=False, testnet=False)


@pytest.fixture()
def futures_exchange() -> BinanceExchange:
    """USDM futures exchange on mainnet."""
    return BinanceExchange(api_key="apikey", api_secret="secret", futures=True, testnet=False)


@pytest.fixture()
def spot_testnet_exchange() -> BinanceExchange:
    """Spot exchange on testnet."""
    return BinanceExchange(api_key="apikey", api_secret="secret", futures=False, testnet=True)


@pytest.fixture()
def futures_testnet_exchange() -> BinanceExchange:
    """USDM futures exchange on testnet."""
    return BinanceExchange(api_key="apikey", api_secret="secret", futures=True, testnet=True)


@pytest.fixture()
def anon_exchange() -> BinanceExchange:
    """BinanceExchange without credentials."""
    return BinanceExchange()


# ---------------------------------------------------------------------------
# Class-level attributes
# ---------------------------------------------------------------------------


class TestBinanceExchangeIdentity:
    def test_name_is_binance(self, spot_exchange: BinanceExchange) -> None:
        assert spot_exchange.name == "binance"

    def test_name_is_class_attribute(self) -> None:
        assert BinanceExchange.name == "binance"


# ---------------------------------------------------------------------------
# URL selection
# ---------------------------------------------------------------------------


class TestBinanceUrlSelection:
    def test_spot_mainnet_uses_rest_url(self, spot_exchange: BinanceExchange) -> None:
        assert spot_exchange._base_url == BINANCE_REST

    def test_futures_mainnet_uses_fapi_url(
        self, futures_exchange: BinanceExchange
    ) -> None:
        assert futures_exchange._base_url == BINANCE_FAPI

    def test_spot_testnet_uses_testnet_vision_url(
        self, spot_testnet_exchange: BinanceExchange
    ) -> None:
        assert spot_testnet_exchange._base_url == "https://testnet.binance.vision"

    def test_futures_testnet_uses_testnet_future_url(
        self, futures_testnet_exchange: BinanceExchange
    ) -> None:
        assert futures_testnet_exchange._base_url == "https://testnet.binancefuture.com"

    def test_futures_mainnet_url_contains_fapi(
        self, futures_exchange: BinanceExchange
    ) -> None:
        assert "fapi" in futures_exchange._base_url

    def test_spot_mainnet_url_contains_api_binance(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert "api.binance.com" in spot_exchange._base_url


# ---------------------------------------------------------------------------
# Initial state before connect()
# ---------------------------------------------------------------------------


class TestBinanceInitialState:
    def test_session_is_none_before_connect(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert spot_exchange._session is None

    def test_credentials_stored(self, spot_exchange: BinanceExchange) -> None:
        assert spot_exchange._api_key == "apikey"
        assert spot_exchange._api_secret == "secret"

    def test_futures_flag_stored(self, futures_exchange: BinanceExchange) -> None:
        assert futures_exchange._futures is True

    def test_spot_flag_stored(self, spot_exchange: BinanceExchange) -> None:
        assert spot_exchange._futures is False

    def test_testnet_flag_stored(self, spot_testnet_exchange: BinanceExchange) -> None:
        assert spot_testnet_exchange._testnet is True

    def test_anon_has_empty_credentials(self, anon_exchange: BinanceExchange) -> None:
        assert anon_exchange._api_key == ""
        assert anon_exchange._api_secret == ""


# ---------------------------------------------------------------------------
# HMAC signature
# ---------------------------------------------------------------------------


class TestBinanceSignature:
    def test_sign_adds_signature_key(self, spot_exchange: BinanceExchange) -> None:
        params: dict[str, Any] = {"symbol": "BTCUSDT"}
        signed = spot_exchange._sign(params)
        assert "signature" in signed

    def test_sign_adds_timestamp_key(self, spot_exchange: BinanceExchange) -> None:
        params: dict[str, Any] = {"symbol": "BTCUSDT"}
        signed = spot_exchange._sign(params)
        assert "timestamp" in signed

    def test_sign_signature_is_64_hex_chars(
        self, spot_exchange: BinanceExchange
    ) -> None:
        params: dict[str, Any] = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.01"}
        signed = spot_exchange._sign(params)
        assert len(signed["signature"]) == 64

    def test_sign_timestamp_is_recent_milliseconds(
        self, spot_exchange: BinanceExchange
    ) -> None:
        before = int(time.time() * 1000)
        params: dict[str, Any] = {}
        signed = spot_exchange._sign(params)
        after = int(time.time() * 1000)
        assert before <= signed["timestamp"] <= after

    def test_sign_signature_is_correct_hmac(
        self, spot_exchange: BinanceExchange
    ) -> None:
        """Manually verify the HMAC-SHA256 value matches what _sign produces."""
        params: dict[str, Any] = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.01"}
        signed = spot_exchange._sign(params.copy())
        # Re-derive signature from the signed params (minus the signature itself).
        params_for_query = {k: v for k, v in signed.items() if k != "signature"}
        query = urlencode(params_for_query)
        expected = hmac.new(
            spot_exchange._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        assert signed["signature"] == expected

    def test_sign_mutates_input_dict(self, spot_exchange: BinanceExchange) -> None:
        params: dict[str, Any] = {"symbol": "ETHUSDT"}
        result = spot_exchange._sign(params)
        # _sign returns the same object
        assert result is params


# ---------------------------------------------------------------------------
# Standalone HMAC test (as specified in the task)
# ---------------------------------------------------------------------------


def test_binance_signature() -> None:
    ex = BinanceExchange(api_key="test", api_secret="secret123")
    params: dict[str, Any] = {"symbol": "BTCUSDT", "side": "BUY", "quantity": "0.01"}
    signed = ex._sign(params)
    assert "signature" in signed
    assert "timestamp" in signed
    assert len(signed["signature"]) == 64  # SHA256 hex is 64 chars


# ---------------------------------------------------------------------------
# _headers
# ---------------------------------------------------------------------------


class TestBinanceHeaders:
    def test_headers_include_api_key(self, spot_exchange: BinanceExchange) -> None:
        headers = spot_exchange._headers()
        assert "X-MBX-APIKEY" in headers

    def test_headers_api_key_value_matches(
        self, spot_exchange: BinanceExchange
    ) -> None:
        headers = spot_exchange._headers()
        assert headers["X-MBX-APIKEY"] == "apikey"

    def test_headers_returns_dict(self, spot_exchange: BinanceExchange) -> None:
        assert isinstance(spot_exchange._headers(), dict)

    def test_anon_headers_have_empty_api_key(
        self, anon_exchange: BinanceExchange
    ) -> None:
        assert anon_exchange._headers()["X-MBX-APIKEY"] == ""


# ---------------------------------------------------------------------------
# health_check returns False when disconnected
# ---------------------------------------------------------------------------


class TestBinanceHealthCheckDisconnected:
    @pytest.mark.asyncio
    async def test_health_check_false_when_not_connected_spot(
        self, spot_exchange: BinanceExchange
    ) -> None:
        result = await spot_exchange.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_false_when_not_connected_futures(
        self, futures_exchange: BinanceExchange
    ) -> None:
        result = await futures_exchange.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_false_for_anon_exchange(
        self, anon_exchange: BinanceExchange
    ) -> None:
        result = await anon_exchange.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# Spot mode: get_positions returns empty list
# ---------------------------------------------------------------------------


class TestBinanceSpotNoPositions:
    @pytest.mark.asyncio
    async def test_get_positions_empty_for_spot(
        self, spot_exchange: BinanceExchange
    ) -> None:
        """Spot mode has no positions endpoint — must always return []."""
        result = await spot_exchange.get_positions()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_positions_empty_for_spot_testnet(
        self, spot_testnet_exchange: BinanceExchange
    ) -> None:
        result = await spot_testnet_exchange.get_positions()
        assert result == []


# ---------------------------------------------------------------------------
# Disconnected state returns safe defaults
# ---------------------------------------------------------------------------


class TestBinanceDisconnectedDefaults:
    @pytest.mark.asyncio
    async def test_cancel_order_returns_false(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert await spot_exchange.cancel_order("12345") is False

    @pytest.mark.asyncio
    async def test_cancel_all_orders_no_symbol_returns_zero(
        self, spot_exchange: BinanceExchange
    ) -> None:
        # No symbol provided — Binance always requires one
        assert await spot_exchange.cancel_all_orders() == 0

    @pytest.mark.asyncio
    async def test_cancel_all_orders_with_symbol_returns_zero_disconnected(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert await spot_exchange.cancel_all_orders("BTCUSDT") == 0

    @pytest.mark.asyncio
    async def test_get_balance_returns_empty_dict(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert await spot_exchange.get_balance() == {}

    @pytest.mark.asyncio
    async def test_get_midpoint_returns_none(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert await spot_exchange.get_midpoint("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_get_price_returns_none(
        self, spot_exchange: BinanceExchange
    ) -> None:
        assert await spot_exchange.get_price("BTCUSDT", "BUY") is None

    @pytest.mark.asyncio
    async def test_get_orderbook_returns_empty_book(
        self, spot_exchange: BinanceExchange
    ) -> None:
        book = await spot_exchange.get_orderbook("BTCUSDT")
        assert book.symbol == "BTCUSDT"
        assert book.bids == []
        assert book.asks == []

    @pytest.mark.asyncio
    async def test_place_order_returns_rejected(
        self, spot_exchange: BinanceExchange
    ) -> None:
        result = await spot_exchange.place_order(
            symbol="BTCUSDT", side="BUY", price=50000.0, size=0.001
        )
        assert result.status == "rejected"
        assert result.order_id == ""
        assert result.error is not None


# ---------------------------------------------------------------------------
# cancel_all_orders requires symbol
# ---------------------------------------------------------------------------


class TestBinanceCancelAllRequiresSymbol:
    @pytest.mark.asyncio
    async def test_cancel_all_without_symbol_always_zero(
        self, spot_exchange: BinanceExchange
    ) -> None:
        """Binance API requires a symbol — adapter must short-circuit when absent."""
        assert await spot_exchange.cancel_all_orders(symbol=None) == 0

    @pytest.mark.asyncio
    async def test_cancel_all_without_symbol_futures_zero(
        self, futures_exchange: BinanceExchange
    ) -> None:
        assert await futures_exchange.cancel_all_orders(symbol=None) == 0


# ---------------------------------------------------------------------------
# URL path selection for futures vs spot
# ---------------------------------------------------------------------------


class TestBinancePathSelection:
    """Verify futures and spot variants use the correct endpoint paths."""

    def _mock_session_for(
        self, exchange: BinanceExchange, response_body: Any
    ) -> None:
        """Attach a mock session that always returns *response_body*."""
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=response_body)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.delete = MagicMock(return_value=mock_resp)
        exchange._session = mock_session

    @pytest.mark.asyncio
    async def test_spot_ping_uses_api_v3_path(
        self, spot_exchange: BinanceExchange
    ) -> None:
        self._mock_session_for(spot_exchange, {})
        await spot_exchange.health_check()
        call_url: str = spot_exchange._session.get.call_args[0][0]  # type: ignore[union-attr]
        assert "/api/v3/ping" in call_url

    @pytest.mark.asyncio
    async def test_futures_ping_uses_fapi_v1_path(
        self, futures_exchange: BinanceExchange
    ) -> None:
        self._mock_session_for(futures_exchange, {})
        await futures_exchange.health_check()
        call_url: str = futures_exchange._session.get.call_args[0][0]  # type: ignore[union-attr]
        assert "/fapi/v1/ping" in call_url

    @pytest.mark.asyncio
    async def test_spot_orderbook_uses_api_v3_depth(
        self, spot_exchange: BinanceExchange
    ) -> None:
        self._mock_session_for(spot_exchange, {"bids": [], "asks": []})
        await spot_exchange.get_orderbook("BTCUSDT")
        call_url: str = spot_exchange._session.get.call_args[0][0]  # type: ignore[union-attr]
        assert "/api/v3/depth" in call_url

    @pytest.mark.asyncio
    async def test_futures_orderbook_uses_fapi_v1_depth(
        self, futures_exchange: BinanceExchange
    ) -> None:
        self._mock_session_for(futures_exchange, {"bids": [], "asks": []})
        await futures_exchange.get_orderbook("BTCUSDT")
        call_url: str = futures_exchange._session.get.call_args[0][0]  # type: ignore[union-attr]
        assert "/fapi/v1/depth" in call_url


# ---------------------------------------------------------------------------
# OrderResult mapping from Binance REST response
# ---------------------------------------------------------------------------


class TestBinanceOrderResultMapping:
    def _make_exchange_with_post_response(
        self, response: Any
    ) -> BinanceExchange:
        ex = BinanceExchange(api_key="k", api_secret="s", futures=False)
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value=response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        ex._session = mock_session
        return ex

    @pytest.mark.asyncio
    async def test_new_order_maps_to_accepted(self) -> None:
        ex = self._make_exchange_with_post_response({
            "orderId": 123,
            "status": "NEW",
            "avgPrice": "0",
            "price": "50000.0",
            "executedQty": "0",
        })
        result = await ex.place_order("BTCUSDT", "BUY", 50000.0, 0.001)
        assert result.status == "accepted"
        assert result.order_id == "123"

    @pytest.mark.asyncio
    async def test_filled_order_maps_to_filled(self) -> None:
        ex = self._make_exchange_with_post_response({
            "orderId": 456,
            "status": "FILLED",
            "avgPrice": "50100.0",
            "price": "50000.0",
            "executedQty": "0.001",
        })
        result = await ex.place_order("BTCUSDT", "BUY", 50000.0, 0.001)
        assert result.status == "filled"

    @pytest.mark.asyncio
    async def test_error_response_maps_to_rejected(self) -> None:
        ex = self._make_exchange_with_post_response({
            "code": -1100,
            "msg": "Illegal characters found in parameter",
        })
        result = await ex.place_order("BTCUSDT", "BUY", 50000.0, 0.001)
        assert result.status == "rejected"
        assert result.order_id == ""

    @pytest.mark.asyncio
    async def test_partially_filled_maps_to_accepted(self) -> None:
        ex = self._make_exchange_with_post_response({
            "orderId": 789,
            "status": "PARTIALLY_FILLED",
            "avgPrice": "50050.0",
            "price": "50000.0",
            "executedQty": "0.0005",
        })
        result = await ex.place_order("BTCUSDT", "BUY", 50000.0, 0.001)
        assert result.status == "accepted"


# ---------------------------------------------------------------------------
# Order type to timeInForce mapping
# ---------------------------------------------------------------------------


class TestBinanceOrderTypeMapping:
    @pytest.mark.asyncio
    async def test_gtc_order_type_sends_gtc(self) -> None:
        ex = BinanceExchange(api_key="k", api_secret="s")
        captured_params: list[dict] = []

        async def fake_post(path: str, params: dict | None = None) -> dict:
            captured_params.append(params or {})
            return {"orderId": 1, "status": "NEW", "avgPrice": "0",
                    "price": "100", "executedQty": "0"}

        ex._post = fake_post  # type: ignore[method-assign]
        await ex.place_order("BTCUSDT", "BUY", 100.0, 1.0, OrderType.GTC)
        assert captured_params[0].get("timeInForce") == "GTC"

    @pytest.mark.asyncio
    async def test_fok_order_type_sends_fok(self) -> None:
        ex = BinanceExchange(api_key="k", api_secret="s")
        captured_params: list[dict] = []

        async def fake_post(path: str, params: dict | None = None) -> dict:
            captured_params.append(params or {})
            return {"orderId": 1, "status": "NEW", "avgPrice": "0",
                    "price": "100", "executedQty": "0"}

        ex._post = fake_post  # type: ignore[method-assign]
        await ex.place_order("BTCUSDT", "BUY", 100.0, 1.0, OrderType.FOK)
        assert captured_params[0].get("timeInForce") == "FOK"

    @pytest.mark.asyncio
    async def test_ioc_order_type_sends_ioc(self) -> None:
        ex = BinanceExchange(api_key="k", api_secret="s")
        captured_params: list[dict] = []

        async def fake_post(path: str, params: dict | None = None) -> dict:
            captured_params.append(params or {})
            return {"orderId": 1, "status": "NEW", "avgPrice": "0",
                    "price": "100", "executedQty": "0"}

        ex._post = fake_post  # type: ignore[method-assign]
        await ex.place_order("BTCUSDT", "BUY", 100.0, 1.0, OrderType.IOC)
        assert captured_params[0].get("timeInForce") == "IOC"

    @pytest.mark.asyncio
    async def test_market_order_omits_price_and_tif(self) -> None:
        ex = BinanceExchange(api_key="k", api_secret="s")
        captured_params: list[dict] = []

        async def fake_post(path: str, params: dict | None = None) -> dict:
            captured_params.append(params or {})
            return {"orderId": 1, "status": "FILLED", "avgPrice": "50100",
                    "price": "0", "executedQty": "1.0"}

        ex._post = fake_post  # type: ignore[method-assign]
        await ex.place_order("BTCUSDT", "BUY", 50000.0, 1.0, OrderType.MARKET)
        assert captured_params[0].get("type") == "MARKET"
        assert "price" not in captured_params[0]
        assert "timeInForce" not in captured_params[0]
