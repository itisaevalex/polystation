"""Portfolio and P&L endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/", summary="Full portfolio snapshot")
def portfolio_summary() -> dict[str, Any]:
    """Return all positions, P&L figures, market value, and trade count."""
    eng = get_engine()
    return eng.portfolio.get_summary()


@router.get("/positions", summary="Open positions only")
def list_positions() -> dict[str, Any]:
    """Return positions with non-zero size, keyed by token_id."""
    eng = get_engine()
    return {
        tid: p.to_dict()
        for tid, p in eng.portfolio.positions.items()
        if p.size > 0
    }


@router.get("/pnl", summary="Realized and unrealized P&L")
def pnl() -> dict[str, Any]:
    """Return realized, unrealized, and combined total P&L."""
    eng = get_engine()
    return {
        "realized": round(eng.portfolio.realized_pnl, 4),
        "unrealized": round(eng.portfolio.total_unrealized_pnl, 4),
        "total": round(eng.portfolio.total_pnl, 4),
        "total_market_value": round(eng.portfolio.total_market_value, 4),
        "trade_count": eng.portfolio.trade_count,
    }
