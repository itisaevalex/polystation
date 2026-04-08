"""Deribit exchange adapter — WebSocket-first API for BTC perpetuals and futures."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import websockets

from polystation.exchanges.base import (
    Exchange,
    ExchangeOrderBook,
    ExchangePosition,
    OrderResult,
    OrderType,
)

logger = logging.getLogger(__name__)

DERIBIT_WS_MAINNET = "wss://www.deribit.com/ws/api/v2"
DERIBIT_WS_TESTNET = "wss://test.deribit.com/ws/api/v2"


class DeribitExchange(Exchange):
    """Deribit exchange adapter for perpetuals and futures.

    Uses WebSocket for all communication. Auth via API key + secret.
    Default instrument: BTC-PERPETUAL.

    Args:
        api_key: Deribit API key for authenticated endpoints.
        api_secret: Deribit API secret for authenticated endpoints.
        testnet: When True (default) connects to the Deribit testnet.
    """

    name = "deribit"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._testnet = testnet
        self._url = DERIBIT_WS_TESTNET if testnet else DERIBIT_WS_MAINNET
        self._ws: Any = None
        self._connected = False
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._listen_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Open the WebSocket connection and optionally authenticate.

        Sets ``_connected = True`` on success and starts the background
        listener task.  Authentication is only attempted when an API key
        is configured.
        """
        try:
            self._ws = await websockets.connect(self._url)
            self._connected = True
            self._listen_task = asyncio.create_task(self._listen_loop())

            if self._api_key:
                await self._authenticate()

            logger.info(
                "DeribitExchange connected (%s)",
                "testnet" if self._testnet else "mainnet",
            )
        except Exception as exc:
            logger.error("Deribit connection failed: %s", exc)
            self._connected = False

    async def disconnect(self) -> None:
        """Cancel the listener task and close the WebSocket."""
        self._connected = False
        if self._listen_task:
            self._listen_task.cancel()
        if self._ws:
            await self._ws.close()
        logger.info("DeribitExchange disconnected")

    async def _send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC 2.0 request and await the response.

        Args:
            method: Deribit API method name (e.g. ``"public/get_order_book"``).
            params: Optional request parameters.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            ConnectionError: When not connected.
            TimeoutError: When the exchange does not respond within 10 seconds.
            Exception: When the exchange returns a JSON-RPC error.
        """
        if not self._ws or not self._connected:
            raise ConnectionError("Not connected to Deribit")

        self._request_id += 1
        rid = self._request_id
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params:
            msg["params"] = params

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[rid] = future

        await self._ws.send(json.dumps(msg))

        try:
            result = await asyncio.wait_for(future, timeout=10.0)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise TimeoutError(f"Deribit request {method} timed out")

    async def _listen_loop(self) -> None:
        """Background coroutine that reads WebSocket frames and resolves pending futures.

        Runs until the connection is closed or an unexpected error is raised.
        Marks the exchange as disconnected when the loop exits.
        """
        try:
            async for raw in self._ws:
                try:
                    data: dict[str, Any] = json.loads(raw)
                    rid = data.get("id")
                    if rid and rid in self._pending:
                        future = self._pending.pop(rid)
                        if "error" in data:
                            future.set_exception(
                                Exception(
                                    data["error"].get("message", str(data["error"]))
                                )
                            )
                        else:
                            future.set_result(data.get("result", {}))
                except json.JSONDecodeError:
                    pass
        except Exception:
            self._connected = False

    async def _authenticate(self) -> None:
        """Exchange client credentials for an access token.

        Calls ``public/auth`` with ``client_credentials`` grant type.
        """
        result = await self._send(
            "public/auth",
            {
                "grant_type": "client_credentials",
                "client_id": self._api_key,
                "client_secret": self._api_secret,
            },
        )
        logger.info("Deribit authenticated: %s", result.get("token_type", ""))

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
            symbol: Instrument name (e.g. ``"BTC-PERPETUAL"``).
            side: ``"BUY"`` or ``"SELL"``.
            price: Limit price (ignored for market orders).
            size: Contract size.
            order_type: Time-in-force; ``MARKET`` sends a market order.

        Returns:
            :class:`OrderResult` describing the submission outcome.
        """
        method = "private/buy" if side.upper() == "BUY" else "private/sell"

        params: dict[str, Any] = {
            "instrument_name": symbol,
            "amount": size,
            "type": "limit",
            "price": price,
        }

        if order_type == OrderType.MARKET:
            params["type"] = "market"
            params.pop("price", None)

        try:
            result = await self._send(method, params)
            order_data: dict[str, Any] = result.get("order", {})
            return OrderResult(
                order_id=order_data.get("order_id", ""),
                status=(
                    "accepted"
                    if order_data.get("order_state") == "open"
                    else "filled"
                ),
                filled_price=order_data.get("average_price"),
                filled_size=order_data.get("filled_amount"),
            )
        except Exception as exc:
            return OrderResult(order_id="", status="rejected", error=str(exc))

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order.

        Args:
            order_id: Deribit-assigned order identifier.

        Returns:
            True on success, False on any error.
        """
        try:
            await self._send("private/cancel", {"order_id": order_id})
            return True
        except Exception:
            return False

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """Cancel all open orders, optionally scoped to one instrument.

        Args:
            symbol: When provided, only orders for this instrument are cancelled.

        Returns:
            Number of orders cancelled as reported by Deribit, or 0 on error.
        """
        try:
            params: dict[str, Any] = {}
            if symbol:
                params["instrument_name"] = symbol
            result = await self._send("private/cancel_all", params)
            return result if isinstance(result, int) else 0
        except Exception:
            return 0

    async def get_orderbook(self, symbol: str) -> ExchangeOrderBook:
        """Fetch the current order book for an instrument.

        Args:
            symbol: Instrument name.

        Returns:
            :class:`ExchangeOrderBook` snapshot; empty book on error.
        """
        try:
            result = await self._send(
                "public/get_order_book", {"instrument_name": symbol}
            )
            bids: list[tuple[float, float]] = [
                (b[0], b[1]) for b in result.get("bids", [])
            ]
            asks: list[tuple[float, float]] = [
                (a[0], a[1]) for a in result.get("asks", [])
            ]
            return ExchangeOrderBook(
                symbol=symbol,
                bids=bids,
                asks=asks,
                timestamp=str(result.get("timestamp", "")),
            )
        except Exception:
            return ExchangeOrderBook(symbol=symbol)

    async def get_positions(self) -> list[ExchangePosition]:
        """Return all open BTC positions.

        Returns:
            List of :class:`ExchangePosition` objects; empty list on error.
        """
        try:
            result = await self._send(
                "private/get_positions", {"currency": "BTC"}
            )
            return [
                ExchangePosition(
                    symbol=p["instrument_name"],
                    side="LONG" if p["direction"] == "buy" else "SHORT",
                    size=abs(p["size"]),
                    avg_entry_price=p.get("average_price", 0),
                    unrealized_pnl=p.get("floating_profit_loss", 0),
                )
                for p in result
            ]
        except Exception:
            return []

    async def get_balance(self) -> dict[str, float]:
        """Return BTC account balances.

        Returns:
            Mapping with keys ``"BTC"``, ``"available"``, and ``"margin"``;
            empty dict on error.
        """
        try:
            result = await self._send(
                "private/get_account_summary", {"currency": "BTC"}
            )
            return {
                "BTC": result.get("equity", 0),
                "available": result.get("available_funds", 0),
                "margin": result.get("margin_balance", 0),
            }
        except Exception:
            return {}

    async def get_midpoint(self, symbol: str) -> float | None:
        """Get the mid-market price for an instrument.

        Args:
            symbol: Instrument name.

        Returns:
            ``(best_bid + best_ask) / 2``, or None when unavailable.
        """
        try:
            result = await self._send(
                "public/get_order_book",
                {"instrument_name": symbol, "depth": 1},
            )
            best_bid: float = result.get("best_bid_price", 0)
            best_ask: float = result.get("best_ask_price", 0)
            if best_bid and best_ask:
                return (best_bid + best_ask) / 2
            return None
        except Exception:
            return None

    async def get_price(self, symbol: str, side: str) -> float | None:
        """Get the best executable price for the given side.

        Args:
            symbol: Instrument name.
            side: ``"BUY"`` returns the best ask; ``"SELL"`` returns the best bid.

        Returns:
            Best price, or None when unavailable.
        """
        try:
            result = await self._send(
                "public/get_order_book",
                {"instrument_name": symbol, "depth": 1},
            )
            if side.upper() == "BUY":
                return result.get("best_ask_price")
            return result.get("best_bid_price")
        except Exception:
            return None

    async def health_check(self) -> bool:
        """Verify the Deribit API is reachable.

        Returns:
            True when ``public/test`` returns a non-empty version string.
        """
        try:
            result = await self._send("public/test", {})
            return result.get("version", "") != ""
        except Exception:
            return False
