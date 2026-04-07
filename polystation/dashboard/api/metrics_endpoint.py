"""Prometheus /metrics endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from polystation.dashboard.app import get_engine

router = APIRouter()


@router.get("/metrics")
def prometheus_metrics() -> Response:
    """Expose Prometheus metrics in the standard text exposition format.

    Returns a 503 with a plain-text hint when prometheus_client is not
    installed so operators get a useful message instead of a silent 404.

    Returns:
        Response with content-type ``text/plain; version=0.0.4`` on success,
        or a 503 plain-text response when prometheus_client is unavailable.
    """
    eng = get_engine()
    if not hasattr(eng, "prom") or eng.prom is None:
        return Response(
            content="prometheus_client not installed. pip install prometheus_client",
            status_code=503,
            media_type="text/plain",
        )
    # Refresh metrics from current engine state before serialising
    eng.prom.update_from_engine(eng)
    return Response(
        content=eng.prom.generate(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
