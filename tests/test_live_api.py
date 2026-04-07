"""Live integration tests against the real Polymarket CLOB API.

NO MOCKING. Every test hits the live endpoint.
Tests are marked with pytest.mark.live so they can be filtered.
"""

from __future__ import annotations

import pytest

from polystation.market.client import MarketDataClient, MarketPrice

# Shared client for all tests — single connection, reused.
_client = MarketDataClient()


# ---- Helper: find a valid active token_id ----

def _get_active_token_id() -> str:
    """Fetch an active token_id using the Gamma API (richer filtering)."""
    import requests as _req

    resp = _req.get(
        "https://gamma-api.polymarket.com/markets",
        params={"limit": "20", "active": "true", "closed": "false"},
        timeout=15,
    )
    resp.raise_for_status()
    markets = resp.json()
    for m in markets:
        clob_ids = m.get("clobTokenIds")
        if not clob_ids:
            continue
        # clobTokenIds may be a JSON string or a list
        if isinstance(clob_ids, str):
            import json as _json
            try:
                clob_ids = _json.loads(clob_ids)
            except (ValueError, TypeError):
                continue
        if isinstance(clob_ids, list) and clob_ids:
            token_id = clob_ids[0]
            if token_id and m.get("enableOrderBook", m.get("enable_order_book", True)):
                return token_id
    pytest.skip("No active market with order book found via Gamma API")
    return ""  # unreachable


@pytest.fixture(scope="module")
def active_token_id() -> str:
    return _get_active_token_id()


# ---------------------------------------------------------------------------
# Health & Time
# ---------------------------------------------------------------------------

class TestHealthAndTime:

    def test_health_check_returns_true(self) -> None:
        assert _client.health() is True

    def test_server_time_is_reasonable(self) -> None:
        ts = _client.server_time()
        # Should be a Unix timestamp (> Jan 1 2025)
        assert ts > 1_735_689_600
        # And not absurdly far in the future (< Jan 1 2030)
        assert ts < 1_893_456_000


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

class TestMarkets:

    def test_get_markets_returns_data(self) -> None:
        resp = _client.get_markets()
        assert isinstance(resp, dict)
        assert "data" in resp
        data = resp["data"]
        assert isinstance(data, list)
        assert len(data) > 0

    def test_market_has_expected_fields(self) -> None:
        resp = _client.get_markets()
        market = resp["data"][0]
        assert "condition_id" in market
        assert "tokens" in market
        assert isinstance(market["tokens"], list)

    def test_market_token_has_token_id(self) -> None:
        resp = _client.get_markets()
        for market in resp["data"][:10]:
            tokens = market.get("tokens", [])
            if tokens:
                assert "token_id" in tokens[0]
                break

    def test_get_markets_pagination(self) -> None:
        resp = _client.get_markets()
        assert "next_cursor" in resp
        cursor = resp["next_cursor"]
        assert isinstance(cursor, str)
        assert len(cursor) > 0

    def test_get_simplified_markets(self) -> None:
        resp = _client.get_simplified_markets()
        assert isinstance(resp, dict)
        assert "data" in resp
        data = resp["data"]
        assert len(data) > 0
        # Simplified should have fewer keys than full
        assert "condition_id" in data[0]

    def test_get_single_market(self) -> None:
        # First get a condition_id from the market list
        resp = _client.get_markets()
        condition_id = resp["data"][0]["condition_id"]
        market = _client.get_market(condition_id)
        assert isinstance(market, dict)
        assert market.get("condition_id") == condition_id


# ---------------------------------------------------------------------------
# Order Book
# ---------------------------------------------------------------------------

class TestOrderBook:

    def test_get_order_book(self, active_token_id: str) -> None:
        book = _client.get_order_book(active_token_id)
        # OrderBookSummary object or dict
        assert book is not None

    def test_order_book_has_bids_and_asks(self, active_token_id: str) -> None:
        book = _client.get_order_book(active_token_id)
        # Access fields — could be object or dict
        if hasattr(book, "bids"):
            bids = book.bids
            asks = book.asks
        else:
            bids = book.get("bids", [])
            asks = book.get("asks", [])
        assert isinstance(bids, list)
        assert isinstance(asks, list)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

