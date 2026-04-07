"""Tests for portfolio tracking, order management, and execution engine."""
from __future__ import annotations

import pytest

from polystation.core.orders import Order, OrderManager, OrderStatus
from polystation.core.portfolio import Portfolio, Position
from polystation.trading.execution import ExecutionEngine


# ---------------------------------------------------------------------------
# Helpers / shared constants
# ---------------------------------------------------------------------------

TOKEN_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MARKET_1 = "market-condition-id-001"
MARKET_2 = "market-condition-id-002"


# ===========================================================================
# Position tests
# ===========================================================================


class TestPositionCostBasis:
    """cost_basis = size * avg_entry_price."""

    def test_cost_basis_basic(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5,
        )
        assert pos.cost_basis == pytest.approx(50.0)

    def test_cost_basis_zero_size(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=0.0, avg_entry_price=0.5,
        )
        assert pos.cost_basis == pytest.approx(0.0)

    def test_cost_basis_fractional_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=200.0, avg_entry_price=0.25,
        )
        assert pos.cost_basis == pytest.approx(50.0)


class TestPositionMarketValue:
    """market_value = size * current_price, or None when price is unknown."""

    def test_market_value_none_when_no_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5,
        )
        assert pos.market_value is None

    def test_market_value_calculated_when_price_set(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5, current_price=0.7,
        )
        assert pos.market_value == pytest.approx(70.0)

    def test_market_value_at_entry_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=50.0, avg_entry_price=0.4, current_price=0.4,
        )
        assert pos.market_value == pytest.approx(pos.cost_basis)


class TestPositionUnrealizedPnl:
    """unrealized_pnl = market_value - cost_basis."""

    def test_unrealized_pnl_none_when_no_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5,
        )
        assert pos.unrealized_pnl is None

    def test_unrealized_pnl_positive(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5, current_price=0.7,
        )
        # market_value=70, cost_basis=50 → pnl=20
        assert pos.unrealized_pnl == pytest.approx(20.0)

    def test_unrealized_pnl_negative(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.6, current_price=0.4,
        )
        # market_value=40, cost_basis=60 → pnl=-20
        assert pos.unrealized_pnl == pytest.approx(-20.0)

    def test_unrealized_pnl_zero_at_entry_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5, current_price=0.5,
        )
        assert pos.unrealized_pnl == pytest.approx(0.0)


class TestPositionUnrealizedPnlPct:
    """unrealized_pnl_pct = (pnl / cost_basis) * 100."""

    def test_pnl_pct_none_when_no_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5,
        )
        assert pos.unrealized_pnl_pct is None

    def test_pnl_pct_none_when_cost_basis_zero(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=0.0, avg_entry_price=0.0, current_price=0.5,
        )
        assert pos.unrealized_pnl_pct is None

    def test_pnl_pct_positive(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5, current_price=0.7,
        )
        # pnl=20, cost_basis=50 → 40%
        assert pos.unrealized_pnl_pct == pytest.approx(40.0)

    def test_pnl_pct_negative(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.8, current_price=0.4,
        )
        # pnl=-40, cost_basis=80 → -50%
        assert pos.unrealized_pnl_pct == pytest.approx(-50.0)

    def test_pnl_pct_zero_at_entry_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=50.0, avg_entry_price=0.6, current_price=0.6,
        )
        assert pos.unrealized_pnl_pct == pytest.approx(0.0)


