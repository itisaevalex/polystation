"""Backtesting API endpoints."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class BacktestRequest(BaseModel):
    """Request body for a single backtest run.

    Attributes:
        kernel_type: Which kernel family to use (``"signal"`` currently supported).
        strategy: Strategy variant — ``"momentum"`` or ``"mean_reversion"``.
        token_id: Polymarket token identifier being traded.
        prices: Ordered sequence of historical prices to replay.
        start_balance: Initial simulated USD balance.
        threshold: Signal threshold forwarded to :class:`~polystation.kernels.signal.kernel.SignalKernel`.
    """

    kernel_type: str = "signal"
    strategy: str = "momentum"
    token_id: str
    prices: list[float]
    start_balance: float = 10000.0
    threshold: float = 0.02


@router.post("/run")
async def run_backtest(req: BacktestRequest) -> dict[str, Any]:
    """Run a backtest by replaying a price sequence through the chosen kernel.

    Args:
        req: Validated :class:`BacktestRequest` body.

    Returns:
        Dict merging :meth:`~polystation.backtest.engine.BacktestResult.to_dict`
        with the full ``pnl_curve`` list and a human-readable ``summary`` string.

    Raises:
        HTTPException: 400 when fewer than 5 price points are supplied, or when
            ``kernel_type`` is not ``"signal"``.
    """
    from polystation.backtest.engine import BacktestEngine
    from polystation.kernels.signal.kernel import SignalKernel

    if len(req.prices) < 5:
        raise HTTPException(status_code=400, detail="Need at least 5 price points")

    if req.kernel_type != "signal":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported kernel_type '{req.kernel_type}' — only 'signal' is available",
        )

    kernel = SignalKernel(
        token_id=req.token_id,
        strategy=req.strategy,
        threshold=req.threshold,
        poll_interval=0,  # instant — backtest drives the loop
        lookback=5,
        size=50,
    )

    price_data = [
        {"timestamp": f"t{i}", "price": p}
        for i, p in enumerate(req.prices)
    ]
    engine = BacktestEngine(start_balance=req.start_balance)
    result = await engine.run(kernel, price_data, req.token_id)

    logger.info(
        "Backtest complete for %s: %s",
        req.token_id[:20],
        result.summary(),
    )

    return {
        **result.to_dict(),
        "pnl_curve": result.pnl_curve,
        "summary": result.summary(),
    }
