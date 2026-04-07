"""Execution engine — validates and routes orders to the CLOB."""
from __future__ import annotations

import logging
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

from polystation.core.orders import Order, OrderManager, OrderStatus
from polystation.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Routes orders from kernels to the Polymarket CLOB.

    Validates orders, submits them via the authenticated ClobClient, and
    updates the OrderManager and Portfolio on fills.  Dry-run mode lets
    kernels be tested end-to-end without touching the live exchange.

    An optional RiskGuard is evaluated before every submission.  When the
    guard vetoes an order it is immediately transitioned to REJECTED without
    touching the CLOB.
    """

    def __init__(
        self,
        clob_client: ClobClient,
        order_manager: OrderManager,
        portfolio: Portfolio,
        metrics: Any = None,
        risk_guard: Any = None,
    ) -> None:
        self.client = clob_client
        self.orders = order_manager
        self.portfolio = portfolio
        self.metrics = metrics
        self.risk_guard = risk_guard
        self._dry_run: bool = False   # Set True to skip actual submission

    def set_dry_run(self, enabled: bool) -> None:
        """Enable or disable dry-run mode.

        In dry-run mode orders are logged and immediately marked as filled
        without contacting the CLOB.

        Args:
            enabled: True to activate dry-run, False to use the live CLOB.
        """
        self._dry_run = enabled
        logger.info("Dry run mode: %s", "ON" if enabled else "OFF")

    def submit_order(self, order: Order) -> dict[str, Any] | None:
        """Submit an order to the CLOB and record the outcome.

        Signs and posts the order using the authenticated ClobClient.  On
        success the OrderManager is updated to FILLED and the Portfolio
        records the fill.  On failure the order is marked REJECTED.

        In dry-run mode the CLOB is bypassed and an immediate synthetic fill
        is recorded instead.

        Args:
            order: Order object previously created via OrderManager.

        Returns:
            The server response dict on success, or None on failure.
        """
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
                    order_id=order.id,
                    token_id=order.token_id,
                    side=order.side,
                    order_price=order.price,
                    fill_price=order.price,
                    fill_size=order.size,
                    kernel_name=order.kernel_name,
                    realized_pnl=fill_realized,
                )
            if self.risk_guard and fill_realized < 0:
                self.risk_guard.record_loss(fill_realized)
            return {"dry_run": True, "order_id": order.id}

        try:
            self.orders.update_status(order.id, OrderStatus.SUBMITTED)

            order_args = OrderArgs(
                price=order.price,
                size=order.size,
                side=order.side,
                token_id=order.token_id,
            )

            signed_order = self.client.create_order(order_args)
            response = self.client.post_order(signed_order)

            if response:
                server_id = response.get("orderID", response.get("order_id", ""))
                self.orders.update_status(
                    order.id, OrderStatus.SUBMITTED, server_order_id=server_id
                )
                # Treat CLOB acceptance as an immediate fill.
                # A production implementation would await fill confirmation
                # via WebSocket or polling before booking the portfolio entry.
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
                        order_id=order.id,
                        token_id=order.token_id,
                        side=order.side,
                        order_price=order.price,
                        fill_price=order.price,
                        fill_size=order.size,
                        kernel_name=order.kernel_name,
                        realized_pnl=fill_realized,
                    )
                if self.risk_guard and fill_realized < 0:
                    self.risk_guard.record_loss(fill_realized)
                logger.info(
                    "Order %s submitted and filled: %s", order.id, server_id
                )
                return response

            self.orders.update_status(
                order.id, OrderStatus.REJECTED, error="No response from CLOB"
            )
            return None

        except Exception as exc:
            self.orders.update_status(order.id, OrderStatus.REJECTED, error=str(exc))
            logger.error("Order %s submission failed: %s", order.id, exc)
            return None

    def cancel_order(self, order: Order) -> bool:
        """Cancel a single active order on the CLOB.

        If the order was never forwarded to the CLOB (no server_order_id) it
        is cancelled locally without a network call.

        Args:
            order: Order to cancel.

        Returns:
            True if the cancellation was accepted or the order was local-only,
            False if the CLOB call raised an exception.
        """
        if not order.server_order_id:
            self.orders.update_status(order.id, OrderStatus.CANCELLED)
            return True

        if self._dry_run:
            logger.info("[DRY RUN] Would cancel: %s", order.id)
            self.orders.update_status(order.id, OrderStatus.CANCELLED)
            return True

        try:
            result = self.client.cancel(order.server_order_id)
            self.orders.update_status(order.id, OrderStatus.CANCELLED)
            logger.info("Order %s cancelled", order.id)
            return bool(result)
        except Exception as exc:
            logger.error("Failed to cancel order %s: %s", order.id, exc)
            return False

    def cancel_all(self, kernel_name: str | None = None) -> int:
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
            if self.cancel_order(order):
                cancelled += 1
        logger.info(
            "Cancelled %d/%d active orders", cancelled, len(active)
        )
        return cancelled
