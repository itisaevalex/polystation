"""Order management endpoints — query and inspect orders."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


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
