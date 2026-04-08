"""Risk monitoring API endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/guard")
def risk_guard_status() -> dict[str, Any]:
    """Return the current RiskGuard configuration and daily counters.

    Returns:
        Dict with enabled flag, config thresholds, daily counters, and
        the ten most-recent vetoes.  Returns a minimal disabled dict when
        the RiskGuard is not wired into the execution engine.
    """
    eng = get_engine()
    if eng.execution and eng.execution.risk_guard:
        return eng.execution.risk_guard.get_status()
    return {"enabled": False, "config": {}, "recent_vetoes": []}


@router.post("/guard")
def update_risk_guard(config: dict[str, Any]) -> dict[str, Any]:
    """Update RiskGuard configuration fields at runtime.

    Only fields present in RiskConfig are applied; unknown keys are silently
    ignored.  Returns the updated status dict after applying the changes.

    Args:
        config: Partial or full dict of RiskConfig field names to new values.

    Returns:
        Updated RiskGuard status dict, or an error dict when the guard is
        not initialized.
    """
    eng = get_engine()
    if eng.execution and eng.execution.risk_guard:
        eng.execution.risk_guard.update_config(**config)
        return eng.execution.risk_guard.get_status()
    return {"error": "RiskGuard not initialized"}


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


@router.get("/exits")
def exit_config_status() -> dict[str, Any]:
    """Return the current PositionManager exit configuration and status.

    Returns:
        Dict from :meth:`~polystation.automation.position_manager.PositionManager.get_status`,
        or an error dict when the PositionManager has not been initialized.
    """
    eng = get_engine()
    if eng.position_manager:
        return eng.position_manager.get_status()
    return {"error": "PositionManager not initialized"}


@router.post("/exits")
async def update_exit_config(config: dict[str, Any]) -> dict[str, Any]:
    """Update the global PositionManager exit configuration at runtime.

    Args:
        config: Dict with any subset of :class:`~polystation.automation.position_manager.ExitConfig`
            fields.  Unknown keys are silently ignored.

    Returns:
        Updated status dict after applying the new config, or an error dict
        when the PositionManager has not been initialized.
    """
    eng = get_engine()
    if not eng.position_manager:
        return {"error": "PositionManager not initialized"}
    from polystation.automation.position_manager import ExitConfig
    new_config = ExitConfig(
        trailing_stop_pct=config.get("trailing_stop_pct"),
        profit_target_pct=config.get("profit_target_pct"),
        stop_loss_pct=config.get("stop_loss_pct"),
        max_hold_hours=config.get("max_hold_hours"),
        expiry_exit_hours=config.get("expiry_exit_hours", 2.0),
        enabled=config.get("enabled", False),
    )
    eng.position_manager.set_config(None, new_config)
    return eng.position_manager.get_status()


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
