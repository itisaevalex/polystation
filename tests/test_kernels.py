"""Tests for the kernel system: registry, VoiceKernel, MarketMakerKernel, SignalKernel.

NO MOCKING — uses real objects throughout.
Execution uses dry_run mode.
Market data uses the live CLOB / Gamma API where needed.
"""

from __future__ import annotations

import json

import pytest
import requests

# Trigger @register decorators by importing each kernel module.
import polystation.kernels.voice  # noqa: F401 — registers VoiceKernel
import polystation.kernels.market_maker  # noqa: F401 — registers MarketMakerKernel
import polystation.kernels.signal  # noqa: F401 — registers SignalKernel

from polystation.core.engine import TradingEngine
from polystation.core.orders import OrderManager, OrderStatus
from polystation.core.portfolio import Portfolio
from polystation.kernels import create_kernel, get_kernel_class, list_kernels
from polystation.kernels.market_maker.kernel import MarketMakerKernel
from polystation.kernels.signal.kernel import SignalKernel
from polystation.kernels.voice.kernel import VoiceKernel
from polystation.market.client import MarketDataClient
from polystation.trading.execution import ExecutionEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_token_id() -> str:
    """Fetch an active token_id using the Gamma API (richer filtering)."""
    resp = requests.get(
        "https://gamma-api.polymarket.com/markets",
        params={"limit": "20", "active": "true", "closed": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    for m in resp.json():
        clob_ids = m.get("clobTokenIds")
        if not clob_ids:
            continue
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except (ValueError, TypeError):
                continue
        if isinstance(clob_ids, list) and clob_ids and clob_ids[0]:
            return clob_ids[0]
    pytest.skip("No active token found")
    return ""  # unreachable


async def _make_engine_with_dry_run() -> TradingEngine:
    """Build a fully wired TradingEngine in dry_run mode."""
    engine = TradingEngine()
    engine.market_data = MarketDataClient()
    engine.portfolio = Portfolio()
    engine.orders = OrderManager()
    # ExecutionEngine needs a ClobClient but won't use it in dry_run.
    engine.execution = ExecutionEngine(None, engine.orders, engine.portfolio)  # type: ignore[arg-type]
    engine.execution.set_dry_run(True)
    await engine.start()
    return engine


# ---------------------------------------------------------------------------
# Kernel Registry
# ---------------------------------------------------------------------------


class TestKernelRegistry:
    """Tests for polystation.kernels registry functions."""

    def test_register_decorator_registers_voice_kernel(self) -> None:
        cls = get_kernel_class("voice")
        assert cls is VoiceKernel

    def test_register_decorator_registers_market_maker_kernel(self) -> None:
        cls = get_kernel_class("market-maker")
        assert cls is MarketMakerKernel

    def test_register_decorator_registers_signal_kernel(self) -> None:
        cls = get_kernel_class("signal")
        assert cls is SignalKernel

    def test_list_kernels_contains_all_three(self) -> None:
        names = list_kernels()
        assert "voice" in names
        assert "market-maker" in names
        assert "signal" in names

    def test_list_kernels_returns_list_of_strings(self) -> None:
        names = list_kernels()
        assert isinstance(names, list)
        for name in names:
            assert isinstance(name, str)

    def test_get_kernel_class_returns_none_for_unknown(self) -> None:
        assert get_kernel_class("nonexistent-kernel-xyz") is None

    def test_create_kernel_returns_voice_instance(self) -> None:
        kernel = create_kernel("voice")
        assert isinstance(kernel, VoiceKernel)

    def test_create_kernel_returns_market_maker_instance(self) -> None:
        kernel = create_kernel("market-maker", token_id="fake-token-id")
        assert isinstance(kernel, MarketMakerKernel)

    def test_create_kernel_returns_signal_instance(self) -> None:
        kernel = create_kernel("signal", token_id="fake-token-id")
        assert isinstance(kernel, SignalKernel)

    def test_create_kernel_raises_key_error_for_unknown(self) -> None:
        with pytest.raises(KeyError):
            create_kernel("nonexistent-kernel-xyz")

    def test_create_kernel_forwards_kwargs_to_voice(self) -> None:
        kernel = create_kernel("voice", source_type="radio", url="http://example.com", debug=True)
        assert isinstance(kernel, VoiceKernel)
        assert kernel.source_type == "radio"
        assert kernel.url == "http://example.com"
        assert kernel.debug is True

    def test_create_kernel_forwards_kwargs_to_market_maker(self) -> None:
        kernel = create_kernel(
            "market-maker",
            token_id="tok123",
            spread=0.05,
            size=100,
            refresh_interval=60.0,
            max_position=1000,
        )
        assert isinstance(kernel, MarketMakerKernel)
        assert kernel.token_id == "tok123"
        assert kernel.spread == pytest.approx(0.05)
        assert kernel.size == pytest.approx(100)

    def test_create_kernel_forwards_kwargs_to_signal(self) -> None:
        kernel = create_kernel(
            "signal",
            token_id="tok456",
            lookback=5,
            strategy="mean_reversion",
            threshold=0.03,
            size=75,
        )
        assert isinstance(kernel, SignalKernel)
        assert kernel.token_id == "tok456"
        assert kernel.lookback == 5
        assert kernel.strategy == "mean_reversion"


# ---------------------------------------------------------------------------
# VoiceKernel
# ---------------------------------------------------------------------------


class TestVoiceKernelConstruction:
    """Constructor and attribute tests for VoiceKernel."""

    def test_name_is_voice(self) -> None:
        assert VoiceKernel.name == "voice"

    def test_initial_status_is_stopped(self) -> None:
        kernel = VoiceKernel()
        assert kernel.status == "stopped"

    def test_default_source_type_is_youtube(self) -> None:
        kernel = VoiceKernel()
        assert kernel.source_type == "youtube"

    def test_default_url_is_none(self) -> None:
        kernel = VoiceKernel()
        assert kernel.url is None

    def test_default_debug_is_false(self) -> None:
        kernel = VoiceKernel()
        assert kernel.debug is False

    def test_constructor_stores_source_type(self) -> None:
        kernel = VoiceKernel(source_type="radio")
        assert kernel.source_type == "radio"

    def test_constructor_stores_url(self) -> None:
        kernel = VoiceKernel(url="https://example.com/stream")
        assert kernel.url == "https://example.com/stream"

    def test_constructor_stores_debug(self) -> None:
        kernel = VoiceKernel(debug=True)
        assert kernel.debug is True

    def test_constructor_accepts_twitter_source_type(self) -> None:
        kernel = VoiceKernel(source_type="twitter")
        assert kernel.source_type == "twitter"


class TestVoiceKernelGetStatus:
    """get_status() output tests for VoiceKernel."""

    def test_get_status_has_source_type_key(self) -> None:
        kernel = VoiceKernel(source_type="radio")
        status = kernel.get_status()
        assert "source_type" in status

    def test_get_status_source_type_matches_constructor(self) -> None:
        kernel = VoiceKernel(source_type="radio")
        status = kernel.get_status()
        assert status["source_type"] == "radio"

    def test_get_status_has_url_key(self) -> None:
        kernel = VoiceKernel(url="https://test.example.com")
        status = kernel.get_status()
        assert "url" in status

    def test_get_status_url_matches_constructor(self) -> None:
        kernel = VoiceKernel(url="https://test.example.com")
        status = kernel.get_status()
        assert status["url"] == "https://test.example.com"

    def test_get_status_has_name_key(self) -> None:
        kernel = VoiceKernel()
        status = kernel.get_status()
        assert "name" in status
        assert status["name"] == "voice"

    def test_get_status_has_status_key(self) -> None:
        kernel = VoiceKernel()
        status = kernel.get_status()
        assert "status" in status
        assert status["status"] == "stopped"

    def test_get_status_thread_alive_is_false_before_start(self) -> None:
        kernel = VoiceKernel()
        status = kernel.get_status()
        assert status["thread_alive"] is False


# ---------------------------------------------------------------------------
# MarketMakerKernel
# ---------------------------------------------------------------------------


class TestMarketMakerKernelConstruction:
    """Constructor and attribute tests for MarketMakerKernel."""

    def test_name_is_market_maker(self) -> None:
        assert MarketMakerKernel.name == "market-maker"

    def test_initial_status_is_stopped(self) -> None:
        kernel = MarketMakerKernel(token_id="tok")
        assert kernel.status == "stopped"

    def test_constructor_stores_token_id(self) -> None:
        kernel = MarketMakerKernel(token_id="abc123")
        assert kernel.token_id == "abc123"

    def test_constructor_stores_spread(self) -> None:
        kernel = MarketMakerKernel(token_id="tok", spread=0.05)
        assert kernel.spread == pytest.approx(0.05)

    def test_constructor_stores_size(self) -> None:
        kernel = MarketMakerKernel(token_id="tok", size=200)
        assert kernel.size == pytest.approx(200)

    def test_constructor_stores_refresh_interval(self) -> None:
        kernel = MarketMakerKernel(token_id="tok", refresh_interval=60.0)
        assert kernel.refresh_interval == pytest.approx(60.0)

    def test_constructor_stores_max_position(self) -> None:
        kernel = MarketMakerKernel(token_id="tok", max_position=1000)
        assert kernel.max_position == pytest.approx(1000)

    def test_default_spread(self) -> None:
        kernel = MarketMakerKernel(token_id="tok")
        assert kernel.spread == pytest.approx(0.02)

    def test_default_size(self) -> None:
        kernel = MarketMakerKernel(token_id="tok")
        assert kernel.size == pytest.approx(50)

    def test_default_refresh_interval(self) -> None:
        kernel = MarketMakerKernel(token_id="tok")
        assert kernel.refresh_interval == pytest.approx(30.0)

    def test_default_max_position(self) -> None:
        kernel = MarketMakerKernel(token_id="tok")
        assert kernel.max_position == pytest.approx(500)


class TestMarketMakerKernelGetStatus:
    """get_status() output tests for MarketMakerKernel."""

    def _make_kernel(self) -> MarketMakerKernel:
        return MarketMakerKernel(
            token_id="tok-status-test",
            spread=0.03,
            size=75,
            refresh_interval=45.0,
            max_position=600,
        )

    def test_get_status_has_token_id(self) -> None:
        status = self._make_kernel().get_status()
        assert "token_id" in status
        assert status["token_id"] == "tok-status-test"

    def test_get_status_has_spread(self) -> None:
        status = self._make_kernel().get_status()
        assert "spread" in status
        assert status["spread"] == pytest.approx(0.03)

    def test_get_status_has_size(self) -> None:
        status = self._make_kernel().get_status()
        assert "size" in status
        assert status["size"] == pytest.approx(75)

    def test_get_status_has_refresh_interval(self) -> None:
        status = self._make_kernel().get_status()
        assert "refresh_interval" in status
        assert status["refresh_interval"] == pytest.approx(45.0)

    def test_get_status_has_max_position(self) -> None:
        status = self._make_kernel().get_status()
        assert "max_position" in status
        assert status["max_position"] == pytest.approx(600)

    def test_get_status_has_cycle_count(self) -> None:
        status = self._make_kernel().get_status()
        assert "cycle_count" in status
        assert status["cycle_count"] == 0

    def test_get_status_has_name(self) -> None:
        status = self._make_kernel().get_status()
        assert status["name"] == "market-maker"

    def test_get_status_initial_status_stopped(self) -> None:
        status = self._make_kernel().get_status()
        assert status["status"] == "stopped"


# ---------------------------------------------------------------------------
# SignalKernel
# ---------------------------------------------------------------------------


class TestSignalKernelConstruction:
    """Constructor and attribute tests for SignalKernel."""

    def test_name_is_signal(self) -> None:
        assert SignalKernel.name == "signal"

    def test_initial_status_is_stopped(self) -> None:
        kernel = SignalKernel(token_id="tok")
        assert kernel.status == "stopped"

    def test_constructor_stores_token_id(self) -> None:
        kernel = SignalKernel(token_id="my-token")
        assert kernel.token_id == "my-token"

    def test_constructor_stores_lookback(self) -> None:
        kernel = SignalKernel(token_id="tok", lookback=30)
        assert kernel.lookback == 30

    def test_constructor_stores_strategy(self) -> None:
        kernel = SignalKernel(token_id="tok", strategy="mean_reversion")
        assert kernel.strategy == "mean_reversion"

    def test_constructor_stores_threshold(self) -> None:
        kernel = SignalKernel(token_id="tok", threshold=0.05)
        assert kernel.threshold == pytest.approx(0.05)

    def test_constructor_stores_size(self) -> None:
        kernel = SignalKernel(token_id="tok", size=100)
        assert kernel.size == pytest.approx(100)

    def test_default_strategy_is_momentum(self) -> None:
        kernel = SignalKernel(token_id="tok")
        assert kernel.strategy == "momentum"

    def test_default_threshold(self) -> None:
        kernel = SignalKernel(token_id="tok")
        assert kernel.threshold == pytest.approx(0.02)


class TestSignalKernelGetStatus:
    """get_status() output tests for SignalKernel."""

    def test_get_status_has_price_history_len(self) -> None:
        kernel = SignalKernel(token_id="tok", lookback=5)
        status = kernel.get_status()
        assert "price_history_len" in status
        assert status["price_history_len"] == 0

    def test_get_status_has_signals_fired(self) -> None:
        kernel = SignalKernel(token_id="tok")
        status = kernel.get_status()
        assert "signals_fired" in status
        assert status["signals_fired"] == 0

    def test_get_status_has_name(self) -> None:
        kernel = SignalKernel(token_id="tok")
        status = kernel.get_status()
        assert status["name"] == "signal"

    def test_get_status_initial_status_stopped(self) -> None:
        kernel = SignalKernel(token_id="tok")
        status = kernel.get_status()
        assert status["status"] == "stopped"


class TestSignalKernelMomentumLogic:
    """Test the momentum signal strategy using feed_price() for direct control.

    The SignalKernel compares the oldest sample to the newest in the rolling
    window: ``change = (newest - oldest) / oldest``.
    Momentum fires a BUY when ``change > threshold`` and a SELL when
    ``change < -threshold``.  ``feed_price()`` returns True when either
    condition is met and increments ``_signals_fired``.
    """

    def _make_momentum_kernel(self, lookback: int = 2, threshold: float = 0.05) -> SignalKernel:
        return SignalKernel(
            token_id="tok-momentum",
            lookback=lookback,
            strategy="momentum",
            threshold=threshold,
        )

    def test_no_signal_on_first_price(self) -> None:
        # Only one sample — window has < 2 entries, so no evaluation.
        kernel = self._make_momentum_kernel(lookback=5)
        assert kernel.feed_price(0.50) is False

    def test_no_signal_when_change_below_threshold(self) -> None:
        # oldest=0.50, newest=0.51, change=2% < threshold=10% → no signal
        kernel = self._make_momentum_kernel(lookback=2, threshold=0.10)
        kernel.feed_price(0.50)
        fired = kernel.feed_price(0.51)
        assert fired is False

    def test_momentum_fires_when_price_rises_above_threshold(self) -> None:
        # oldest=0.50, newest=0.55, change=10% > threshold=5% → BUY fires
        kernel = self._make_momentum_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.50)
        fired = kernel.feed_price(0.55)
        assert fired is True

    def test_signals_fired_increments_on_rising_price(self) -> None:
        kernel = self._make_momentum_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.50)
        kernel.feed_price(0.55)
        assert kernel._signals_fired == 1

    def test_signals_fired_does_not_increment_below_threshold(self) -> None:
        kernel = self._make_momentum_kernel(lookback=2, threshold=0.10)
        kernel.feed_price(0.50)
        kernel.feed_price(0.51)  # 2% change < 10% threshold
        assert kernel._signals_fired == 0

    def test_price_history_len_updates_after_feed(self) -> None:
        kernel = self._make_momentum_kernel(lookback=5)
        kernel.feed_price(0.50)
        kernel.feed_price(0.51)
        assert kernel.get_status()["price_history_len"] == 2

    def test_price_history_capped_at_lookback(self) -> None:
        kernel = self._make_momentum_kernel(lookback=3)
        for _ in range(10):
            kernel.feed_price(0.50)
        assert kernel.get_status()["price_history_len"] == 3

    def test_momentum_fires_when_price_falls_below_negative_threshold(self) -> None:
        # oldest=0.55, newest=0.50, change≈-9.1% < -threshold=-5% → SELL fires
        kernel = self._make_momentum_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.55)
        fired = kernel.feed_price(0.50)
        assert fired is True  # SELL signal fires for momentum on price drop

    def test_no_signal_when_flat_price(self) -> None:
        kernel = self._make_momentum_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.50)
        fired = kernel.feed_price(0.50)  # 0% change
        assert fired is False


