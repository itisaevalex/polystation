"""Order management endpoints — query and inspect orders."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateOrderRequest(BaseModel):
    """Request body for manual order placement via the dashboard."""

    token_id: str
    side: str       # "BUY" or "SELL"
    price: float
    size: float
    order_type: str = "GTC"
    expiry: str = ""


@router.post("/create", summary="Place a manual order")
async def create_order(req: CreateOrderRequest) -> dict[str, Any]:
    """Create an order and immediately submit it through the execution engine.

    Args:
        req: Order parameters validated by :class:`CreateOrderRequest`.

    Returns:
        Dict with the serialised order and the execution result.

    Raises:
        HTTPException: 400 when order submission fails.
    """
    eng = get_engine()
    order = eng.orders.create_order(
        token_id=req.token_id,
        side=req.side,
        price=req.price,
        size=req.size,
        order_type=req.order_type,
        expiry=req.expiry,
        kernel_name="dashboard",
    )
    result = await eng.execution.submit_order(order)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail=order.error or "Order submission failed",
        )
    return {"order": order.to_dict(), "result": result}


@router.get("/", summary="Recent orders (most-recent first)")
def list_orders(limit: int = 50) -> list[dict[str, Any]]:
    """Return the *limit* most-recently created orders across all kernels."""
    eng = get_engine()
    orders = eng.orders.get_all_orders(limit)
    return [o.to_dict() for o in orders]


@router.get("/active", summary="Currently active orders")
def active_orders(kernel: str | None = None) -> list[dict[str, Any]]:
    """Return all orders in PENDING / SUBMITTED / PARTIALLY_FILLED state.

    Pass ``?kernel=<name>`` to filter to a single kernel's orders.
    """
    eng = get_engine()
    orders = eng.orders.get_active_orders(kernel)
    return [o.to_dict() for o in orders]


@router.get("/summary", summary="Order book statistics")
def order_summary() -> dict[str, Any]:
    """Return aggregate counts and the 20 most-recent orders."""
    eng = get_engine()
    return eng.orders.get_summary()


@router.get("/{order_id}", summary="Single order by ID")
def get_order(order_id: str) -> dict[str, Any]:
    """Return the full state of a single order, or 404 if not found."""
    eng = get_engine()
    order = eng.orders.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found")
    return order.to_dict()
