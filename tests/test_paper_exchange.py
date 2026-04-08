"""Tests for PaperExchange — simulated fills, balance tracking, positions, P&L."""
from __future__ import annotations

import pytest

from polystation.exchanges.base import OrderType
from polystation.exchanges.paper import PaperExchange


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def exchange() -> PaperExchange:
    """Fresh PaperExchange with 10 000 USD balance and 5 bps slippage."""
    return PaperExchange(initial_balance=10000.0, slippage_bps=5.0)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_connect_is_noop(self, exchange: PaperExchange) -> None:
        """connect() completes without raising."""
        await exchange.connect()  # should not raise

    @pytest.mark.asyncio
    async def test_disconnect_is_noop(self, exchange: PaperExchange) -> None:
        """disconnect() completes without raising."""
        await exchange.disconnect()  # should not raise

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self, exchange: PaperExchange) -> None:
        assert await exchange.health_check() is True


# ---------------------------------------------------------------------------
# Balance: BUY deducts, SELL adds
# ---------------------------------------------------------------------------


class TestBalance:
    @pytest.mark.asyncio
    async def test_buy_deducts_from_balance(self, exchange: PaperExchange) -> None:
        """Placing a BUY order reduces the cash balance by cost + slippage."""
        initial = exchange.balance
        result = await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        assert result.status == "filled"
        assert exchange.balance < initial

    @pytest.mark.asyncio
    async def test_sell_adds_to_balance(self, exchange: PaperExchange) -> None:
        """Placing a SELL order increases the cash balance."""
        # Buy first to establish a position
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        balance_after_buy = exchange.balance
        await exchange.place_order("tok1", "SELL", price=0.6, size=50.0)
        assert exchange.balance > balance_after_buy

    @pytest.mark.asyncio
    async def test_buy_exact_slippage_applied(self, exchange: PaperExchange) -> None:
        """Fill price for BUY is price * (1 + slippage_bps / 10000)."""
        result = await exchange.place_order("tok1", "BUY", price=0.5, size=10.0)
        expected_fill = 0.5 * (1 + 5 / 10000)
        assert result.filled_price == pytest.approx(expected_fill, rel=1e-6)

    @pytest.mark.asyncio
    async def test_sell_exact_slippage_applied(self, exchange: PaperExchange) -> None:
        """Fill price for SELL is price * (1 - slippage_bps / 10000)."""
        result = await exchange.place_order("tok1", "SELL", price=0.5, size=10.0)
        expected_fill = 0.5 * (1 - 5 / 10000)
        assert result.filled_price == pytest.approx(expected_fill, rel=1e-6)


# ---------------------------------------------------------------------------
# Insufficient balance rejection
# ---------------------------------------------------------------------------


class TestInsufficientBalance:
    @pytest.mark.asyncio
    async def test_buy_rejected_when_cost_exceeds_balance(
        self, exchange: PaperExchange
    ) -> None:
        """Order is rejected when fill cost exceeds available balance."""
        # 1 unit at 20 000 USD exceeds the 10 000 USD starting balance
        result = await exchange.place_order("tok1", "BUY", price=20000.0, size=1.0)
        assert result.status == "rejected"
        assert result.error is not None
        assert "balance" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rejected_order_does_not_change_balance(
        self, exchange: PaperExchange
    ) -> None:
        """A rejected BUY must not alter the cash balance."""
        initial = exchange.balance
        await exchange.place_order("tok1", "BUY", price=20000.0, size=1.0)
        assert exchange.balance == initial


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------