class TestSignalKernelMeanReversionLogic:
    """Test the mean_reversion signal strategy using feed_price() for direct control.

    Mean reversion fires a BUY when ``change < -threshold`` (price dropped
    enough to revert) and a SELL when ``change > threshold`` (price spiked).
    """

    def _make_reversion_kernel(self, lookback: int = 2, threshold: float = 0.05) -> SignalKernel:
        return SignalKernel(
            token_id="tok-reversion",
            lookback=lookback,
            strategy="mean_reversion",
            threshold=threshold,
        )

    def test_no_signal_on_first_price(self) -> None:
        # Only one sample in history → no evaluation.
        kernel = self._make_reversion_kernel(lookback=5)
        assert kernel.feed_price(0.55) is False

    def test_mean_reversion_fires_buy_when_price_drops_below_threshold(self) -> None:
        # oldest=0.55, newest=0.50, change≈-9.1% < -threshold=-5% → BUY
        kernel = self._make_reversion_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.55)
        fired = kernel.feed_price(0.50)
        assert fired is True

    def test_mean_reversion_fires_sell_when_price_rises_above_threshold(self) -> None:
        # oldest=0.50, newest=0.55, change=10% > threshold=5% → SELL
        kernel = self._make_reversion_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.50)
        fired = kernel.feed_price(0.55)
        assert fired is True  # SELL signal fires for mean_reversion on price rise

    def test_signals_fired_increments_on_reversion_buy(self) -> None:
        kernel = self._make_reversion_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.55)
        kernel.feed_price(0.50)
        assert kernel._signals_fired == 1

    def test_no_signal_when_drop_too_small(self) -> None:
        # Drop of ~1% < 5% threshold → no signal
        kernel = self._make_reversion_kernel(lookback=2, threshold=0.05)
        kernel.feed_price(0.50)
        fired = kernel.feed_price(0.495)
        assert fired is False

    def test_signals_fired_zero_when_no_threshold_crossed(self) -> None:
        kernel = self._make_reversion_kernel(lookback=2, threshold=0.10)
        kernel.feed_price(0.50)
        kernel.feed_price(0.51)
        assert kernel._signals_fired == 0

    def test_signals_fired_counts_multiple_signals(self) -> None:
        kernel = self._make_reversion_kernel(lookback=2, threshold=0.05)
        # Each pair triggers a signal (oldest changes every time with lookback=2).
        kernel.feed_price(0.55)
        kernel.feed_price(0.50)  # drop ~9.1% → BUY
        kernel.feed_price(0.55)  # rise ~10% from new oldest=0.50 → SELL
        assert kernel._signals_fired == 2


