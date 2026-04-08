"""Binance exchange adapter — REST + WebSocket for spot and USDM futures."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from polystation.exchanges.base import (
    Exchange,
    ExchangeOrderBook,
    ExchangePosition,
    OrderResult,
    OrderType,
)

logger = logging.getLogger(__name__)

BINANCE_REST = "https://api.binance.com"
BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_WS = "wss://stream.binance.com:9443/ws"

# Map OrderType values to Binance timeInForce strings.
_TIF_MAP: dict[OrderType, str] = {
    OrderType.GTC: "GTC",
    OrderType.FOK: "FOK",
    OrderType.IOC: "IOC",
    OrderType.GTD: "GTC",  # Binance has no GTD — fall back to GTC
}


class BinanceExchange(Exchange):
    """Binance exchange adapter for spot and USDM futures.

    Uses the REST API via :mod:`aiohttp`.  No ``python-binance`` dependency
    required.  Authenticated endpoints are signed with HMAC-SHA256.

    Args:
        api_key: Binance API key.
        api_secret: Binance API secret used for HMAC signing.
        futures: When True, routes all calls to the USDM Futures (``fapi``)
            endpoint instead of the spot endpoint.
        testnet: When True, connects to the respective Binance testnet.
    """

    name = "binance"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        futures: bool = False,
        testnet: bool = False,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._futures = futures
        self._testnet = testnet
        self._session: aiohttp.ClientSession | None = None

        if futures:
            self._base_url = (
                "https://testnet.binancefuture.com" if testnet else BINANCE_FAPI
            )
        else:
            self._base_url = (
                "https://testnet.binance.vision" if testnet else BINANCE_REST
            )

    async def connect(self) -> None:
        """Create the underlying :class:`aiohttp.ClientSession`."""
        self._session = aiohttp.ClientSession()
        logger.info(
            "BinanceExchange connected (futures=%s, testnet=%s)",
            self._futures,
            self._testnet,
        )

    async def disconnect(self) -> None:
        """Close the :class:`aiohttp.ClientSession` and release resources."""
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("BinanceExchange disconnected")

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Append a ``timestamp`` and HMAC-SHA256 ``signature`` to *params*.

        Mutates and returns *params* in-place for chaining convenience.

        Args:
            params: Request parameters dict to sign.

        Returns:
            The same dict with ``timestamp`` and ``signature`` added.
        """
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self._api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    def _headers(self) -> dict[str, str]:
        """Return HTTP headers required for authenticated Binance requests.

        Returns:
            Dict containing the ``X-MBX-APIKEY`` header.
        """
        return {"X-MBX-APIKEY": self._api_key}

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        """Perform a GET request against the Binance REST API.

        Args:
            path: URL path relative to the base URL.
            params: Optional query parameters.
            signed: When True, adds a timestamp + HMAC signature.

        Returns:
            Decoded JSON response body.

        Raises:
            ConnectionError: When the session has not been opened.
        """
        if not self._session:
            raise ConnectionError("Not connected to Binance")
        p: dict[str, Any] = params or {}
        if signed:
            p = self._sign(p)
        url = f"{self._base_url}{path}"
        async with self._session.get(url, params=p, headers=self._headers()) as resp:
            return await resp.json()

    async def _post(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Perform a signed POST request against the Binance REST API.

        Args:
            path: URL path relative to the base URL.
            params: Optional query parameters (will be signed).

        Returns:
            Decoded JSON response body.

        Raises:
            ConnectionError: When the session has not been opened.
        """
        if not self._session:
            raise ConnectionError("Not connected to Binance")
        p = self._sign(params or {})
        url = f"{self._base_url}{path}"
        async with self._session.post(url, params=p, headers=self._headers()) as resp:
            return await resp.json()

    async def _delete(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Perform a signed DELETE request against the Binance REST API.

        Args:
            path: URL path relative to the base URL.
            params: Optional query parameters (will be signed).

        Returns:
            Decoded JSON response body.

        Raises:
            ConnectionError: When the session has not been opened.
        """
        if not self._session:
            raise ConnectionError("Not connected to Binance")
        p = self._sign(params or {})
        url = f"{self._base_url}{path}"
        async with self._session.delete(url, params=p, headers=self._headers()) as resp:
            return await resp.json()

    async def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
    ) -> OrderResult:
        """Submit a limit or market order.

        Args:
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``).
            side: ``"BUY"`` or ``"SELL"``.
            price: Limit price (ignored for market orders).
            size: Order quantity.
            order_type: Time-in-force; ``MARKET`` sends a market order.

        Returns:
            :class:`OrderResult` describing the submission outcome.
        """
        path = "/fapi/v1/order" if self._futures else "/api/v3/order"

        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "quantity": str(size),
        }

        if order_type == OrderType.MARKET:
            params["type"] = "MARKET"
        else:
            params["type"] = "LIMIT"
            params["price"] = str(price)
            params["timeInForce"] = _TIF_MAP.get(order_type, "GTC")

        try:
            result = await self._post(path, params)
            if "orderId" in result:
                return OrderResult(
                    order_id=str(result["orderId"]),
                    status=(
                        "accepted"
                        if result.get("status") in ("NEW", "PARTIALLY_FILLED")
                        else "filled"
                    ),
                    filled_price=float(
                        result.get("avgPrice", result.get("price", price))
                    ),
                    filled_size=float(result.get("executedQty", 0)),
                )
            return OrderResult(
                order_id="",
                status="rejected",
                error=result.get("msg", str(result)),
            )
        except Exception as exc:
            return OrderResult(order_id="", status="rejected", error=str(exc))

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order by its Binance-assigned ID.

        Note: Binance requires a ``symbol`` to cancel orders.  This method
        passes only the ``orderId``; callers that know the symbol should use
        :meth:`cancel_all_orders` scoped to that symbol instead.

        Args:
            order_id: Binance order identifier.

        Returns:
            True when the cancellation was accepted, False on error.
        """
        path = "/fapi/v1/order" if self._futures else "/api/v3/order"
        try:
            result = await self._delete(path, {"orderId": order_id})
            return "orderId" in result
        except Exception:
            return False

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """Cancel all open orders for a symbol.

        Binance requires a symbol — returns 0 immediately when none is given.

        Args:
            symbol: Trading pair symbol.  Required by Binance.

        Returns:
            Number of orders cancelled, or 0 on missing symbol / error.
        """
        if not symbol:
            return 0  # Binance always requires a symbol
        path = (
            "/fapi/v1/allOpenOrders" if self._futures else "/api/v3/openOrders"
        )
        try:
            result = await self._delete(path, {"symbol": symbol})
            return len(result) if isinstance(result, list) else 1
        except Exception:
            return 0

    async def get_orderbook(self, symbol: str) -> ExchangeOrderBook:
        """Fetch the current order book for a symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            :class:`ExchangeOrderBook` snapshot; empty book on error.
        """
        path = "/fapi/v1/depth" if self._futures else "/api/v3/depth"
        try:
            result = await self._get(path, {"symbol": symbol, "limit": 20})
            bids: list[tuple[float, float]] = [
                (float(b[0]), float(b[1])) for b in result.get("bids", [])
            ]
            asks: list[tuple[float, float]] = [
                (float(a[0]), float(a[1])) for a in result.get("asks", [])
            ]
            return ExchangeOrderBook(symbol=symbol, bids=bids, asks=asks)
        except Exception:
            return ExchangeOrderBook(symbol=symbol)

    async def get_positions(self) -> list[ExchangePosition]:
        """Return all open USDM futures positions.

        Spot mode always returns an empty list (spot has no positions endpoint).

        Returns:
            List of :class:`ExchangePosition`; empty on spot mode or error.
        """
        if not self._futures:
            return []  # Spot has no positions endpoint
        try:
            result = await self._get("/fapi/v2/positionRisk", signed=True)
            return [
                ExchangePosition(
                    symbol=p["symbol"],
                    side="LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                    size=abs(float(p["positionAmt"])),
                    avg_entry_price=float(p.get("entryPrice", 0)),
                    unrealized_pnl=float(p.get("unRealizedProfit", 0)),
                )
                for p in result
                if float(p.get("positionAmt", 0)) != 0
            ]
        except Exception:
            return []

    async def get_balance(self) -> dict[str, float]:
        """Return available balances keyed by asset.

        For futures, returns each asset's total balance.
        For spot, returns only assets with a positive free balance.

        Returns:
            Mapping of asset symbol to balance; empty dict on error.
        """
        try:
            if self._futures:
                result = await self._get("/fapi/v2/balance", signed=True)
                return {b["asset"]: float(b["balance"]) for b in result}
            else:
                result = await self._get("/api/v3/account", signed=True)
                return {
                    b["asset"]: float(b["free"])
                    for b in result.get("balances", [])
                    if float(b.get("free", 0)) > 0
                }
        except Exception:
            return {}

    async def get_midpoint(self, symbol: str) -> float | None:
        """Get the mid-market price for a symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            ``(best_bid + best_ask) / 2``, or None when unavailable.
        """
        path = (
            "/fapi/v1/ticker/bookTicker"
            if self._futures
            else "/api/v3/ticker/bookTicker"
        )
        try:
            result = await self._get(path, {"symbol": symbol})
            bid = float(result.get("bidPrice", 0))
            ask = float(result.get("askPrice", 0))
            if bid and ask:
                return (bid + ask) / 2
            return None
        except Exception:
            return None

    async def get_price(self, symbol: str, side: str) -> float | None:
        """Get the best executable price for the given side.

        Args:
            symbol: Trading pair symbol.
            side: ``"BUY"`` returns the best ask; ``"SELL"`` returns the best bid.

        Returns:
            Best price as a float, or None when zero / unavailable.
        """
        path = (
            "/fapi/v1/ticker/bookTicker"
            if self._futures
            else "/api/v3/ticker/bookTicker"
        )
        try:
            result = await self._get(path, {"symbol": symbol})
            if side.upper() == "BUY":
                return float(result.get("askPrice", 0)) or None
            return float(result.get("bidPrice", 0)) or None
        except Exception:
            return None

    async def health_check(self) -> bool:
        """Verify that the Binance REST API is reachable.

        Returns:
            True when the ping endpoint responds with an empty dict ``{}``.
        """
        path = "/fapi/v1/ping" if self._futures else "/api/v3/ping"
        try:
            result = await self._get(path)
            return isinstance(result, dict)  # Binance ping returns {}
        except Exception:
            return False
