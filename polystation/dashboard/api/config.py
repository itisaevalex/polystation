"""Configuration endpoints — dry-run toggle and runtime settings."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from polystation.dashboard.app import get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/dry-run", summary="Set dry-run mode")
async def set_dry_run(enabled: bool = True) -> dict[str, Any]:
    """Enable or disable dry-run mode on the execution engine.

    When dry-run is active no real orders are submitted to the CLOB.
    Pass ``?enabled=false`` to switch to live trading.
    """
    eng = get_engine()
    eng.execution.set_dry_run(enabled)
    logger.info("Dry-run mode set to %s", enabled)
    return {"dry_run": enabled}


@router.get("/dry-run", summary="Get current dry-run state")
def get_dry_run() -> dict[str, Any]:
    """Return the current dry-run flag from the execution engine."""
    eng = get_engine()
    return {"dry_run": eng.execution._dry_run}
