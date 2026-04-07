"""Tests for polystation.core.risk — RiskGuard pre-trade veto system."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from polystation.core.risk import RiskConfig, RiskGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(
    price: float = 0.5,
    size: float = 10.0,
    token_id: str = "tok-aaa",
    order_id: str = "ORD-000001",
) -> MagicMock:
    """Return a minimal order mock."""
    order = MagicMock()
    order.price = price
    order.size = size
    order.token_id = token_id
    order.id = order_id
    return order


def _make_portfolio(
    total_market_value: float = 0.0,
    realized_pnl: float = 0.0,
    position_size: float = 0.0,
) -> MagicMock:
    """Return a minimal portfolio mock."""
    p = MagicMock()
    p.total_market_value = total_market_value
    p.realized_pnl = realized_pnl
    pos = MagicMock()
    pos.size = position_size
    p.get_position.return_value = pos if position_size > 0 else None
    return p


def _make_orders(active_count: int = 0) -> MagicMock:
    """Return an orders mock with a fixed number of active orders."""
    orders = MagicMock()
    orders.get_active_orders.return_value = [MagicMock()] * active_count
    return orders


# ===========================================================================
# RiskConfig defaults
# ===========================================================================


class TestRiskConfigDefaults:
    def test_defaults_are_set(self) -> None:
        cfg = RiskConfig()
        assert cfg.max_stake_per_trade == 500.0
        assert cfg.max_gross_exposure == 10000.0
        assert cfg.max_position_per_token == 1000.0
        assert cfg.daily_loss_stop == -500.0
        assert cfg.max_active_orders == 50
        assert cfg.max_daily_trades == 200
        assert cfg.enabled is True

    def test_custom_values(self) -> None:
        cfg = RiskConfig(max_stake_per_trade=100.0, enabled=False)
        assert cfg.max_stake_per_trade == 100.0
        assert cfg.enabled is False


# ===========================================================================
# RiskGuard.check — disabled pass-through
# ===========================================================================


class TestRiskGuardDisabled:
    def test_disabled_guard_approves_any_order(self) -> None:
        guard = RiskGuard(RiskConfig(enabled=False))
        # Even an order that would breach every limit
        order = _make_order(price=1.0, size=99999.0)
        allowed, reason = guard.check(order, _make_portfolio(), _make_orders())
        assert allowed is True
        assert reason == ""


# ===========================================================================
# RiskGuard.check — max_stake_per_trade
# ===========================================================================


class TestMaxStakeCheck:
    def test_order_below_limit_passes(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=500.0))
        order = _make_order(price=0.5, size=100.0)  # value = 50
        allowed, _ = guard.check(order, _make_portfolio(), _make_orders())
        assert allowed is True

    def test_order_at_limit_passes(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=500.0))
        order = _make_order(price=0.5, size=1000.0)  # value = 500
        allowed, _ = guard.check(order, _make_portfolio(), _make_orders())
        assert allowed is True

    def test_order_above_limit_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=500.0))
        order = _make_order(price=0.5, size=1001.0)  # value = 500.5
        allowed, reason = guard.check(order, _make_portfolio(), _make_orders())
        assert allowed is False
        assert "max stake" in reason.lower()

    def test_veto_reason_contains_amounts(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=100.0))
        order = _make_order(price=1.0, size=200.0)  # value = 200
        _, reason = guard.check(order, _make_portfolio(), _make_orders())
        assert "200.00" in reason
        assert "100.00" in reason


# ===========================================================================
# RiskGuard.check — max_gross_exposure
# ===========================================================================


class TestMaxGrossExposureCheck:
    def test_exposure_within_limit_passes(self) -> None:
        guard = RiskGuard(RiskConfig(max_gross_exposure=10000.0))
        portfolio = _make_portfolio(total_market_value=9000.0)
        order = _make_order(price=0.5, size=100.0)  # adds 50 → 9050
        allowed, _ = guard.check(order, portfolio, _make_orders())
        assert allowed is True

    def test_exposure_exceeds_limit_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(max_gross_exposure=1000.0))
        portfolio = _make_portfolio(total_market_value=990.0)
        order = _make_order(price=1.0, size=20.0)  # adds 20 → 1010
        allowed, reason = guard.check(order, portfolio, _make_orders())
        assert allowed is False
        assert "gross exposure" in reason.lower()


# ===========================================================================
# RiskGuard.check — max_position_per_token
# ===========================================================================


class TestMaxPositionPerTokenCheck:
    def test_new_token_position_not_checked(self) -> None:
        """No existing position — token check is skipped."""
        guard = RiskGuard(RiskConfig(max_position_per_token=100.0))
        portfolio = _make_portfolio(position_size=0.0)  # get_position returns None
        order = _make_order(price=0.5, size=10.0)
        allowed, _ = guard.check(order, portfolio, _make_orders())
        assert allowed is True

    def test_existing_position_within_limit_passes(self) -> None:
        guard = RiskGuard(RiskConfig(max_position_per_token=1000.0))
        portfolio = _make_portfolio(position_size=100.0)
        order = _make_order(price=0.5, size=10.0)  # new total value = 110 * 0.5 = 55
        allowed, _ = guard.check(order, portfolio, _make_orders())
        assert allowed is True

    def test_existing_position_exceeds_limit_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(max_position_per_token=100.0))
        portfolio = _make_portfolio(position_size=500.0)
        order = _make_order(price=1.0, size=1.0)  # new total = 501 * 1.0 = 501 > 100
        allowed, reason = guard.check(order, portfolio, _make_orders())
        assert allowed is False
        assert "position" in reason.lower()


# ===========================================================================
# RiskGuard.check — daily_loss_stop
# ===========================================================================


class TestDailyLossStopCheck:
    def test_no_loss_passes(self) -> None:
        guard = RiskGuard(RiskConfig(daily_loss_stop=-500.0))
        portfolio = _make_portfolio(realized_pnl=100.0)
        allowed, _ = guard.check(_make_order(), portfolio, _make_orders())
        assert allowed is True

    def test_loss_below_stop_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(daily_loss_stop=-500.0))
        portfolio = _make_portfolio(realized_pnl=-500.0)  # exactly at stop
        allowed, reason = guard.check(_make_order(), portfolio, _make_orders())
        assert allowed is False
        assert "loss stop" in reason.lower()

    def test_loss_above_stop_passes(self) -> None:
        guard = RiskGuard(RiskConfig(daily_loss_stop=-500.0))
        portfolio = _make_portfolio(realized_pnl=-499.99)
        allowed, _ = guard.check(_make_order(), portfolio, _make_orders())
        assert allowed is True


# ===========================================================================
# RiskGuard.check — max_active_orders
# ===========================================================================


class TestMaxActiveOrdersCheck:
    def test_below_limit_passes(self) -> None:
        guard = RiskGuard(RiskConfig(max_active_orders=10))
        allowed, _ = guard.check(_make_order(), _make_portfolio(), _make_orders(9))
        assert allowed is True

    def test_at_limit_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(max_active_orders=10))
        allowed, reason = guard.check(_make_order(), _make_portfolio(), _make_orders(10))
        assert allowed is False
        assert "active orders" in reason.lower()

    def test_above_limit_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(max_active_orders=5))
        allowed, _ = guard.check(_make_order(), _make_portfolio(), _make_orders(20))
        assert allowed is False


# ===========================================================================
# RiskGuard.check — max_daily_trades
# ===========================================================================


class TestMaxDailyTradesCheck:
    def test_below_limit_increments_counter(self) -> None:
        guard = RiskGuard(RiskConfig(max_daily_trades=10))
        for _ in range(5):
            guard.check(_make_order(), _make_portfolio(), _make_orders())
        assert guard.daily_trade_count == 5

    def test_at_limit_vetoed(self) -> None:
        guard = RiskGuard(RiskConfig(max_daily_trades=3))
        for _ in range(3):
            guard.check(_make_order(), _make_portfolio(), _make_orders())
        allowed, reason = guard.check(_make_order(), _make_portfolio(), _make_orders())
        assert allowed is False
        assert "daily trades" in reason.lower()

    def test_counter_not_incremented_on_earlier_veto(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=1.0, max_daily_trades=100))
        order = _make_order(price=1.0, size=100.0)  # vetoed by stake check
        guard.check(order, _make_portfolio(), _make_orders())
        assert guard.daily_trade_count == 0


# ===========================================================================
# Veto log behaviour
# ===========================================================================


class TestVetoLog:
    def test_veto_appended_to_log(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=1.0))
        order = _make_order(price=1.0, size=100.0, order_id="ORD-TEST")
        guard.check(order, _make_portfolio(), _make_orders())
        assert len(guard._vetoes) == 1
        assert guard._vetoes[0]["order_id"] == "ORD-TEST"

    def test_veto_log_capped_at_100(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=1.0))
        for i in range(150):
            order = _make_order(price=1.0, size=100.0, order_id=f"ORD-{i:06d}")
            guard.check(order, _make_portfolio(), _make_orders())
        assert len(guard._vetoes) == 100

    def test_veto_log_contains_timestamp(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=1.0))
        order = _make_order(price=1.0, size=100.0)
        guard.check(order, _make_portfolio(), _make_orders())
        assert "timestamp" in guard._vetoes[0]

    def test_get_status_recent_vetoes_limited_to_10(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=1.0))
        for i in range(20):
            order = _make_order(price=1.0, size=100.0, order_id=f"ORD-{i:06d}")
            guard.check(order, _make_portfolio(), _make_orders())
        status = guard.get_status()
        assert len(status["recent_vetoes"]) == 10


# ===========================================================================
# get_status / update_config
# ===========================================================================


class TestGetStatus:
    def test_returns_enabled_flag(self) -> None:
        guard = RiskGuard(RiskConfig(enabled=True))
        assert guard.get_status()["enabled"] is True

    def test_returns_config_dict(self) -> None:
        guard = RiskGuard()
        status = guard.get_status()
        assert "max_stake_per_trade" in status["config"]
        assert "max_gross_exposure" in status["config"]

    def test_daily_trade_count_in_status(self) -> None:
        guard = RiskGuard(RiskConfig(max_daily_trades=100))
        guard.check(_make_order(), _make_portfolio(), _make_orders())
        assert guard.get_status()["daily_trade_count"] == 1

    def test_daily_loss_rounded(self) -> None:
        guard = RiskGuard()
        guard.record_loss(-12.3456789)
        status = guard.get_status()
        assert status["daily_loss"] == pytest.approx(-12.3457, abs=1e-4)


class TestUpdateConfig:
    def test_updates_known_field(self) -> None:
        guard = RiskGuard()
        guard.update_config(max_stake_per_trade=99.0)
        assert guard.config.max_stake_per_trade == 99.0

    def test_ignores_unknown_fields(self) -> None:
        guard = RiskGuard()
        # Should not raise
        guard.update_config(nonexistent_field=42)

    def test_update_takes_effect_on_next_check(self) -> None:
        guard = RiskGuard(RiskConfig(max_stake_per_trade=500.0))
        order = _make_order(price=1.0, size=200.0)  # value 200 — passes
        allowed, _ = guard.check(order, _make_portfolio(), _make_orders())
        assert allowed is True

        guard.update_config(max_stake_per_trade=100.0)
        allowed, _ = guard.check(order, _make_portfolio(), _make_orders())
        assert allowed is False


# ===========================================================================
# record_loss / reset_daily
# ===========================================================================


class TestRecordLoss:
    def test_negative_amount_accumulated(self) -> None:
        guard = RiskGuard()
        guard.record_loss(-50.0)
        guard.record_loss(-30.0)
        assert guard.daily_loss == pytest.approx(-80.0)

    def test_positive_amount_ignored(self) -> None:
        guard = RiskGuard()
        guard.record_loss(100.0)
        assert guard.daily_loss == 0.0

    def test_zero_ignored(self) -> None:
        guard = RiskGuard()
        guard.record_loss(0.0)
        assert guard.daily_loss == 0.0


class TestResetDaily:
    def test_resets_trade_count(self) -> None:
        guard = RiskGuard(RiskConfig(max_daily_trades=100))
        for _ in range(5):
            guard.check(_make_order(), _make_portfolio(), _make_orders())
        guard.reset_daily()
        assert guard.daily_trade_count == 0

    def test_resets_daily_loss(self) -> None:
        guard = RiskGuard()
        guard.record_loss(-200.0)
        guard.reset_daily()
        assert guard.daily_loss == 0.0

    def test_updates_day_start(self) -> None:
        guard = RiskGuard()
        before = guard._day_start
        guard.reset_daily()
        assert guard._day_start >= before


# ===========================================================================
# Daily counter auto-reset
# ===========================================================================


class TestDayReset:
    def test_counter_resets_when_day_changes(self) -> None:
        guard = RiskGuard(RiskConfig(max_daily_trades=100))
        # Simulate being in the past
        guard._day_start = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
        guard.daily_trade_count = 99

        # This check should detect the day change and reset
        guard.check(_make_order(), _make_portfolio(), _make_orders())
        # After reset counter starts at 0, then increments to 1
        assert guard.daily_trade_count == 1


# ===========================================================================
# Integration with ExecutionEngine
# ===========================================================================


class TestRiskGuardIntegration:
    """Verify that ExecutionEngine correctly gates orders through RiskGuard."""

    def test_vetoed_order_is_rejected(self) -> None:
        from polystation.core.orders import OrderManager, OrderStatus
        from polystation.core.portfolio import Portfolio
        from polystation.trading.execution import ExecutionEngine

        om = OrderManager()
        portfolio = Portfolio()
        risk = RiskGuard(RiskConfig(max_stake_per_trade=1.0))  # very tight limit
        engine = ExecutionEngine(
            None, om, portfolio, risk_guard=risk  # type: ignore[arg-type]
        )
        engine.set_dry_run(True)

        order = om.create_order(
            token_id="tok-aaa", side="BUY", price=1.0, size=100.0
        )
        result = engine.submit_order(order)

        assert result is None
        assert order.status == OrderStatus.REJECTED
        assert "Risk:" in order.error

    def test_approved_order_fills_normally(self) -> None:
        from polystation.core.orders import OrderManager, OrderStatus
        from polystation.core.portfolio import Portfolio
        from polystation.trading.execution import ExecutionEngine

        om = OrderManager()
        portfolio = Portfolio()
        risk = RiskGuard(RiskConfig(max_stake_per_trade=500.0))
        engine = ExecutionEngine(
            None, om, portfolio, risk_guard=risk  # type: ignore[arg-type]
        )
        engine.set_dry_run(True)

        order = om.create_order(
            token_id="tok-bbb", side="BUY", price=0.5, size=10.0  # value = 5 < 500
        )
        result = engine.submit_order(order)

        assert result is not None
        assert result.get("dry_run") is True
        assert order.status == OrderStatus.FILLED

    def test_loss_recorded_after_fill(self) -> None:
        from polystation.core.orders import OrderManager
        from polystation.core.portfolio import Portfolio
        from polystation.trading.execution import ExecutionEngine

        om = OrderManager()
        portfolio = Portfolio()
        risk = RiskGuard()
        engine = ExecutionEngine(
            None, om, portfolio, risk_guard=risk  # type: ignore[arg-type]
        )
        engine.set_dry_run(True)

        # Buy first
        buy = om.create_order(token_id="tok-ccc", side="BUY", price=0.8, size=10.0)
        engine.submit_order(buy)

        # Sell at a loss (lower price)
        sell = om.create_order(token_id="tok-ccc", side="SELL", price=0.5, size=10.0)
        engine.submit_order(sell)

        # The loss should have been recorded
        assert risk.daily_loss < 0