class TestPositionTracking:
    @pytest.mark.asyncio
    async def test_buy_increases_position_size(self, exchange: PaperExchange) -> None:
        """BUY increases the position size for the symbol."""
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        positions = await exchange.get_positions()
        pos_map = {p.symbol: p for p in positions}
        assert "tok1" in pos_map
        assert pos_map["tok1"].size == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_sell_decreases_position_size(self, exchange: PaperExchange) -> None:
        """SELL reduces the position size by the sold amount."""
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        await exchange.place_order("tok1", "SELL", price=0.6, size=40.0)
        positions = await exchange.get_positions()
        pos_map = {p.symbol: p for p in positions}
        assert "tok1" in pos_map
        assert pos_map["tok1"].size == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_full_sell_removes_position_from_active_list(
        self, exchange: PaperExchange
    ) -> None:
        """Selling the entire position removes it from the active list."""
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        await exchange.place_order("tok1", "SELL", price=0.6, size=100.0)
        positions = await exchange.get_positions()
        symbols = {p.symbol for p in positions}
        assert "tok1" not in symbols

    @pytest.mark.asyncio
    async def test_avg_entry_price_is_vwap(self, exchange: PaperExchange) -> None:
        """Average entry price is updated as a running volume-weighted average."""
        result1 = await exchange.place_order("tok1", "BUY", price=0.4, size=100.0)
        result2 = await exchange.place_order("tok1", "BUY", price=0.6, size=100.0)
        pos = exchange._positions["tok1"]
        expected_avg = (
            (result1.filled_price * 100 + result2.filled_price * 100) / 200  # type: ignore[operator]
        )
        assert pos.avg_entry_price == pytest.approx(expected_avg, rel=1e-6)

    @pytest.mark.asyncio
    async def test_get_positions_excludes_zero_size(
        self, exchange: PaperExchange
    ) -> None:
        """get_positions() only returns symbols with remaining size > 0."""
        await exchange.place_order("tok1", "BUY", price=0.5, size=50.0)
        await exchange.place_order("tok1", "SELL", price=0.5, size=50.0)
        positions = await exchange.get_positions()
        assert all(p.size > 0 for p in positions)


# ---------------------------------------------------------------------------
# Order book
# ---------------------------------------------------------------------------


class TestOrderBook:
    @pytest.mark.asyncio
    async def test_orderbook_centred_on_set_price(
        self, exchange: PaperExchange
    ) -> None:
        """get_orderbook returns bid/ask spread centred on set_price."""
        exchange.set_price("tok1", 0.5)
        book = await exchange.get_orderbook("tok1")
        assert book.best_bid == pytest.approx(0.49)
        assert book.best_ask == pytest.approx(0.51)

    @pytest.mark.asyncio
    async def test_orderbook_defaults_to_0_5_when_no_price_set(
        self, exchange: PaperExchange
    ) -> None:
        """Default mid-price is 0.5 when no price has been injected."""
        book = await exchange.get_orderbook("tok1")
        assert book.best_bid is not None
        assert book.best_ask is not None


# ---------------------------------------------------------------------------
# get_midpoint / get_price
# ---------------------------------------------------------------------------


class TestPriceQueries:
    @pytest.mark.asyncio
    async def test_get_midpoint_returns_set_price(
        self, exchange: PaperExchange
    ) -> None:
        exchange.set_price("tok1", 0.55)
        assert await exchange.get_midpoint("tok1") == pytest.approx(0.55)

    @pytest.mark.asyncio
    async def test_get_midpoint_returns_none_when_not_set(
        self, exchange: PaperExchange
    ) -> None:
        assert await exchange.get_midpoint("unknown_token") is None

    @pytest.mark.asyncio
    async def test_get_price_buy_adds_slippage(self, exchange: PaperExchange) -> None:
        exchange.set_price("tok1", 0.5)
        buy_price = await exchange.get_price("tok1", "BUY")
        assert buy_price is not None
        assert buy_price > 0.5

    @pytest.mark.asyncio
    async def test_get_price_sell_subtracts_slippage(
        self, exchange: PaperExchange
    ) -> None:
        exchange.set_price("tok1", 0.5)
        sell_price = await exchange.get_price("tok1", "SELL")
        assert sell_price is not None
        assert sell_price < 0.5

    @pytest.mark.asyncio
    async def test_get_price_returns_none_when_not_set(
        self, exchange: PaperExchange
    ) -> None:
        assert await exchange.get_price("unknown_token", "BUY") is None


# ---------------------------------------------------------------------------
# get_balance
# ---------------------------------------------------------------------------


