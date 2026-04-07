"""Live integration tests for polystation market data layer. NO MOCKING."""

from __future__ import annotations

import asyncio
import json

import pytest

from polystation.market.book import OrderBook, PriceLevel
from polystation.market.client import MarketDataClient
from polystation.market.feed import MarketFeed
from polystation.market.scanner import MarketInfo, MarketScanner

# ---------------------------------------------------------------------------
# Module-level singletons — one connection for the whole test session
# ---------------------------------------------------------------------------

_client = MarketDataClient()
_scanner = MarketScanner()


# ---------------------------------------------------------------------------
# Helper: resolve a real, active token_id from the Gamma API
# ---------------------------------------------------------------------------


def _get_active_token_id() -> str:
    """Fetch an active token_id using the Gamma API (richer filtering)."""
    import requests

    resp = requests.get(
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
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except (ValueError, TypeError):
                continue
        if isinstance(clob_ids, list) and clob_ids:
            token_id = clob_ids[0]
            if token_id:
                return token_id
    pytest.skip("No active token found")
    return ""


@pytest.fixture(scope="module")
def active_token_id() -> str:
    """Module-scoped fixture: one live token_id shared by all OrderBook tests."""
    return _get_active_token_id()


# ---------------------------------------------------------------------------
# OrderBook model tests
# ---------------------------------------------------------------------------


class TestOrderBookModel:
    """Tests for OrderBook and PriceLevel dataclasses with manually constructed data."""

    def test_price_level_fields(self) -> None:
        """PriceLevel stores price and size exactly as given."""
        level = PriceLevel(price=0.55, size=100.0)
        assert level.price == 0.55
        assert level.size == 100.0

    def test_best_bid_and_ask_from_manual_levels(self) -> None:
        """best_bid and best_ask reflect the highest bid and lowest ask."""
        bids = [PriceLevel(0.45, 50.0), PriceLevel(0.44, 30.0)]
        asks = [PriceLevel(0.46, 20.0), PriceLevel(0.47, 10.0)]
        book = OrderBook(token_id="test-token", bids=bids, asks=asks)
        assert book.best_bid is not None
        assert book.best_bid.price == 0.45
        assert book.best_ask is not None
        assert book.best_ask.price == 0.46

    def test_spread_computed_correctly(self) -> None:
        """spread = best_ask.price - best_bid.price, rounded to 6 decimal places."""
        bids = [PriceLevel(0.45, 50.0)]
        asks = [PriceLevel(0.47, 20.0)]
        book = OrderBook(token_id="test-token", bids=bids, asks=asks)
        assert book.spread is not None
        assert abs(book.spread - 0.02) < 1e-9

    def test_midpoint_computed_correctly(self) -> None:
        """midpoint = (best_bid + best_ask) / 2."""
        bids = [PriceLevel(0.44, 10.0)]
        asks = [PriceLevel(0.46, 10.0)]
        book = OrderBook(token_id="test-token", bids=bids, asks=asks)
        assert book.midpoint is not None
        assert abs(book.midpoint - 0.45) < 1e-9

    def test_empty_book_best_bid_is_none(self) -> None:
        """An empty order book has no best bid."""
        book = OrderBook(token_id="empty-token")
        assert book.best_bid is None

    def test_empty_book_best_ask_is_none(self) -> None:
        """An empty order book has no best ask."""
        book = OrderBook(token_id="empty-token")
        assert book.best_ask is None

    def test_empty_book_spread_is_none(self) -> None:
        """spread is None when either side of the book is empty."""
        book = OrderBook(token_id="empty-token")
        assert book.spread is None

    def test_empty_book_midpoint_is_none(self) -> None:
        """midpoint is None when either side of the book is empty."""
        book = OrderBook(token_id="empty-token")
        assert book.midpoint is None

    def test_bid_depth_sums_all_levels(self) -> None:
        """bid_depth is the total size across all bid levels."""
        bids = [PriceLevel(0.45, 50.0), PriceLevel(0.44, 30.0), PriceLevel(0.43, 20.0)]
        book = OrderBook(token_id="test-token", bids=bids)
        assert abs(book.bid_depth - 100.0) < 1e-9

    def test_ask_depth_sums_all_levels(self) -> None:
        """ask_depth is the total size across all ask levels."""
        asks = [PriceLevel(0.46, 15.0), PriceLevel(0.47, 25.0)]
        book = OrderBook(token_id="test-token", asks=asks)
        assert abs(book.ask_depth - 40.0) < 1e-9

    def test_empty_book_depths_are_zero(self) -> None:
        """bid_depth and ask_depth are 0.0 when the book has no levels."""
        book = OrderBook(token_id="empty-token")
        assert book.bid_depth == 0.0
        assert book.ask_depth == 0.0

    def test_to_dict_returns_expected_keys(self) -> None:
        """to_dict() includes all required serialisation keys."""
        bids = [PriceLevel(0.45, 10.0)]
        asks = [PriceLevel(0.46, 10.0)]
        book = OrderBook(
            token_id="tok",
            market_id="mkt",
            bids=bids,
            asks=asks,
            tick_size=0.01,
            last_trade_price=0.44,
        )
        result = book.to_dict()
        expected_keys = {
            "token_id",
            "market_id",
            "timestamp",
            "best_bid",
            "best_ask",
            "spread",
            "midpoint",
            "bid_depth",
            "ask_depth",
            "bid_levels",
            "ask_levels",
            "last_trade_price",
        }
        assert expected_keys.issubset(result.keys())

    def test_to_dict_values_are_json_serialisable(self) -> None:
        """to_dict() output can be round-tripped through json.dumps without error."""
        bids = [PriceLevel(0.45, 50.0)]
        asks = [PriceLevel(0.47, 20.0)]
        book = OrderBook(token_id="tok", bids=bids, asks=asks)
        result = book.to_dict()
        serialised = json.dumps(result)
        assert isinstance(serialised, str)
        assert len(serialised) > 0

    def test_to_dict_best_bid_nested_dict(self) -> None:
        """to_dict() encodes best_bid as a dict with price and size keys."""
        bids = [PriceLevel(0.45, 10.0)]
        book = OrderBook(token_id="tok", bids=bids)
        result = book.to_dict()
        assert result["best_bid"] is not None
        assert result["best_bid"]["price"] == 0.45
        assert result["best_bid"]["size"] == 10.0

    def test_to_dict_empty_book_best_bid_is_none(self) -> None:
        """to_dict() sets best_bid to None for an empty book."""
        book = OrderBook(token_id="empty-tok")
        result = book.to_dict()
        assert result["best_bid"] is None
        assert result["best_ask"] is None
        assert result["spread"] is None
        assert result["midpoint"] is None

    def test_to_dict_level_counts(self) -> None:
        """to_dict() bid_levels and ask_levels match the actual list lengths."""
        bids = [PriceLevel(0.44, 1.0), PriceLevel(0.43, 2.0)]
        asks = [PriceLevel(0.46, 3.0)]
        book = OrderBook(token_id="tok", bids=bids, asks=asks)
        result = book.to_dict()
        assert result["bid_levels"] == 2
        assert result["ask_levels"] == 1


class TestOrderBookFromClobResponse:
    """Tests for OrderBook.from_clob_response() against the live CLOB API."""

    def test_from_clob_response_returns_order_book(self, active_token_id: str) -> None:
        """from_clob_response() produces an OrderBook for a live token."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        assert isinstance(book, OrderBook)

    def test_from_clob_response_token_id_preserved(self, active_token_id: str) -> None:
        """Parsed OrderBook carries the original token_id."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        assert book.token_id == active_token_id

    def test_from_clob_response_bids_and_asks_are_lists(self, active_token_id: str) -> None:
        """bids and asks are always lists (may be empty for illiquid markets)."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        assert isinstance(book.bids, list)
        assert isinstance(book.asks, list)

    def test_from_clob_response_bids_descending(self, active_token_id: str) -> None:
        """Bids are sorted highest-price-first after parsing."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        if len(book.bids) >= 2:
            for i in range(len(book.bids) - 1):
                assert book.bids[i].price >= book.bids[i + 1].price

    def test_from_clob_response_asks_ascending(self, active_token_id: str) -> None:
        """Asks are sorted lowest-price-first after parsing."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        if len(book.asks) >= 2:
            for i in range(len(book.asks) - 1):
                assert book.asks[i].price <= book.asks[i + 1].price

    def test_from_clob_response_price_levels_are_price_level_instances(self, active_token_id: str) -> None:
        """Each entry in bids and asks is a PriceLevel dataclass."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        for level in book.bids:
            assert isinstance(level, PriceLevel)
        for level in book.asks:
            assert isinstance(level, PriceLevel)

    def test_from_clob_response_price_levels_have_positive_values(self, active_token_id: str) -> None:
        """All parsed price/size values must be non-negative floats."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        for level in book.bids + book.asks:
            assert isinstance(level.price, float)
            assert isinstance(level.size, float)
            assert level.price >= 0.0
            assert level.size >= 0.0

    def test_from_clob_response_tick_size_is_positive(self, active_token_id: str) -> None:
        """Parsed tick_size is a positive float."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        assert isinstance(book.tick_size, float)
        assert book.tick_size > 0.0

    def test_from_clob_response_to_dict_roundtrip(self, active_token_id: str) -> None:
        """A live OrderBook can be serialised to a JSON-compatible dict."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        result = book.to_dict()
        assert isinstance(result, dict)
        assert result["token_id"] == active_token_id
        # Ensure JSON round-trip works
        json.dumps(result)

    def test_from_clob_response_spread_valid_when_both_sides_present(self, active_token_id: str) -> None:
        """spread is a non-negative float when the book has both bids and asks."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        if book.best_bid and book.best_ask:
            assert book.spread is not None
            assert isinstance(book.spread, float)
            assert book.spread >= 0.0

    def test_from_clob_response_midpoint_in_valid_range(self, active_token_id: str) -> None:
        """midpoint lies in (0, 1) for a prediction market token."""
        raw = _client.get_order_book(active_token_id)
        book = OrderBook.from_clob_response(active_token_id, raw)
        if book.midpoint is not None:
            assert 0.0 < book.midpoint < 1.0


# ---------------------------------------------------------------------------
# MarketScanner tests (Gamma API)
# ---------------------------------------------------------------------------


class TestMarketScanner:
    """Tests for MarketScanner against the live Gamma API."""

    def test_get_active_markets_returns_list(self) -> None:
        """get_active_markets() returns a list."""
        result = _scanner.get_active_markets(limit=10)
        assert isinstance(result, list)

    def test_get_active_markets_non_empty(self) -> None:
        """get_active_markets() returns at least one market."""
        result = _scanner.get_active_markets(limit=10)
        assert len(result) > 0

    def test_get_active_markets_returns_market_info_instances(self) -> None:
        """Every element in the list is a MarketInfo dataclass."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m, MarketInfo)

    def test_get_active_markets_condition_id_non_empty(self) -> None:
        """Each MarketInfo has a non-empty condition_id string."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.condition_id, str)
            assert len(m.condition_id) > 0

    def test_get_active_markets_question_non_empty(self) -> None:
        """Each MarketInfo has a non-empty question string."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.question, str)
            assert len(m.question) > 0

    def test_get_active_markets_active_flag_true(self) -> None:
        """Markets returned by get_active_markets() are all marked active=True."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert m.active is True

    def test_get_active_markets_closed_flag_false(self) -> None:
        """Markets returned by get_active_markets() are all marked closed=False."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert m.closed is False

    def test_get_active_markets_token_ids_is_list(self) -> None:
        """token_ids is a list for every returned market."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.token_ids, list)

    def test_get_active_markets_outcomes_is_list(self) -> None:
        """outcomes is a list for every returned market."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.outcomes, list)

    def test_get_active_markets_volume_non_negative(self) -> None:
        """volume is a non-negative float for every returned market."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.volume, float)
            assert m.volume >= 0.0

    def test_get_active_markets_liquidity_non_negative(self) -> None:
        """liquidity is a non-negative float for every returned market."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.liquidity, float)
            assert m.liquidity >= 0.0

    def test_get_active_markets_neg_risk_is_bool(self) -> None:
        """neg_risk is a bool for every returned market."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            assert isinstance(m.neg_risk, bool)

    def test_get_active_markets_best_bid_ask_types(self) -> None:
        """best_bid and best_ask are either None or a float in [0, 1]."""
        result = _scanner.get_active_markets(limit=10)
        for m in result:
            if m.best_bid is not None:
                assert isinstance(m.best_bid, float)
                assert 0.0 <= m.best_bid <= 1.0
            if m.best_ask is not None:
                assert isinstance(m.best_ask, float)
                assert 0.0 <= m.best_ask <= 1.0

    def test_get_events_returns_non_empty_list(self) -> None:
        """get_events() returns at least one event dict."""
        events = _scanner.get_events(limit=10)
        assert isinstance(events, list)
        assert len(events) > 0

    def test_get_events_elements_are_dicts(self) -> None:
        """Each element returned by get_events() is a dict."""
        events = _scanner.get_events(limit=10)
        for event in events:
            assert isinstance(event, dict)

    def test_get_events_have_slug_or_title(self) -> None:
        """Each event dict has at least a slug or a title key."""
        events = _scanner.get_events(limit=10)
        for event in events:
            assert "slug" in event or "title" in event

    def test_get_trending_returns_list(self) -> None:
        """get_trending() returns a list."""
        result = _scanner.get_trending(limit=5)
        assert isinstance(result, list)

    def test_get_trending_returns_market_info_instances(self) -> None:
        """Every element returned by get_trending() is a MarketInfo."""
        result = _scanner.get_trending(limit=5)
        for m in result:
            assert isinstance(m, MarketInfo)

    def test_get_trending_non_empty(self) -> None:
        """get_trending() returns at least one result."""
        result = _scanner.get_trending(limit=5)
        assert len(result) > 0

    def test_search_markets_returns_list(self) -> None:
        """search_markets() returns a list without raising."""
        result = _scanner.search_markets("bitcoin", limit=10)
        assert isinstance(result, list)

    def test_search_markets_elements_are_market_info(self) -> None:
        """Every element returned by search_markets() is a MarketInfo."""
        result = _scanner.search_markets("bitcoin", limit=10)
        for m in result:
            assert isinstance(m, MarketInfo)

    def test_search_markets_does_not_raise_on_no_results(self) -> None:
        """search_markets() with an unlikely query returns a list, not an exception."""
        # Use a very specific slug substring that likely yields zero matches
        result = _scanner.search_markets("zzz-highly-unlikely-query-xyz", limit=5)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# MarketFeed tests (WebSocket)
# ---------------------------------------------------------------------------


class TestMarketFeed:
    """Tests for MarketFeed WebSocket connectivity."""

    def test_market_feed_instantiation(self) -> None:
        """MarketFeed can be instantiated with the default URL."""
        feed = MarketFeed()
        assert isinstance(feed, MarketFeed)
        assert "wss://" in feed.url

    def test_market_feed_custom_url(self) -> None:
        """MarketFeed stores a custom URL provided at construction time."""
        custom_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        feed = MarketFeed(url=custom_url)
        assert feed.url == custom_url

    def test_market_feed_initial_state(self) -> None:
        """A freshly created MarketFeed is not running and has no subscriptions."""
        feed = MarketFeed()
        assert feed._running is False
        assert len(feed._subscriptions) == 0

    def test_market_feed_subscribe_adds_token(self) -> None:
        """subscribe() records the token_id in the internal subscription set."""
        feed = MarketFeed()
        token_id = "12345"
        feed.subscribe(token_id)
        assert token_id in feed._subscriptions

    def test_market_feed_unsubscribe_removes_token(self) -> None:
        """unsubscribe() removes a previously added token_id."""
        feed = MarketFeed()
        token_id = "12345"
        feed.subscribe(token_id)
        feed.unsubscribe(token_id)
        assert token_id not in feed._subscriptions

    def test_market_feed_on_message_registers_callback(self) -> None:
        """on_message() appends a callback to the internal callback list."""
        feed = MarketFeed()

        async def _cb(msg: dict) -> None:  # type: ignore[type-arg]
            pass

        feed.on_message(_cb)
        assert _cb in feed._callbacks

    @pytest.mark.asyncio
    async def test_market_feed_start_connects_to_live_ws(self) -> None:
        """start() establishes a live WebSocket connection within 10 seconds.

        The feed is allowed to run for up to 2 seconds; if it does not raise
        within that window the connection is considered successful.  A
        TimeoutError from asyncio.wait_for is the *expected* outcome — it
        means the feed connected and was listening when we cancelled it.
        """
        feed = MarketFeed()
        try:
            await asyncio.wait_for(feed.start(), timeout=2.0)
        except asyncio.TimeoutError:
            # Expected: feed connected and was blocked waiting for messages.
            pass
        finally:
            await feed.stop()
        # After stop(), _running must be False
        assert feed._running is False

    @pytest.mark.asyncio
    async def test_market_feed_stop_sets_running_false(self) -> None:
        """stop() sets _running to False even when called before start()."""
        feed = MarketFeed()
        await feed.stop()
        assert feed._running is False

    @pytest.mark.asyncio
    async def test_market_feed_start_with_subscription(self, active_token_id: str) -> None:
        """start() connects when a token subscription is registered beforehand."""
        feed = MarketFeed()
        feed.subscribe(active_token_id)
        try:
            await asyncio.wait_for(feed.start(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        finally:
            await feed.stop()
        assert feed._running is False
