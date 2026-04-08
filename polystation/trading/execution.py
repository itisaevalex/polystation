"""Execution engine — validates and routes orders through the exchange abstraction."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from polystation.core.orders import Order, OrderManager, OrderStatus
from polystation.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Routes orders from kernels through an Exchange adapter to the market.

    Validates orders, delegates submission to the configured
    :class:`~polystation.exchanges.base.Exchange`, and updates
    :class:`OrderManager` and :class:`Portfolio` on fills.  Dry-run mode
    lets kernels be tested end-to-end without touching a live exchange.

    Args:
        exchange: A connected :class:`~polystation.exchanges.base.Exchange`
            instance (e.g. :class:`~polystation.exchanges.polymarket.PolymarketExchange`).
            Pass ``None`` when running in dry-run-only mode.
        order_manager: Shared :class:`OrderManager` instance.
        portfolio: Shared :class:`Portfolio` instance.
    """

    def __init__(
        self,
        exchange: Any | None,
        order_manager: OrderManager,
        portfolio: Portfolio,
        metrics: Any | None = None,
        risk_guard: Any | None = None,
        redis_client: Any | None = None,
        db: Any | None = None,
    ) -> None:
        self.exchange = exchange
        self.orders = order_manager
        self.portfolio = portfolio
        self.metrics = metrics
        self.risk_guard = risk_guard
        self.redis = redis_client
        self.db = db
        self._dry_run: bool = False

    def set_dry_run(self, enabled: bool) -> None:
        """Enable or disable dry-run mode.

        In dry-run mode orders are logged and immediately marked as filled
        without contacting any exchange.

        Args:
            enabled: True to activate dry-run, False to use the live exchange.
        """
        self._dry_run = enabled
        logger.info("Dry run mode: %s", "ON" if enabled else "OFF")

    async def submit_order(self, order: Order) -> dict[str, Any] | None:
        """Submit an order and record the outcome.

        In dry-run mode the exchange is bypassed and a synthetic fill is
        recorded immediately.  In live mode the order is forwarded to
        :meth:`~polystation.exchanges.base.Exchange.place_order`.

        Args:
            order: Order object previously created via :class:`OrderManager`.

        Returns:
            A result dict on success, or None on failure/rejection.
        """
        # Risk check (before any exchange interaction)
        if self.risk_guard:
            allowed, reason = self.risk_guard.check(order, self.portfolio, self.orders)
            if not allowed:
                self.orders.update_status(order.id, OrderStatus.REJECTED, error=f"Risk: {reason}")
                return None

        if self._dry_run:
            logger.info(
                "[DRY RUN] Would submit: %s %s %.0f @ %.4f",
                order.side,
                order.token_id[:20],
                order.size,
                order.price,
            )
            prev_realized = self.portfolio.realized_pnl
            self.orders.update_status(order.id, OrderStatus.FILLED)
            self.orders.record_fill(order.id, order.price, order.size)
            self.portfolio.record_fill(
                order.token_id,
                order.side,
                order.price,
                order.size,
                market_id=order.market_id,
            )
            fill_realized = self.portfolio.realized_pnl - prev_realized
            if self.metrics:
                self.metrics.record_fill(
                    order_id=order.id, token_id=order.token_id, side=order.side,
                    order_price=order.price, fill_price=order.price,
                    fill_size=order.size, kernel_name=order.kernel_name,
                    realized_pnl=fill_realized,
                )
            if self.risk_guard and fill_realized < 0:
                self.risk_guard.record_loss(fill_realized)
            if self.redis:
                self.redis.publish_trade({"order_id": order.id, "side": order.side,
                    "price": order.price, "size": order.size, "kernel": order.kernel_name})
            if self.db:
                try:
                    self.db.save_order(order.to_dict())
                    self.db.save_trade({
                        "order_id": order.id,
                        "token_id": order.token_id,
                        "side": order.side,
                        "price": order.price,
                        "size": order.size,
                        "pnl": fill_realized,
                        "kernel_name": order.kernel_name,
                        "exchange": order.exchange,
                    })
                    pos = self.portfolio.get_position(order.token_id)
                    if pos is not None:
                        self.db.save_position(pos.to_dict())
                except Exception:
                    logger.exception("Failed to persist dry-run fill to database")
            return {"dry_run": True, "order_id": order.id}

        if self.exchange is None:
            self.orders.update_status(
                order.id, OrderStatus.REJECTED, error="No exchange configured"
            )
            logger.error("submit_order called but no exchange is configured")
            return None

        try:
            self.orders.update_status(order.id, OrderStatus.SUBMITTED)

            result = await self.exchange.place_order(
                symbol=order.token_id,
                side=order.side,
                price=order.price,
                size=order.size,
            )

            if result and result.status in ("accepted", "filled"):
                server_id = result.order_id
                self.orders.update_status(
                    order.id, OrderStatus.SUBMITTED, server_order_id=server_id
                )
                prev_realized = self.portfolio.realized_pnl
                self.orders.record_fill(order.id, order.price, order.size)
                self.portfolio.record_fill(
                    order.token_id,
                    order.side,
                    order.price,
                    order.size,
                    market_id=order.market_id,
                )
                fill_realized = self.portfolio.realized_pnl - prev_realized
                if self.metrics:
                    self.metrics.record_fill(
                        order_id=order.id, token_id=order.token_id, side=order.side,
                        order_price=order.price, fill_price=result.filled_price or order.price,
                        fill_size=order.size, kernel_name=order.kernel_name,
                        realized_pnl=fill_realized,
                    )
                if self.risk_guard and fill_realized < 0:
                    self.risk_guard.record_loss(fill_realized)
                if self.redis:
                    self.redis.publish_trade({"order_id": order.id, "side": order.side,
                        "price": order.price, "size": order.size, "kernel": order.kernel_name})
                if self.db:
                    try:
                        self.db.save_order(order.to_dict())
                        self.db.save_trade({
                            "order_id": order.id,
                            "token_id": order.token_id,
                            "side": order.side,
                            "price": result.filled_price or order.price,
                            "size": order.size,
                            "pnl": fill_realized,
                            "kernel_name": order.kernel_name,
                            "exchange": order.exchange,
                        })
                        pos = self.portfolio.get_position(order.token_id)
                        if pos is not None:
                            self.db.save_position(pos.to_dict())
                    except Exception:
                        logger.exception("Failed to persist live fill to database")
                logger.info("Order %s submitted via %s: %s", order.id, self.exchange.name, server_id)
                return {"order_id": server_id, "status": result.status}

            error_msg = (result.error or "No response from exchange") if result else "No response from exchange"
            self.orders.update_status(order.id, OrderStatus.REJECTED, error=error_msg)
            return None

        except Exception as exc:
            self.orders.update_status(order.id, OrderStatus.REJECTED, error=str(exc))
            logger.error("Order %s submission failed: %s", order.id, exc)
            return None

    def submit_order_sync(self, order: Order) -> dict[str, Any] | None:
        """Synchronous wrapper for :meth:`submit_order`.

        Intended for use in threaded contexts (e.g. VoiceKernel's daemon
        thread) where an event loop is already running.  Uses
        :func:`asyncio.run_coroutine_threadsafe` when a running loop is
        detected, or :func:`asyncio.run` otherwise.

        Args:
            order: Order to submit.

        Returns:
            Result dict on success, or None on failure.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.submit_order(order), loop
                )
                return future.result(timeout=30)
            else:
                return asyncio.run(self.submit_order(order))
        except Exception as exc:
            logger.error("submit_order_sync failed: %s", exc)
            return None

    async def cancel_order(self, order: Order) -> bool:
        """Cancel a single active order.

        If the order has no ``server_order_id`` it is cancelled locally
        without an exchange call.

        Args:
            order: Order to cancel.

        Returns:
            True when the cancellation succeeded, False otherwise.
        """
        if not order.server_order_id:
            self.orders.update_status(order.id, OrderStatus.CANCELLED)
            return True

        if self._dry_run:
            logger.info("[DRY RUN] Would cancel: %s", order.id)
            self.orders.update_status(order.id, OrderStatus.CANCELLED)
            return True

        if self.exchange is None:
            logger.warning("cancel_order called but no exchange is configured")
            return False

        try:
            result = await self.exchange.cancel_order(order.server_order_id)
            self.orders.update_status(order.id, OrderStatus.CANCELLED)
            logger.info("Order %s cancelled", order.id)
            return bool(result)
        except Exception as exc:
            logger.error("Failed to cancel order %s: %s", order.id, exc)
            return False

    async def cancel_all(self, kernel_name: str | None = None) -> int:
        """Cancel all active orders, optionally scoped to one kernel.

        Args:
            kernel_name: When provided, only orders belonging to this kernel
                are cancelled.

        Returns:
            Number of orders successfully cancelled.
        """
        active = self.orders.get_active_orders(kernel_name)
        cancelled = 0
        for order in active:
            if await self.cancel_order(order):
                cancelled += 1
        logger.info("Cancelled %d/%d active orders", cancelled, len(active))
        return cancelled

    def cancel_all_sync(self, kernel_name: str | None = None) -> int:
        """Synchronous wrapper for :meth:`cancel_all`.

        Falls back to local-only cancellation (no exchange call) when no
        running event loop is detected.  Intended for use in threaded
        contexts where ``await`` is not available.

        Args:
            kernel_name: When provided, only orders belonging to this kernel
                are cancelled.

        Returns:
            Number of orders successfully cancelled.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.cancel_all(kernel_name), loop
                )
                return future.result(timeout=30)
            else:
                return asyncio.run(self.cancel_all(kernel_name))
        except Exception as exc:
            logger.error("cancel_all_sync failed: %s", exc)
            # Best-effort local cancellation to avoid stuck orders.
            active = self.orders.get_active_orders(kernel_name)
            for order in active:
                self.orders.update_status(order.id, OrderStatus.CANCELLED)
            return len(active)