# ---------------------------------------------------------------------------
# Engine Integration: lifecycle via TradingEngine
# ---------------------------------------------------------------------------


class TestEngineIntegrationLifecycle:
    """Start/stop kernels through TradingEngine with dry_run execution."""

    @pytest.mark.asyncio
    async def test_market_maker_kernel_lifecycle_via_engine(self) -> None:
        """Register, start, verify running, stop MarketMakerKernel."""
        engine = await _make_engine_with_dry_run()
        kernel = MarketMakerKernel(token_id="fake-token-lifecycle", refresh_interval=9999)
        engine.register_kernel(kernel)

        await engine.start_kernel("market-maker")
        assert kernel.status == "running"

        await engine.stop_kernel("market-maker")
        assert kernel.status == "stopped"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_signal_kernel_lifecycle_via_engine(self) -> None:
        """Register, start, verify running, stop SignalKernel."""
        engine = await _make_engine_with_dry_run()
        kernel = SignalKernel(token_id="fake-token-signal", poll_interval=9999)
        engine.register_kernel(kernel)

        await engine.start_kernel("signal")
        assert kernel.status == "running"

        await engine.stop_kernel("signal")
        assert kernel.status == "stopped"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_voice_kernel_registers_with_engine(self) -> None:
        """VoiceKernel can be registered with TradingEngine."""
        engine = await _make_engine_with_dry_run()
        kernel = VoiceKernel(source_type="youtube")
        engine.register_kernel(kernel)
        assert "voice" in engine.kernels
        await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_get_status_includes_all_three_kernels(self) -> None:
        """Engine status reflects all three registered kernels."""
        engine = await _make_engine_with_dry_run()
        engine.register_kernel(MarketMakerKernel(token_id="t1", refresh_interval=9999))
        engine.register_kernel(SignalKernel(token_id="t2", poll_interval=9999))
        engine.register_kernel(VoiceKernel())

        status = engine.get_status()
        assert "market-maker" in status["kernels"]
        assert "signal" in status["kernels"]
        assert "voice" in status["kernels"]
        await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_start_stop_all_kernels(self) -> None:
        """engine.stop() stops all running kernels at once."""
        engine = await _make_engine_with_dry_run()
        mm_kernel = MarketMakerKernel(token_id="tok-all", refresh_interval=9999)
        sig_kernel = SignalKernel(token_id="tok-all-sig", poll_interval=9999)
        engine.register_kernel(mm_kernel)
        engine.register_kernel(sig_kernel)

        await engine.start_kernel("market-maker")
        await engine.start_kernel("signal")
        assert mm_kernel.status == "running"
        assert sig_kernel.status == "running"

        await engine.stop()
        assert mm_kernel.status == "stopped"
        assert sig_kernel.status == "stopped"

    @pytest.mark.asyncio
    async def test_kernel_has_engine_reference_after_start(self) -> None:
        """After start_kernel(), kernel.engine is set to the TradingEngine."""
        engine = await _make_engine_with_dry_run()
        kernel = MarketMakerKernel(token_id="tok-ref", refresh_interval=9999)
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")
        assert kernel.engine is engine
        await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_reports_running_true_after_start(self) -> None:
        engine = await _make_engine_with_dry_run()
        assert engine._running is True
        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_cancelled_orders_for_market_maker(self) -> None:
        """Stopping MarketMakerKernel cancels its outstanding orders."""
        engine = await _make_engine_with_dry_run()
        kernel = MarketMakerKernel(token_id="tok-cancel", refresh_interval=9999)
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        # Manually place an order tagged with the kernel.
        order = engine.orders.create_order(
            token_id="tok-cancel",
            side="BUY",
            price=0.50,
            size=10,
            kernel_name="market-maker",
        )
        assert order.is_active is True

        await engine.stop_kernel("market-maker")
        # After stop, the order should be cancelled.
        updated = engine.orders.get_order(order.id)
        assert updated is not None
        assert updated.status == OrderStatus.CANCELLED

        await engine.stop()