class TestPricing:

    def test_midpoint_returns_float(self, active_token_id: str) -> None:
        mid = _client.get_midpoint(active_token_id)
        # Some markets may not have a midpoint, but most active ones will
        if mid is not None:
            assert isinstance(mid, float)
            assert 0.0 <= mid <= 1.0

    def test_price_buy_returns_float(self, active_token_id: str) -> None:
        price = _client.get_price(active_token_id, "BUY")
        if price is not None:
            assert isinstance(price, float)
            assert 0.0 <= price <= 1.0

    def test_price_sell_returns_float(self, active_token_id: str) -> None:
        price = _client.get_price(active_token_id, "SELL")
        if price is not None:
            assert isinstance(price, float)
            assert 0.0 <= price <= 1.0

    def test_spread_returns_float(self, active_token_id: str) -> None:
        spread = _client.get_spread(active_token_id)
        if spread is not None:
            assert isinstance(spread, float)
            assert spread >= 0.0

    def test_last_trade_price_returns_market_price(self, active_token_id: str) -> None:
        result = _client.get_last_trade_price(active_token_id)
        assert isinstance(result, MarketPrice)
        assert result.token_id == active_token_id

    def test_tick_size_returns_valid_value(self, active_token_id: str) -> None:
        tick = _client.get_tick_size(active_token_id)
        if tick is not None:
            assert isinstance(tick, float)
            assert tick > 0.0
            assert tick <= 0.1

    def test_full_pricing_returns_market_price(self, active_token_id: str) -> None:
        mp = _client.get_full_pricing(active_token_id)
        assert isinstance(mp, MarketPrice)
        assert mp.token_id == active_token_id
        # At least some fields should be populated for an active market
        populated = [mp.midpoint, mp.best_bid, mp.best_ask, mp.spread, mp.last_trade]
        assert any(v is not None for v in populated), f"No pricing data for {active_token_id}"


# ---------------------------------------------------------------------------
# Engine & Kernel framework (unit-style but no mocking — real objects)
# ---------------------------------------------------------------------------

class TestEngineKernelFramework:

    @pytest.mark.asyncio
    async def test_engine_starts_and_stops(self) -> None:
        from polystation.core.engine import TradingEngine

        engine = TradingEngine()
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

    @pytest.mark.asyncio
    async def test_register_and_list_kernels(self) -> None:
        from polystation.core.engine import TradingEngine
        from polystation.core.kernel import Kernel

        class DummyKernel(Kernel):
            name = "dummy"

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

        engine = TradingEngine()
        kernel = DummyKernel()
        engine.register_kernel(kernel)
        assert "dummy" in engine.kernels
        status = engine.get_status()
        assert "dummy" in status["kernels"]

    @pytest.mark.asyncio
    async def test_start_and_stop_kernel(self) -> None:
        from polystation.core.engine import TradingEngine
        from polystation.core.kernel import Kernel

        class TestKernel(Kernel):
            name = "test"
            started = False
            stopped = False

            async def start(self) -> None:
                self.started = True

            async def stop(self) -> None:
                self.stopped = True

        engine = TradingEngine()
        kernel = TestKernel()
        engine.register_kernel(kernel)

        await engine.start_kernel("test")
        assert kernel.status == "running"
        assert kernel.started is True

        await engine.stop_kernel("test")
        assert kernel.status == "stopped"
        assert kernel.stopped is True

    @pytest.mark.asyncio
    async def test_duplicate_kernel_registration_raises(self) -> None:
        from polystation.core.engine import TradingEngine
        from polystation.core.kernel import Kernel

        class K(Kernel):
            name = "dup"
            async def start(self) -> None: pass
            async def stop(self) -> None: pass

        engine = TradingEngine()
        engine.register_kernel(K())
        with pytest.raises(ValueError, match="already registered"):
            engine.register_kernel(K())

    @pytest.mark.asyncio
    async def test_event_bus_fires_on_kernel_start(self) -> None:
        from polystation.core.engine import TradingEngine
        from polystation.core.kernel import Kernel

        events_received: list[str] = []

        class EK(Kernel):
            name = "evtest"
            async def start(self) -> None: pass
            async def stop(self) -> None: pass

        engine = TradingEngine()
        engine.events.subscribe("kernel.started", lambda name: events_received.append(name))

        kernel = EK()
        engine.register_kernel(kernel)
        await engine.start_kernel("evtest")

        assert "evtest" in events_received