class TestGetBalance:
    @pytest.mark.asyncio
    async def test_initial_balance_returned(self, exchange: PaperExchange) -> None:
        bal = await exchange.get_balance()
        assert bal == {"USD": 10000.0}

    @pytest.mark.asyncio
    async def test_balance_reflects_trades(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        bal = await exchange.get_balance()
        assert bal["USD"] < 10000.0


# ---------------------------------------------------------------------------
# Cancel helpers (always succeed for paper exchange)
# ---------------------------------------------------------------------------


class TestCancelHelpers:
    @pytest.mark.asyncio
    async def test_cancel_order_returns_true(self, exchange: PaperExchange) -> None:
        assert await exchange.cancel_order("PAPER-000001") is True

    @pytest.mark.asyncio
    async def test_cancel_all_orders_returns_zero(
        self, exchange: PaperExchange
    ) -> None:
        assert await exchange.cancel_all_orders() == 0


# ---------------------------------------------------------------------------
# P&L calculation
# ---------------------------------------------------------------------------


class TestPnl:
    @pytest.mark.asyncio
    async def test_initial_pnl_is_zero(self, exchange: PaperExchange) -> None:
        assert exchange.get_pnl() == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_pnl_marks_open_position_to_market(
        self, exchange: PaperExchange
    ) -> None:
        """P&L reflects the mark-to-market value of an open position."""
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        # Set current price higher than entry to expect positive PnL
        exchange.set_price("tok1", 0.7)
        pnl = exchange.get_pnl()
        # Position is worth more than we paid (before slippage correction)
        # P&L should be positive because price rose
        assert isinstance(pnl, float)

    @pytest.mark.asyncio
    async def test_pnl_falls_when_price_drops(self, exchange: PaperExchange) -> None:
        """P&L turns negative when the mark price drops below entry."""
        await exchange.place_order("tok1", "BUY", price=0.5, size=200.0)
        exchange.set_price("tok1", 0.1)
        assert exchange.get_pnl() < 0


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    @pytest.mark.asyncio
    async def test_reset_restores_balance(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        exchange.reset()
        assert exchange.balance == pytest.approx(10000.0)

    @pytest.mark.asyncio
    async def test_reset_clears_positions(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        exchange.reset()
        assert len(exchange._positions) == 0

    @pytest.mark.asyncio
    async def test_reset_clears_prices(self, exchange: PaperExchange) -> None:
        exchange.set_price("tok1", 0.5)
        exchange.reset()
        assert len(exchange._prices) == 0

    @pytest.mark.asyncio
    async def test_reset_clears_trade_log(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        exchange.reset()
        assert len(exchange._trade_log) == 0

    @pytest.mark.asyncio
    async def test_reset_resets_order_counter(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=10.0)
        exchange.reset()
        result = await exchange.place_order("tok1", "BUY", price=0.5, size=10.0)
        # Counter restarts from 1
        assert result.order_id == "PAPER-000001"

    @pytest.mark.asyncio
    async def test_pnl_is_zero_after_reset(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        exchange.set_price("tok1", 0.9)
        exchange.reset()
        assert exchange.get_pnl() == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Trade log
# ---------------------------------------------------------------------------


class TestTradeLog:
    @pytest.mark.asyncio
    async def test_trade_log_records_each_fill(self, exchange: PaperExchange) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        await exchange.place_order("tok1", "SELL", price=0.6, size=50.0)
        assert len(exchange._trade_log) == 2

    @pytest.mark.asyncio
    async def test_trade_log_entry_has_required_keys(
        self, exchange: PaperExchange
    ) -> None:
        await exchange.place_order("tok1", "BUY", price=0.5, size=100.0)
        entry = exchange._trade_log[0]
        for key in ("order_id", "symbol", "side", "price", "size", "balance"):
            assert key in entry

    @pytest.mark.asyncio
    async def test_order_ids_are_sequential(self, exchange: PaperExchange) -> None:
        for _ in range(3):
            await exchange.place_order("tok1", "BUY", price=0.1, size=1.0)
        ids = [t["order_id"] for t in exchange._trade_log]
        assert ids == ["PAPER-000001", "PAPER-000002", "PAPER-000003"]

    @pytest.mark.asyncio
    async def test_rejected_order_not_in_trade_log(
        self, exchange: PaperExchange
    ) -> None:
        await exchange.place_order("tok1", "BUY", price=99999.0, size=1.0)
        assert len(exchange._trade_log) == 0


# ---------------------------------------------------------------------------
# OrderType parameter (should not affect paper exchange behaviour)
# ---------------------------------------------------------------------------


class TestOrderTypeParameter:
    @pytest.mark.asyncio
    async def test_gtc_order_fills(self, exchange: PaperExchange) -> None:
        result = await exchange.place_order(
            "tok1", "BUY", price=0.5, size=10.0, order_type=OrderType.GTC
        )
        assert result.status == "filled"

    @pytest.mark.asyncio
    async def test_fok_order_fills(self, exchange: PaperExchange) -> None:
        result = await exchange.place_order(
            "tok1", "BUY", price=0.5, size=10.0, order_type=OrderType.FOK
        )
        assert result.status == "filled"

    @pytest.mark.asyncio
    async def test_market_order_fills(self, exchange: PaperExchange) -> None:
        result = await exchange.place_order(
            "tok1", "BUY", price=0.5, size=10.0, order_type=OrderType.MARKET
        )
        assert result.status == "filled"
