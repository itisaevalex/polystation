"""Polymarket CLOB exchange adapter."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from polystation.exchanges.base import (
    Exchange,
    ExchangeOrderBook,
    ExchangePosition,
    OrderResult,
    OrderType,
)

logger = logging.getLogger(__name__)


class PolymarketExchange(Exchange):
    """Exchange adapter wrapping the Polymarket CLOB REST API.

    Since ``py-clob-client`` is fully synchronous, every network call is
    dispatched via :func:`asyncio.to_thread` so the event loop remains free.

    A read-only :class:`MarketDataClient` is always initialised on
    :meth:`connect`; the authenticated ``ClobClient`` is only constructed
    when a private key is available.

    Args:
        host: CLOB API base URL.
        private_key: Wallet private key for signing orders.  Falls back to
            the ``PK`` environment variable when omitted.
        api_key: API key for the CLOB.  Falls back to ``CLOB_API_KEY``.
        api_secret: API secret.  Falls back to ``CLOB_SECRET``.
        api_passphrase: API passphrase.  Falls back to ``CLOB_PASS_PHRASE``.
    """

    name = "polymarket"

    def __init__(
        self,
        host: str = "https://clob.polymarket.com",
        private_key: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        api_passphrase: str | None = None,
    ) -> None:
        self.host = host
        self._pk = private_key
        self._api_key = api_key
        self._api_secret = api_secret
        self._api_passphrase = api_passphrase
        self._client: Any = None        # ClobClient (authenticated)
        self._market_client: Any = None  # MarketDataClient (read-only)

    async def connect(self) -> None:
        """Initialize CLOB and market-data connections.

        Always creates a read-only :class:`MarketDataClient`.  When a private
        key is found (parameter or ``PK`` env var) an authenticated
        ``ClobClient`` is also constructed for order submission.
        """
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
        from py_clob_client.constants import POLYGON
        from polystation.market.client import MarketDataClient

        # Read-only market data client — always available, no auth required.
        self._market_client = MarketDataClient(self.host)

        pk = self._pk or os.getenv("PK")
        creds: ApiCreds | None = None
        ak = self._api_key or os.getenv("CLOB_API_KEY")
        if ak:
            creds = ApiCreds(
                api_key=ak,
                api_secret=self._api_secret or os.getenv("CLOB_SECRET", ""),
                api_passphrase=self._api_passphrase or os.getenv("CLOB_PASS_PHRASE", ""),
            )

        if pk:
            self._client = ClobClient(
                host=self.host, key=pk, chain_id=POLYGON, creds=creds
            )
            logger.info("PolymarketExchange connected with trading credentials")
        else:
            self._client = ClobClient(host=self.host, chain_id=POLYGON)
            logger.info("PolymarketExchange connected (read-only, no PK)")

    async def disconnect(self) -> None:
        """Release client references."""
        self._client = None
        self._market_client = None
        logger.info("PolymarketExchange disconnected")

    async def place_order(
        self,
        symbol: str,
        side: str,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
    ) -> OrderResult:
        """Sign and post a limit order to the Polymarket CLOB.

        Args:
            symbol: Token ID (``token_id`` in CLOB parlance).
            side: ``"BUY"`` or ``"SELL"``.
            price: Limit price between 0 and 1.  For MARKET orders this value
                is ignored — the current best price is fetched automatically.
            size: Number of shares.
            order_type: Time-in-force.  Defaults to GTC.

        Returns:
            :class:`OrderResult` describing the outcome.
        """
        if self._client is None:
            return OrderResult(order_id="", status="rejected", error="Not connected")

        from py_clob_client.clob_types import OrderArgs
        from py_clob_client.clob_types import OrderType as ClobOrderType

        # Map internal OrderType to py-clob-client OrderType.
        # Polymarket uses FAK (Fill-And-Kill) for IOC-like behaviour.
        ORDER_TYPE_MAP: dict[OrderType, ClobOrderType] = {
            OrderType.GTC: ClobOrderType.GTC,
            OrderType.FOK: ClobOrderType.FOK,
            OrderType.IOC: ClobOrderType.FOK,   # Polymarket uses FAK/FOK for IOC
            OrderType.GTD: ClobOrderType.GTD,
        }

        # For MARKET orders fetch the best available price first.
        effective_price = price
        if order_type == OrderType.MARKET:
            best = await self.get_price(symbol, side)
            if best is None:
                return OrderResult(
                    order_id="", status="rejected",
                    error="Could not determine market price"
                )
            effective_price = best

        clob_order_type: ClobOrderType | None = ORDER_TYPE_MAP.get(order_type)

        def _place() -> Any:
            order_args = OrderArgs(
                price=effective_price,
                size=size,
                side=side,
                token_id=symbol,
            )
            signed = self._client.create_order(order_args)
            if clob_order_type is not None:
                return self._client.post_order(signed, orderType=clob_order_type)
            return self._client.post_order(signed)

        try:
            resp = await asyncio.to_thread(_place)
            if resp:
                oid = resp.get("orderID", resp.get("order_id", ""))
                return OrderResult(
                    order_id=oid,
                    status="accepted",
                    filled_price=effective_price,
                    filled_size=size,
                )
            return OrderResult(order_id="", status="rejected", error="No response from CLOB")
        except Exception as exc:
            logger.error("place_order failed for symbol=%s: %s", symbol, exc)
            return OrderResult(order_id="", status="rejected", error=str(exc))

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a single open order by its CLOB-assigned ID.

        Args:
            order_id: CLOB order identifier.

        Returns:
            True when the cancellation was accepted, False on error.
        """
        if not self._client:
            return False
        try:
            result = await asyncio.to_thread(self._client.cancel, order_id)
            return bool(result)
        except Exception as exc:
            logger.error("cancel_order failed for order_id=%s: %s", order_id, exc)
            return False

    async def cancel_all_orders(self, symbol: str | None = None) -> int:
        """Cancel all open orders, optionally scoped to one token.

        The Polymarket CLOB does not return a count; this method returns
        ``1`` on success and ``0`` on failure.

        Args:
            symbol: Token ID.  When provided, only orders for this token
                are cancelled.

        Returns:
            ``1`` on success, ``0`` on failure.
        """
        if not self._client:
            return 0
        try:
            if symbol:
                await asyncio.to_thread(
                    self._client.cancel_market_orders,
                    market="",
                    asset_id=symbol,
                )
            else:
                await asyncio.to_thread(self._client.cancel_all)
            return 1  # CLOB does not return a cancelled-order count
        except Exception as exc:
            logger.error("cancel_all_orders failed (symbol=%s): %s", symbol, exc)
            return 0

    async def get_orderbook(self, symbol: str) -> ExchangeOrderBook:
        """Fetch and normalise the order book for a token.

        Args:
            symbol: Token ID.

        Returns:
            :class:`ExchangeOrderBook` snapshot.  Returns an empty book on
            error.
        """
        if not self._market_client:
            return ExchangeOrderBook(symbol=symbol)

        def _fetch() -> Any:
            raw = self._market_client.get_order_book(symbol)
            from polystation.market.book import OrderBook

            return OrderBook.from_clob_response(symbol, raw)

        try:
            book = await asyncio.to_thread(_fetch)
            return ExchangeOrderBook(
                symbol=symbol,
                bids=[(lv.price, lv.size) for lv in book.bids],
                asks=[(lv.price, lv.size) for lv in book.asks],
                timestamp=book.timestamp,
            )
        except Exception as exc:
            logger.warning("get_orderbook failed for symbol=%s: %s", symbol, exc)
            return ExchangeOrderBook(symbol=symbol)

    async def get_positions(self) -> list[ExchangePosition]:
        """Return open positions.

        Polymarket CLOB does not expose a positions endpoint; returns an
        empty list.
        """
        return []

    async def get_balance(self) -> dict[str, float]:
        """Return available balances.

        On-chain balance lookup is not yet implemented; returns an empty
        mapping.
        """
        return {}

    async def get_midpoint(self, symbol: str) -> float | None:
        """Get the mid-market price for a token.

        Args:
            symbol: Token ID.

        Returns:
            Mid-market price, or None on error.
        """
        if not self._market_client:
            return None
        try:
            return await asyncio.to_thread(self._market_client.get_midpoint, symbol)
        except Exception as exc:
            logger.warning("get_midpoint failed for symbol=%s: %s", symbol, exc)
            return None

    async def get_price(self, symbol: str, side: str) -> float | None:
        """Get the best price for a token on the given side.

        Args:
            symbol: Token ID.
            side: ``"BUY"`` or ``"SELL"``.

        Returns:
            Best price for the requested side, or None on error.
        """
        if not self._market_client:
            return None
        try:
            return await asyncio.to_thread(self._market_client.get_price, symbol, side)
        except Exception as exc:
            logger.warning("get_price failed for symbol=%s side=%s: %s", symbol, side, exc)
            return None

    async def health_check(self) -> bool:
        """Check whether the Polymarket CLOB API is reachable.

        Returns:
            True when the API responds with ``"OK"``, False otherwise.
        """
        if not self._market_client:
            return False
        try:
            return await asyncio.to_thread(self._market_client.health)
        except Exception as exc:
            logger.warning("health_check failed: %s", exc)
            return False