class TestPositionToDict:
    """to_dict() must contain all documented keys."""

    def test_to_dict_has_all_keys(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=100.0, avg_entry_price=0.5, current_price=0.6,
        )
        result = pos.to_dict()
        expected_keys = {
            "token_id", "market_id", "outcome", "side", "size",
            "avg_entry_price", "current_price", "cost_basis",
            "market_value", "unrealized_pnl", "unrealized_pnl_pct",
        }
        assert expected_keys.issubset(result.keys())

    def test_to_dict_values_match_properties(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="NO",
            side="BUY", size=80.0, avg_entry_price=0.3, current_price=0.45,
        )
        d = pos.to_dict()
        assert d["token_id"] == TOKEN_A
        assert d["market_id"] == MARKET_1
        assert d["outcome"] == "NO"
        assert d["side"] == "BUY"
        assert d["size"] == pytest.approx(80.0)
        assert d["avg_entry_price"] == pytest.approx(0.3)
        assert d["current_price"] == pytest.approx(0.45)
        assert d["cost_basis"] == pytest.approx(pos.cost_basis)
        assert d["market_value"] == pytest.approx(pos.market_value)
        assert d["unrealized_pnl"] == pytest.approx(pos.unrealized_pnl)
        assert d["unrealized_pnl_pct"] == pytest.approx(pos.unrealized_pnl_pct)

    def test_to_dict_none_fields_when_no_price(self) -> None:
        pos = Position(
            token_id=TOKEN_A, market_id=MARKET_1, outcome="YES",
            side="BUY", size=50.0, avg_entry_price=0.5,
        )
        d = pos.to_dict()
        assert d["current_price"] is None
        assert d["market_value"] is None
        assert d["unrealized_pnl"] is None
        assert d["unrealized_pnl_pct"] is None


# ===========================================================================
# Portfolio tests
# ===========================================================================


class TestPortfolioRecordFillBuy:
    """BUY fills create or enlarge a position."""

    def test_buy_creates_position(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0, MARKET_1, "YES")
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.size == pytest.approx(100.0)

    def test_buy_sets_avg_entry_price(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0, MARKET_1, "YES")
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.avg_entry_price == pytest.approx(0.5)

    def test_buy_stores_market_id_and_outcome(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0, MARKET_1, "YES")
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.market_id == MARKET_1
        assert pos.outcome == "YES"

    def test_two_buys_recalculate_avg_entry_price(self) -> None:
        portfolio = Portfolio()
        # Buy 100 @ 0.4 → cost = 40
        portfolio.record_fill(TOKEN_A, "BUY", 0.4, 100.0)
        # Buy 100 @ 0.6 → cost = 60 → total cost 100, total size 200 → avg 0.5
        portfolio.record_fill(TOKEN_A, "BUY", 0.6, 100.0)
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.size == pytest.approx(200.0)
        assert pos.avg_entry_price == pytest.approx(0.5)

    def test_buy_increments_trade_count(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "BUY", 0.6, 50.0)
        assert portfolio.trade_count == 2

    def test_buy_different_tokens_tracked_independently(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0, MARKET_1, "YES")
        portfolio.record_fill(TOKEN_B, "BUY", 0.3, 200.0, MARKET_2, "NO")
        pos_a = portfolio.get_position(TOKEN_A)
        pos_b = portfolio.get_position(TOKEN_B)
        assert pos_a is not None and pos_b is not None
        assert pos_a.size == pytest.approx(100.0)
        assert pos_b.size == pytest.approx(200.0)
        assert pos_a.avg_entry_price == pytest.approx(0.5)
        assert pos_b.avg_entry_price == pytest.approx(0.3)


class TestPortfolioRecordFillSell:
    """SELL fills reduce a position and realize P&L."""

    def test_sell_reduces_position_size(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 40.0)
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.size == pytest.approx(60.0)

    def test_sell_realizes_positive_pnl(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 50.0)
        # pnl = (0.7 - 0.5) * 50 = 10.0
        assert portfolio.realized_pnl == pytest.approx(10.0)

    def test_sell_realizes_negative_pnl(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.8, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.5, 100.0)
        # pnl = (0.5 - 0.8) * 100 = -30.0
        assert portfolio.realized_pnl == pytest.approx(-30.0)

    def test_full_close_realizes_correct_pnl(self) -> None:
        """buy 100 @ 0.5, sell 100 @ 0.7 → realized_pnl = 20.0."""
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 100.0)
        assert portfolio.realized_pnl == pytest.approx(20.0)

    def test_full_close_zeroes_position_size(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 100.0)
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.size == pytest.approx(0.0)

    def test_sell_increments_trade_count(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 100.0)
        assert portfolio.trade_count == 2


