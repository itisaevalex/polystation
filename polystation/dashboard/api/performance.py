"""Performance tracking API endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/summary")
def performance_summary() -> dict[str, Any]:
    """Return aggregate performance statistics across all kernels.

    Returns:
        Dict with total trade count, P&L, volume, win rate, and per-kernel counts.
        Returns an error dict if MetricsCollector has not been initialized.
    """
    eng = get_engine()
    if eng.metrics is None:
        return {"error": "metrics not initialized"}
    return eng.metrics.get_performance_summary()


@router.get("/pnl-history")
def pnl_history(limit: int = 500) -> list[dict[str, Any]]:
    """Return P&L time-series snapshots.

    Args:
        limit: Maximum number of data points to return (downsampled if needed).

    Returns:
        List of snapshot dicts ordered oldest-first, or empty list if not ready.
    """
    eng = get_engine()
    if eng.metrics is None:
        return []
    return eng.metrics.get_pnl_history(limit)


@router.get("/trades")
def trade_history(
    limit: int = 100, kernel: str | None = None
) -> list[dict[str, Any]]:
    """Return recent trade records.

    Args:
        limit: Maximum number of records to return.
        kernel: Optional kernel name to filter results.

    Returns:
        List of trade record dicts, most-recent first.
    """
    eng = get_engine()
    if eng.metrics is None:
        return []
    return eng.metrics.get_trade_history(limit, kernel)


@router.get("/kernels")
def kernel_performance() -> list[dict[str, Any]]:
    """Return per-kernel performance breakdown.

    Returns:
        List of KernelStats dicts, one per kernel seen.
    """
    eng = get_engine()
    if eng.metrics is None:
        return []
    return eng.metrics.get_kernel_stats()
