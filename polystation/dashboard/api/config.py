"""Configuration endpoints — dry-run toggle and runtime settings."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

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


class CredentialsRequest(BaseModel):
    host: str = "https://clob.polymarket.com"
    pk: str = ""
    pbk: str = ""
    clob_api_key: str = ""
    clob_secret: str = ""
    clob_pass_phrase: str = ""


@router.post("/credentials", summary="Set API credentials and initialize trading client")
async def set_credentials(req: CredentialsRequest) -> dict[str, Any]:
    """Set CLOB credentials in the running process and reinitialize the execution engine.

    This sets os.environ vars so that create_clob_client() picks them up,
    then rebuilds the execution engine's CLOB client.
    """
    import os
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    from py_clob_client.constants import POLYGON
    from polystation.core.orders import OrderManager
    from polystation.trading.execution import ExecutionEngine

    # Set env vars for this process
    os.environ["HOST"] = req.host
    if req.pk:
        os.environ["PK"] = req.pk
    if req.pbk:
        os.environ["PBK"] = req.pbk
    if req.clob_api_key:
        os.environ["CLOB_API_KEY"] = req.clob_api_key
    if req.clob_secret:
        os.environ["CLOB_SECRET"] = req.clob_secret
    if req.clob_pass_phrase:
        os.environ["CLOB_PASS_PHRASE"] = req.clob_pass_phrase

    # Build CLOB client
    try:
        creds = None
        if req.clob_api_key:
            creds = ApiCreds(
                api_key=req.clob_api_key,
                api_secret=req.clob_secret,
                api_passphrase=req.clob_pass_phrase,
            )
        client = ClobClient(host=req.host, key=req.pk or None, chain_id=POLYGON, creds=creds)

        eng = get_engine()
        # Rewire execution engine with the real client
        eng.execution = ExecutionEngine(client, eng.orders, eng.portfolio)
        eng.execution.set_dry_run(False)

        logger.info("Credentials set — live trading client initialized")
        return {"status": "ok", "dry_run": False, "host": req.host}
    except Exception as exc:
        logger.error("Failed to initialize trading client: %s", exc)
        return {"status": "error", "error": str(exc)}
