"""Prometheus metrics for Polystation. Optional — works only if prometheus_client is installed."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.info("prometheus_client not installed — /metrics endpoint disabled")


class PolystationMetrics:
    """Manages Prometheus gauges and counters for the trading engine.

    All methods are no-ops if prometheus_client is not installed.
    """

    def __init__(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            self._registry = None
            return

        self._registry = CollectorRegistry()

        # P&L gauges (labeled by kernel)
        self.realized_pnl = Gauge(
            "polystation_realized_pnl", "Realized P&L in USD", ["kernel"], registry=self._registry
        )
        self.unrealized_pnl = Gauge(
            "polystation_unrealized_pnl", "Unrealized P&L in USD", ["kernel"], registry=self._registry
        )
        self.total_pnl = Gauge(
            "polystation_total_pnl", "Total P&L in USD", ["kernel"], registry=self._registry
        )

        # Position gauges
        self.position_count = Gauge(
            "polystation_position_count", "Open positions", ["kernel"], registry=self._registry
        )
        self.gross_exposure = Gauge(
            "polystation_gross_exposure", "Gross exposure in USD", registry=self._registry
        )

        # Trade counters
        self.trade_count = Counter(
            "polystation_trades_total", "Total trades", ["kernel", "side"], registry=self._registry
        )
        self.order_count = Counter(
            "polystation_orders_total", "Total orders by status", ["status"], registry=self._registry
        )

        # Win rate gauge
        self.win_rate = Gauge(
            "polystation_win_rate", "Win rate", ["kernel"], registry=self._registry
        )

        # Engine status
        self.engine_running = Gauge(
            "polystation_engine_running", "1 if engine is running", registry=self._registry
        )
        self.kernel_status = Gauge(
            "polystation_kernel_status",
            "Kernel status (1=running, 0=stopped, -1=error)",
            ["kernel"],
            registry=self._registry,
        )
        self.active_orders = Gauge(
            "polystation_active_orders", "Active orders", registry=self._registry
        )
        self.ws_connections = Gauge(
            "polystation_ws_connections", "WebSocket connections", registry=self._registry
        )

    def update_from_engine(self, engine: Any) -> None:
        """Pull current state from engine and update all gauges.

        Args:
            engine: TradingEngine instance to read state from.
        """
        if not PROMETHEUS_AVAILABLE or self._registry is None:
            return

        # Engine status
        self.engine_running.set(1 if engine._running else 0)

        # Kernel status
        for name, kernel in engine.kernels.items():
            status_map = {"running": 1, "stopped": 0, "error": -1, "starting": 0.5, "stopping": 0.5}
            self.kernel_status.labels(kernel=name).set(status_map.get(kernel.status, 0))

        # Portfolio
        if engine.portfolio:
            p = engine.portfolio
            self.gross_exposure.set(p.total_market_value)
            # Aggregate P&L (no kernel label for aggregate)
            self.realized_pnl.labels(kernel="all").set(p.realized_pnl)
            self.unrealized_pnl.labels(kernel="all").set(p.total_unrealized_pnl)
            self.total_pnl.labels(kernel="all").set(p.total_pnl)

        # Per-kernel metrics from MetricsCollector
        if engine.metrics:
            for ks in engine.metrics.kernel_stats.values():
                self.realized_pnl.labels(kernel=ks.name).set(ks.total_pnl)
                self.win_rate.labels(kernel=ks.name).set(ks.win_rate)
                self.position_count.labels(kernel=ks.name).set(ks.trade_count)  # approximate

        # Orders
        if engine.orders:
            active = len(engine.orders.get_active_orders())
            self.active_orders.set(active)

        # WebSocket connections
        try:
            from polystation.dashboard.ws import manager

            self.ws_connections.set(len(manager.active))
        except Exception:
            pass

    def record_trade(self, kernel: str, side: str) -> None:
        """Increment the trade counter for a kernel/side combination.

        Args:
            kernel: Kernel name label.
            side: Order side label (BUY or SELL).
        """
        if PROMETHEUS_AVAILABLE and self._registry:
            self.trade_count.labels(kernel=kernel, side=side).inc()

    def record_order_status(self, status: str) -> None:
        """Increment the order counter for a given status.

        Args:
            status: Order status label (e.g. filled, rejected).
        """
        if PROMETHEUS_AVAILABLE and self._registry:
            self.order_count.labels(status=status).inc()

    def generate(self) -> bytes:
        """Render all registered metrics in Prometheus text format.

        Returns:
            UTF-8 encoded Prometheus exposition format bytes, or empty bytes
            when prometheus_client is not available.
        """
        if not PROMETHEUS_AVAILABLE or self._registry is None:
            return b""
        return generate_latest(self._registry)
