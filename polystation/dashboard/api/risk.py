"""Risk monitoring API endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/summary")
def risk_summary() -> dict[str, Any]:
    """Return risk-related portfolio data.

    Returns:
        Dict with gross exposure, position count, P&L totals, and the largest
        open position.  Returns an error dict if MetricsCollector has not been
        initialized.
    """
    eng = get_engine()
    if eng.metrics is None:
        return {"error": "metrics not initialized"}
    return eng.metrics.get_risk_summary()


@router.get("/positions")
def risk_positions() -> list[dict[str, Any]]:
    """Return all open positions with risk metrics.

    Returns:
        List of position dicts including size, cost basis, unrealized P&L,
        and portfolio weight as a percentage.
    """
    eng = get_engine()
    positions = [p for p in eng.portfolio.positions.values() if p.size > 0]
    total_mv = eng.portfolio.total_market_value
    return [
        {
            "token_id": p.token_id[:20] + "...",
            "market_id": p.market_id,
            "side": p.side,
            "size": p.size,
            "avg_entry_price": round(p.avg_entry_price, 4),
            "current_price": p.current_price,
            "cost_basis": round(p.cost_basis, 4),
            "market_value": p.market_value,
            "unrealized_pnl": p.unrealized_pnl,
            "weight": round(p.cost_basis / total_mv * 100, 2) if total_mv > 0 else 0,
        }
        for p in positions
    ]
