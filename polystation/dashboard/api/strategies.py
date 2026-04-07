"""Kernel (strategy) management endpoints — list, start, stop."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


class StartKernelRequest(BaseModel):
    """Request body for POST /api/strategies/start."""

    name: str
    params: dict[str, Any] = {}


@router.get("/", summary="Engine and kernel status")
def list_strategies() -> dict[str, Any]:
    """Return engine running state and per-kernel status dicts."""
    eng = get_engine()
    return eng.get_status()


@router.get("/available", summary="Registered kernel names")
def available_kernels() -> dict[str, Any]:
    """Import all kernel modules to populate the registry, then list names."""
    # Side-effect imports register kernels via the @register decorator
    import polystation.kernels.voice  # noqa: F401
    import polystation.kernels.market_maker  # noqa: F401
    import polystation.kernels.signal  # noqa: F401

    from polystation.kernels import list_kernels

    return {"kernels": list_kernels()}


@router.post("/start", summary="Instantiate and start a kernel")
async def start_kernel(req: StartKernelRequest) -> dict[str, Any]:
    """Create a kernel from the registry and start it under the engine.

    ``params`` are forwarded as keyword arguments to the kernel's ``__init__``.
    Returns ``{"status": "started", "name": <name>}`` on success.
    """
    # Ensure all kernels are registered before attempting creation
    import polystation.kernels.voice  # noqa: F401
    import polystation.kernels.market_maker  # noqa: F401
    import polystation.kernels.signal  # noqa: F401

    from polystation.kernels import create_kernel

    eng = get_engine()

    # If a kernel with this name is already registered, reject to avoid duplicate
    if req.name in eng.kernels:
        raise HTTPException(
            status_code=409,
            detail=f"Kernel '{req.name}' is already registered. Stop it first.",
        )

    try:
        kernel = create_kernel(req.name, **req.params)
        eng.register_kernel(kernel)
        await eng.start_kernel(req.name)
        return {"status": "started", "name": req.name}
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to start kernel '%s'", req.name)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/stop/{name}", summary="Stop a running kernel")
async def stop_kernel(name: str) -> dict[str, Any]:
    """Stop the named kernel and transition it to ``stopped`` status."""
    eng = get_engine()
    if name not in eng.kernels:
        raise HTTPException(status_code=404, detail=f"Kernel '{name}' not found")
    try:
        await eng.stop_kernel(name)
        return {"status": "stopped", "name": name}
    except Exception as exc:
        logger.exception("Failed to stop kernel '%s'", name)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{name}", summary="Single kernel status")
def kernel_status(name: str) -> dict[str, Any]:
    """Return the status dict for a single kernel."""
    eng = get_engine()
    kernel = eng.kernels.get(name)
    if kernel is None:
        raise HTTPException(status_code=404, detail=f"Kernel '{name}' not found")
    return kernel.get_status()