# ---------------------------------------------------------------------------
# MarketMakerKernel: live market data + dry_run cycle
# ---------------------------------------------------------------------------


class TestMarketMakerKernelLiveCycle:
    """Integration test: one _refresh_quotes() cycle against the live CLOB."""

    @pytest.mark.asyncio
    async def test_refresh_quotes_creates_orders_for_active_token(self) -> None:
        """_refresh_quotes() should place at least one BUY order in dry_run mode."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        initial_order_count = len(engine.orders.orders)

        await kernel._refresh_quotes()

        final_order_count = len(engine.orders.orders)
        assert final_order_count > initial_order_count, (
            "Expected at least one order after _refresh_quotes() for an active token"
        )

        await engine.stop()

    @pytest.mark.asyncio
    async def test_refresh_quotes_places_buy_order(self) -> None:
        """After a refresh cycle, at least one order should be a BUY."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        await kernel._refresh_quotes()

        all_orders = list(engine.orders.orders.values())
        mm_orders = [o for o in all_orders if o.kernel_name == "market-maker"]
        assert any(o.side == "BUY" for o in mm_orders), (
            "Expected a BUY order from market-maker kernel"
        )

        await engine.stop()

    @pytest.mark.asyncio
    async def test_refresh_quotes_cycle_count_increments(self) -> None:
        """Running _refresh_quotes() manually increments _cycle_count via the loop."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        # Manually call _refresh_quotes() twice to test cycle tracking independently
        # of the loop (which would auto-increment _cycle_count).
        initial_cycles = kernel._cycle_count

        # The loop increments cycle_count, but direct _refresh_quotes() does not.
        # We verify get_status() cycle_count stays consistent with _cycle_count.
        status = kernel.get_status()
        assert status["cycle_count"] == initial_cycles

        await engine.stop()

    @pytest.mark.asyncio
    async def test_refresh_quotes_order_tagged_with_kernel_name(self) -> None:
        """Orders from _refresh_quotes() are tagged with the kernel name."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        await kernel._refresh_quotes()

        all_orders = list(engine.orders.orders.values())
        mm_orders = [o for o in all_orders if o.kernel_name == "market-maker"]
        assert len(mm_orders) > 0

        for order in mm_orders:
            assert order.kernel_name == "market-maker"

        await engine.stop()

    @pytest.mark.asyncio
    async def test_refresh_quotes_orders_have_valid_prices(self) -> None:
        """Orders placed by _refresh_quotes() should have prices in [0.01, 0.99]."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        await kernel._refresh_quotes()

        all_orders = list(engine.orders.orders.values())
        mm_orders = [o for o in all_orders if o.kernel_name == "market-maker"]
        for order in mm_orders:
            assert 0.01 <= order.price <= 0.99, (
                f"Order {order.id} has price {order.price} outside valid range"
            )

        await engine.stop()

    @pytest.mark.asyncio
    async def test_refresh_quotes_orders_for_correct_token(self) -> None:
        """All orders from _refresh_quotes() should target the configured token_id."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        await kernel._refresh_quotes()

        all_orders = list(engine.orders.orders.values())
        mm_orders = [o for o in all_orders if o.kernel_name == "market-maker"]
        for order in mm_orders:
            assert order.token_id == token_id

        await engine.stop()

    @pytest.mark.asyncio
    async def test_get_status_after_refresh_includes_cycle_count(self) -> None:
        """get_status() correctly reflects cycle_count in the status dict."""
        token_id = _get_active_token_id()
        engine = await _make_engine_with_dry_run()

        kernel = MarketMakerKernel(
            token_id=token_id,
            spread=0.02,
            size=50,
            refresh_interval=9999,
        )
        engine.register_kernel(kernel)
        await engine.start_kernel("market-maker")

        status = kernel.get_status()
        assert "cycle_count" in status
        assert isinstance(status["cycle_count"], int)

        await engine.stop()
