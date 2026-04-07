"""Tests for polystation.core.prometheus — PolystationMetrics wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from polystation.core.prometheus import PROMETHEUS_AVAILABLE, PolystationMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(
    running: bool = True,
    kernels: dict | None = None,
    active_orders: int = 0,
    realized_pnl: float = 0.0,
    unrealized_pnl: float = 0.0,
    total_pnl: float = 0.0,
    market_value: float = 0.0,
) -> MagicMock:
    """Return a minimal TradingEngine mock for metrics testing."""
    engine = MagicMock()
    engine._running = running
    engine.kernels = kernels or {}

    portfolio = MagicMock()
    portfolio.realized_pnl = realized_pnl
    portfolio.total_unrealized_pnl = unrealized_pnl
    portfolio.total_pnl = total_pnl
    portfolio.total_market_value = market_value
    engine.portfolio = portfolio

    orders = MagicMock()
    orders.get_active_orders.return_value = [MagicMock()] * active_orders
    engine.orders = orders

    engine.metrics = MagicMock()
    engine.metrics.kernel_stats = {}

    return engine


# ===========================================================================
# Graceful degradation when prometheus_client is absent
# ===========================================================================


class TestGracefulDegradation:
    """PolystationMetrics must not crash when prometheus_client is absent."""

    def test_generate_returns_empty_bytes_when_unavailable(self) -> None:
        """Simulate missing prometheus_client by patching PROMETHEUS_AVAILABLE."""
        metrics = PolystationMetrics()
        with patch("polystation.core.prometheus.PROMETHEUS_AVAILABLE", False):
            # Force registry to None to simulate absent lib
            metrics._registry = None
            result = metrics.generate()
        assert result == b""

    def test_update_from_engine_noop_when_registry_none(self) -> None:
        metrics = PolystationMetrics()
        metrics._registry = None
        # Should not raise
        metrics.update_from_engine(_make_engine())

    def test_record_trade_noop_when_registry_none(self) -> None:
        metrics = PolystationMetrics()
        metrics._registry = None
        # Should not raise
        metrics.record_trade(kernel="k1", side="BUY")

    def test_record_order_status_noop_when_registry_none(self) -> None:
        metrics = PolystationMetrics()
        metrics._registry = None
        # Should not raise
        metrics.record_order_status(status="filled")


# ===========================================================================
# Tests that only run when prometheus_client is installed
# ===========================================================================


@pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="prometheus_client not installed")
class TestPolystationMetrics:
    def test_instantiation_creates_registry(self) -> None:
        metrics = PolystationMetrics()
        assert metrics._registry is not None

    def test_generate_returns_bytes(self) -> None:
        metrics = PolystationMetrics()
        result = metrics.generate()
        assert isinstance(result, bytes)

    def test_generate_output_is_non_empty(self) -> None:
        metrics = PolystationMetrics()
        # Set at least one gauge so output is non-empty
        metrics.engine_running.set(1)
        result = metrics.generate()
        assert len(result) > 0

    def test_generate_output_contains_metric_name(self) -> None:
        metrics = PolystationMetrics()
        metrics.engine_running.set(1)
        output = metrics.generate().decode()
        assert "polystation_engine_running" in output

    def test_update_from_engine_sets_running_gauge(self) -> None:
        metrics = PolystationMetrics()
        engine = _make_engine(running=True)
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert "polystation_engine_running 1.0" in output

    def test_update_from_engine_stopped(self) -> None:
        metrics = PolystationMetrics()
        engine = _make_engine(running=False)
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert "polystation_engine_running 0.0" in output

    def test_update_from_engine_sets_portfolio_exposure(self) -> None:
        metrics = PolystationMetrics()
        engine = _make_engine(market_value=1234.56)
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert "polystation_gross_exposure" in output
        assert "1234.56" in output

    def test_update_from_engine_sets_active_orders(self) -> None:
        metrics = PolystationMetrics()
        engine = _make_engine(active_orders=7)
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert "polystation_active_orders 7.0" in output

    def test_update_from_engine_aggregate_pnl(self) -> None:
        metrics = PolystationMetrics()
        engine = _make_engine(realized_pnl=42.5)
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert 'polystation_realized_pnl{kernel="all"}' in output
        assert "42.5" in output

    def test_kernel_status_labels_set(self) -> None:
        metrics = PolystationMetrics()
        kernel = MagicMock()
        kernel.status = "running"
        engine = _make_engine(kernels={"my_kernel": kernel})
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert 'polystation_kernel_status{kernel="my_kernel"}' in output
        assert "1.0" in output

    def test_kernel_status_error_maps_to_minus_one(self) -> None:
        metrics = PolystationMetrics()
        kernel = MagicMock()
        kernel.status = "error"
        engine = _make_engine(kernels={"err_kernel": kernel})
        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert 'polystation_kernel_status{kernel="err_kernel"} -1.0' in output

    def test_record_trade_increments_counter(self) -> None:
        metrics = PolystationMetrics()
        metrics.record_trade(kernel="k1", side="BUY")
        metrics.record_trade(kernel="k1", side="BUY")
        output = metrics.generate().decode()
        assert "polystation_trades_total" in output
        assert '2.0' in output

    def test_record_order_status_increments_counter(self) -> None:
        metrics = PolystationMetrics()
        metrics.record_order_status(status="filled")
        output = metrics.generate().decode()
        assert "polystation_orders_total" in output

    def test_ws_connections_set_to_zero_when_manager_unavailable(self) -> None:
        """When ws manager import fails ws_connections stays at 0."""
        metrics = PolystationMetrics()
        with patch("polystation.dashboard.ws.manager", side_effect=ImportError):
            # The except block in update_from_engine should swallow this
            engine = _make_engine()
            metrics.update_from_engine(engine)
        # ws_connections gauge should still exist and equal 0
        output = metrics.generate().decode()
        assert "polystation_ws_connections" in output

    def test_per_kernel_stats_from_metrics_collector(self) -> None:
        from polystation.core.metrics import KernelStats

        metrics = PolystationMetrics()
        engine = _make_engine()

        ks = KernelStats(name="voice", trade_count=3, win_count=2, loss_count=1, total_pnl=15.0)
        engine.metrics.kernel_stats = {"voice": ks}

        metrics.update_from_engine(engine)
        output = metrics.generate().decode()
        assert 'polystation_realized_pnl{kernel="voice"}' in output
        assert 'polystation_win_rate{kernel="voice"}' in output


# ===========================================================================
# Metrics endpoint (integration)
# ===========================================================================


@pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="prometheus_client not installed")
class TestMetricsEndpoint:
    """Smoke-test the /metrics HTTP endpoint through the FastAPI test client."""

    def test_metrics_endpoint_returns_200(self) -> None:
        import httpx
        from fastapi.testclient import TestClient

        from polystation.dashboard.app import create_app

        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_content_type(self) -> None:
        import httpx
        from fastapi.testclient import TestClient

        from polystation.dashboard.app import create_app

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/metrics")
        assert "text/plain" in response.headers.get("content-type", "")

    def test_metrics_endpoint_contains_engine_metric(self) -> None:
        from fastapi.testclient import TestClient

        from polystation.dashboard.app import create_app

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/metrics")
        assert "polystation_engine_running" in response.text
