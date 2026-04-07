"""Market data endpoints — CLOB pricing and Gamma market discovery."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


def _market_to_dict(m: Any) -> dict[str, Any]:
    return {
        "condition_id": m.condition_id,
        "question": m.question,
        "slug": m.slug,
        "volume": m.volume,
        "liquidity": m.liquidity,
        "best_bid": m.best_bid,
        "best_ask": m.best_ask,
        "last_trade_price": m.last_trade_price,
        "token_ids": m.token_ids,
        "outcomes": m.outcomes,
        "neg_risk": m.neg_risk,
        "image": m.image,
    }


@router.get("/", summary="List active open markets (paginated)")
def list_markets(offset: int = 0, limit: int = 100, order: str = "volumeNum") -> dict[str, Any]:
    """Return a page of active open markets sorted by the given field.

    Polymarket has ~50,000+ active markets. Use offset/limit for pagination.
    """
    from polystation.market.scanner import MarketScanner

    scanner = MarketScanner()
    try:
        markets = scanner.get_markets_page(offset=offset, limit=limit, order=order)
    except Exception as exc:
        logger.error("Failed to fetch markets page: %s", exc)
        raise HTTPException(502, f"Gamma API error: {exc}") from exc

    return {
        "data": [_market_to_dict(m) for m in markets],
        "offset": offset,
        "limit": limit,
        "count": len(markets),
        "has_more": len(markets) == limit,
    }


@router.get("/trending", summary="Trending markets by 24-hour volume")
def trending_markets(limit: int = 20) -> list[dict[str, Any]]:
    """Return markets with highest 24-hour volume."""
    from polystation.market.scanner import MarketScanner

    scanner = MarketScanner()
    try:
        markets = scanner.get_trending(limit=limit)
    except Exception as exc:
        logger.error("Failed to fetch trending markets: %s", exc)
        raise HTTPException(502, f"Gamma API error: {exc}") from exc

    return [_market_to_dict(m) for m in markets]


@router.get("/search", summary="Search markets by keyword")
def search_markets(q: str, limit: int = 100) -> dict[str, Any]:
    """Search active open markets by keyword. Returns up to *limit* results."""
    from polystation.market.scanner import MarketScanner

    scanner = MarketScanner()
    try:
        markets = scanner.search_markets(q, limit=limit)
    except Exception as exc:
        logger.error("Market search failed for query '%s': %s", q, exc)
        raise HTTPException(502, f"Gamma API error: {exc}") from exc

    return {
        "query": q,
        "data": [_market_to_dict(m) for m in markets],
        "count": len(markets),
    }


@router.get("/book/{token_id}", summary="Order book snapshot for a token")
def get_order_book(token_id: str) -> dict[str, Any]:
    """Return the live order book for *token_id* from the CLOB API."""
    eng = get_engine()
    try:
        raw = eng.market_data.get_order_book(token_id)
    except Exception as exc:
        logger.error("Order book fetch failed for %s: %s", token_id, exc)
        raise HTTPException(502, f"CLOB API error: {exc}") from exc

    from polystation.market.book import OrderBook

    book = OrderBook.from_clob_response(token_id, raw)

    # Extend the default to_dict() with full level arrays for chart rendering
    result = book.to_dict()
    result["bids"] = [{"price": lv.price, "size": lv.size} for lv in book.bids[:20]]
    result["asks"] = [{"price": lv.price, "size": lv.size} for lv in book.asks[:20]]
    return result


@router.get("/price/{token_id}", summary="Best bid/ask/midpoint for a token")
def get_pricing(token_id: str) -> dict[str, Any]:
    """Return current mid-market price, best bid/ask and spread."""
    eng = get_engine()
    try:
        return {
            "token_id": token_id,
            "midpoint": eng.market_data.get_midpoint(token_id),
            "best_bid": eng.market_data.get_price(token_id, "BUY"),
            "best_ask": eng.market_data.get_price(token_id, "SELL"),
            "spread": eng.market_data.get_spread(token_id),
        }
    except Exception as exc:
        logger.error("Pricing fetch failed for %s: %s", token_id, exc)
        raise HTTPException(502, f"CLOB API error: {exc}") from exc


@router.get("/health", summary="CLOB API health check")
def api_health() -> dict[str, Any]:
    """Check CLOB connectivity and return server timestamp."""
    eng = get_engine()
    try:
        healthy = eng.market_data.health()
        server_time = eng.market_data.server_time() if healthy else None
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return {"clob": False, "server_time": None, "error": str(exc)}

    return {"clob": healthy, "server_time": server_time}