class TestPortfolioUpdatePrice:
    """update_price() sets current_price on the matching position."""

    def test_update_price_changes_current_price(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.update_price(TOKEN_A, 0.75)
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.current_price == pytest.approx(0.75)

    def test_update_price_for_unknown_token_does_not_raise(self) -> None:
        portfolio = Portfolio()
        portfolio.update_price("nonexistent-token", 0.5)  # must not raise


class TestPortfolioAggregates:
    """total_unrealized_pnl, total_pnl, total_market_value."""

    def test_total_unrealized_pnl_single_position(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.update_price(TOKEN_A, 0.6)
        # pnl = (0.6 - 0.5) * 100 = 10
        assert portfolio.total_unrealized_pnl == pytest.approx(10.0)

    def test_total_unrealized_pnl_no_price_returns_zero(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        # No price pushed → contribute 0
        assert portfolio.total_unrealized_pnl == pytest.approx(0.0)

    def test_total_unrealized_pnl_sums_across_positions(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_B, "BUY", 0.3, 200.0)
        portfolio.update_price(TOKEN_A, 0.6)   # pnl = +10
        portfolio.update_price(TOKEN_B, 0.2)   # pnl = -20
        assert portfolio.total_unrealized_pnl == pytest.approx(-10.0)

    def test_total_pnl_equals_realized_plus_unrealized(self) -> None:
        portfolio = Portfolio()
        # Realize 20 on TOKEN_A
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 100.0)
        # Open position on TOKEN_B, no price yet
        portfolio.record_fill(TOKEN_B, "BUY", 0.4, 50.0)
        assert portfolio.total_pnl == pytest.approx(
            portfolio.realized_pnl + portfolio.total_unrealized_pnl
        )

    def test_total_market_value_sums_priced_positions(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_B, "BUY", 0.3, 200.0)
        portfolio.update_price(TOKEN_A, 0.6)   # mv = 60
        portfolio.update_price(TOKEN_B, 0.4)   # mv = 80
        assert portfolio.total_market_value == pytest.approx(140.0)

    def test_total_market_value_excludes_unpriced_positions(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_B, "BUY", 0.3, 200.0)
        portfolio.update_price(TOKEN_A, 0.6)   # mv = 60; TOKEN_B has no price
        assert portfolio.total_market_value == pytest.approx(60.0)


class TestPortfolioGetSummary:
    """get_summary() must contain all documented keys."""

    def test_summary_has_all_keys(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0, MARKET_1, "YES")
        summary = portfolio.get_summary()
        expected_keys = {
            "positions",
            "realized_pnl",
            "unrealized_pnl",
            "total_pnl",
            "total_market_value",
            "trade_count",
        }
        assert expected_keys.issubset(summary.keys())

    def test_summary_trade_count_matches(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_B, "BUY", 0.3, 50.0)
        summary = portfolio.get_summary()
        assert summary["trade_count"] == 2

    def test_summary_realized_pnl_after_sell(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        portfolio.record_fill(TOKEN_A, "SELL", 0.7, 100.0)
        summary = portfolio.get_summary()
        assert summary["realized_pnl"] == pytest.approx(20.0)

    def test_summary_positions_is_dict(self) -> None:
        portfolio = Portfolio()
        portfolio.record_fill(TOKEN_A, "BUY", 0.5, 100.0)
        summary = portfolio.get_summary()
        assert isinstance(summary["positions"], dict)

    def test_get_position_returns_none_for_unknown_token(self) -> None:
        portfolio = Portfolio()
        assert portfolio.get_position("totally-unknown-token") is None


# ===========================================================================
# Order tests
# ===========================================================================


class TestOrderProperties:
    """remaining_size and is_active on Order objects."""

    def test_remaining_size_full_unfilled(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
        )
        assert order.remaining_size == pytest.approx(100.0)

    def test_remaining_size_partially_filled(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0, filled_size=40.0,
        )
        assert order.remaining_size == pytest.approx(60.0)

    def test_remaining_size_fully_filled_is_zero(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0, filled_size=100.0,
        )
        assert order.remaining_size == pytest.approx(0.0)

    def test_is_active_true_for_pending(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.PENDING,
        )
        assert order.is_active is True

    def test_is_active_true_for_submitted(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.SUBMITTED,
        )
        assert order.is_active is True

    def test_is_active_true_for_partially_filled(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.PARTIALLY_FILLED,
        )
        assert order.is_active is True

    def test_is_active_false_for_filled(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.FILLED,
        )
        assert order.is_active is False

    def test_is_active_false_for_cancelled(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.CANCELLED,
        )
        assert order.is_active is False

    def test_is_active_false_for_rejected(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.REJECTED,
        )
        assert order.is_active is False

    def test_is_active_false_for_expired(self) -> None:
        order = Order(
            id="ORD-000001", token_id=TOKEN_A,
            side="BUY", price=0.5, size=100.0,
            status=OrderStatus.EXPIRED,
        )
        assert order.is_active is False


class TestOrderStatusEnum:
    """All seven OrderStatus enum values exist and have the right string values."""

    def test_pending_value(self) -> None:
        assert OrderStatus.PENDING.value == "pending"

    def test_submitted_value(self) -> None:
        assert OrderStatus.SUBMITTED.value == "submitted"

    def test_filled_value(self) -> None:
        assert OrderStatus.FILLED.value == "filled"

    def test_partially_filled_value(self) -> None:
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"

    def test_cancelled_value(self) -> None:
        assert OrderStatus.CANCELLED.value == "cancelled"

    def test_rejected_value(self) -> None:
        assert OrderStatus.REJECTED.value == "rejected"

    def test_expired_value(self) -> None:
        assert OrderStatus.EXPIRED.value == "expired"


# ===========================================================================
# OrderManager tests
# ===========================================================================


class TestOrderManagerCreateOrder:
    """create_order() returns a properly initialized Order."""

    def test_create_order_returns_order_instance(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert isinstance(order, Order)

    def test_create_order_auto_generates_id(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert order.id != ""
        assert order.id.startswith("ORD-")

    def test_create_order_ids_are_unique(self) -> None:
        mgr = OrderManager()
        ids = {mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0).id for _ in range(5)}
        assert len(ids) == 5

    def test_create_order_ids_are_sequential(self) -> None:
        mgr = OrderManager()
        first = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        second = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        # Numeric suffix of second > first
        n1 = int(first.id.split("-")[1])
        n2 = int(second.id.split("-")[1])
        assert n2 == n1 + 1

    def test_create_order_initial_status_is_pending(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert order.status == OrderStatus.PENDING

    def test_create_order_stores_parameters(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(
            TOKEN_A, "SELL", 0.7, 50.0,
            market_id=MARKET_1, kernel_name="scalper", order_type="FOK",
        )
        assert order.token_id == TOKEN_A
        assert order.side == "SELL"
        assert order.price == pytest.approx(0.7)
        assert order.size == pytest.approx(50.0)
        assert order.market_id == MARKET_1
        assert order.kernel_name == "scalper"
        assert order.order_type == "FOK"

    def test_create_order_initial_filled_size_zero(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert order.filled_size == pytest.approx(0.0)

    def test_create_order_registered_in_manager(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert mgr.get_order(order.id) is order


class TestOrderManagerUpdateStatus:
    """update_status() transitions the order state."""

    def test_update_status_changes_status(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.update_status(order.id, OrderStatus.SUBMITTED)
        assert order.status == OrderStatus.SUBMITTED

    def test_update_status_sets_updated_at(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert order.updated_at == ""
        mgr.update_status(order.id, OrderStatus.SUBMITTED)
        assert order.updated_at != ""

    def test_update_status_stores_server_order_id(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.update_status(order.id, OrderStatus.SUBMITTED, server_order_id="SRV-XYZ")
        assert order.server_order_id == "SRV-XYZ"

    def test_update_status_stores_error(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.update_status(order.id, OrderStatus.REJECTED, error="Insufficient funds")
        assert order.error == "Insufficient funds"

    def test_update_status_returns_none_for_unknown_id(self) -> None:
        mgr = OrderManager()
        result = mgr.update_status("ORD-999999", OrderStatus.CANCELLED)
        assert result is None

    def test_update_status_returns_order_on_success(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        result = mgr.update_status(order.id, OrderStatus.SUBMITTED)
        assert result is order


class TestOrderManagerRecordFill:
    """record_fill() updates fill stats and transitions status."""

    def test_record_fill_updates_filled_size(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.record_fill(order.id, 0.5, 60.0)
        assert order.filled_size == pytest.approx(60.0)

    def test_partial_fill_sets_partially_filled_status(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.record_fill(order.id, 0.5, 40.0)
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_full_fill_sets_filled_status(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.record_fill(order.id, 0.5, 100.0)
        assert order.status == OrderStatus.FILLED

    def test_full_fill_via_two_partials(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.record_fill(order.id, 0.5, 60.0)
        mgr.record_fill(order.id, 0.5, 40.0)
        assert order.status == OrderStatus.FILLED
        assert order.filled_size == pytest.approx(100.0)

    def test_record_fill_calculates_vwap_avg_fill_price(self) -> None:
        """Two fills at different prices → volume-weighted average."""
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.record_fill(order.id, 0.4, 50.0)   # cost = 20
        mgr.record_fill(order.id, 0.6, 50.0)   # cost = 30 → avg = 0.5
        assert order.avg_fill_price == pytest.approx(0.5)

    def test_record_fill_returns_none_for_unknown_id(self) -> None:
        mgr = OrderManager()
        result = mgr.record_fill("ORD-999999", 0.5, 100.0)
        assert result is None

    def test_record_fill_returns_order_on_success(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        result = mgr.record_fill(order.id, 0.5, 100.0)
        assert result is order


class TestOrderManagerGetActiveOrders:
    """get_active_orders() filters to live orders only."""

    def test_pending_order_is_active(self) -> None:
        mgr = OrderManager()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert len(mgr.get_active_orders()) == 1

    def test_filled_order_is_not_active(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.record_fill(order.id, 0.5, 100.0)
        assert len(mgr.get_active_orders()) == 0

    def test_cancelled_order_is_not_active(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.update_status(order.id, OrderStatus.CANCELLED)
        assert len(mgr.get_active_orders()) == 0

    def test_get_active_orders_kernel_name_filter(self) -> None:
        mgr = OrderManager()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0, kernel_name="alpha")
        mgr.create_order(TOKEN_B, "BUY", 0.3, 50.0, kernel_name="beta")
        active_alpha = mgr.get_active_orders(kernel_name="alpha")
        assert len(active_alpha) == 1
        assert active_alpha[0].kernel_name == "alpha"

    def test_get_active_orders_all_returned_when_no_filter(self) -> None:
        mgr = OrderManager()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0, kernel_name="alpha")
        mgr.create_order(TOKEN_B, "BUY", 0.3, 50.0, kernel_name="beta")
        assert len(mgr.get_active_orders()) == 2

    def test_get_active_orders_empty_when_none_active(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.update_status(order.id, OrderStatus.REJECTED)
        assert mgr.get_active_orders() == []


class TestOrderManagerGetOrder:
    """get_order() and get_all_orders() query methods."""

    def test_get_order_returns_correct_order(self) -> None:
        mgr = OrderManager()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        fetched = mgr.get_order(order.id)
        assert fetched is order

    def test_get_order_returns_none_for_unknown_id(self) -> None:
        mgr = OrderManager()
        assert mgr.get_order("ORD-999999") is None

    def test_get_all_orders_returns_all(self) -> None:
        mgr = OrderManager()
        for _ in range(5):
            mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        assert len(mgr.get_all_orders()) == 5

    def test_get_all_orders_respects_limit(self) -> None:
        mgr = OrderManager()
        for _ in range(10):
            mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        result = mgr.get_all_orders(limit=3)
        assert len(result) == 3


class TestOrderManagerGetSummary:
    """get_summary() produces the documented keys and correct counts."""

    def test_summary_has_all_keys(self) -> None:
        mgr = OrderManager()
        summary = mgr.get_summary()
        expected_keys = {"total_orders", "active_orders", "filled_orders", "orders"}
        assert expected_keys.issubset(summary.keys())

    def test_summary_counts_correct(self) -> None:
        mgr = OrderManager()
        order1 = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        order2 = mgr.create_order(TOKEN_B, "BUY", 0.3, 50.0)
        mgr.record_fill(order1.id, 0.5, 100.0)
        summary = mgr.get_summary()
        assert summary["total_orders"] == 2
        assert summary["active_orders"] == 1    # order2 still pending
        assert summary["filled_orders"] == 1    # order1

    def test_summary_orders_list_is_list(self) -> None:
        mgr = OrderManager()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        summary = mgr.get_summary()
        assert isinstance(summary["orders"], list)

    def test_summary_empty_manager(self) -> None:
        mgr = OrderManager()
        summary = mgr.get_summary()
        assert summary["total_orders"] == 0
        assert summary["active_orders"] == 0
        assert summary["filled_orders"] == 0


# ===========================================================================
# ExecutionEngine tests (dry_run mode only)
# ===========================================================================


def _make_engine() -> tuple[ExecutionEngine, OrderManager, Portfolio]:
    """Return a dry-run ExecutionEngine together with its real collaborators.

    The ``clob_client`` is passed as None because dry_run mode never calls
    any method on it.
    """
    mgr = OrderManager()
    portfolio = Portfolio()
    engine = ExecutionEngine(clob_client=None, order_manager=mgr, portfolio=portfolio)  # type: ignore[arg-type]
    engine.set_dry_run(True)
    return engine, mgr, portfolio


class TestExecutionEngineDryRunSubmit:
    """submit_order() in dry_run mode."""

    def test_submit_returns_dict(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        result = engine.submit_order(order)
        assert isinstance(result, dict)

    def test_submit_includes_dry_run_flag(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        result = engine.submit_order(order)
        assert result is not None
        assert result.get("dry_run") is True

    def test_submit_marks_order_as_filled(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        engine.submit_order(order)
        assert order.status == OrderStatus.FILLED

    def test_submit_records_portfolio_position(self) -> None:
        engine, mgr, portfolio = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0, market_id=MARKET_1)
        engine.submit_order(order)
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.size == pytest.approx(100.0)

    def test_submit_portfolio_avg_price_matches_order_price(self) -> None:
        engine, mgr, portfolio = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.65, 200.0)
        engine.submit_order(order)
        pos = portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.avg_entry_price == pytest.approx(0.65)

    def test_submit_increments_portfolio_trade_count(self) -> None:
        engine, mgr, portfolio = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        engine.submit_order(order)
        assert portfolio.trade_count == 1

    def test_submit_sell_realizes_pnl(self) -> None:
        engine, mgr, portfolio = _make_engine()
        buy_order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        engine.submit_order(buy_order)
        sell_order = mgr.create_order(TOKEN_A, "SELL", 0.7, 100.0)
        engine.submit_order(sell_order)
        assert portfolio.realized_pnl == pytest.approx(20.0)


class TestExecutionEngineDryRunCancel:
    """cancel_order() in dry_run mode."""

    def test_cancel_returns_true(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        result = engine.cancel_order(order)
        assert result is True

    def test_cancel_marks_order_as_cancelled(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        engine.cancel_order(order)
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_active_order_removed_from_active_list(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        engine.cancel_order(order)
        assert order not in mgr.get_active_orders()


class TestExecutionEngineCancelAll:
    """cancel_all() in dry_run mode."""

    def test_cancel_all_cancels_all_active_orders(self) -> None:
        engine, mgr, _ = _make_engine()
        for _ in range(3):
            mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        cancelled = engine.cancel_all()
        assert cancelled == 3
        assert len(mgr.get_active_orders()) == 0

    def test_cancel_all_returns_count_cancelled(self) -> None:
        engine, mgr, _ = _make_engine()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        mgr.create_order(TOKEN_B, "BUY", 0.3, 50.0)
        count = engine.cancel_all()
        assert count == 2

    def test_cancel_all_with_kernel_name_only_cancels_matching(self) -> None:
        engine, mgr, _ = _make_engine()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0, kernel_name="alpha")
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0, kernel_name="alpha")
        mgr.create_order(TOKEN_B, "BUY", 0.3, 50.0, kernel_name="beta")
        cancelled = engine.cancel_all(kernel_name="alpha")
        assert cancelled == 2
        # beta order must still be active
        beta_active = mgr.get_active_orders(kernel_name="beta")
        assert len(beta_active) == 1

    def test_cancel_all_returns_zero_when_no_active_orders(self) -> None:
        engine, mgr, _ = _make_engine()
        order = mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0)
        engine.submit_order(order)   # fills it → no longer active
        count = engine.cancel_all()
        assert count == 0

    def test_cancel_all_kernel_filter_no_match_returns_zero(self) -> None:
        engine, mgr, _ = _make_engine()
        mgr.create_order(TOKEN_A, "BUY", 0.5, 100.0, kernel_name="alpha")
        count = engine.cancel_all(kernel_name="no-such-kernel")
        assert count == 0
        # alpha order must be untouched
        assert len(mgr.get_active_orders()) == 1
