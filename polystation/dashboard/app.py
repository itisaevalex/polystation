"""FastAPI application for the Polystation dashboard."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from polystation.core.engine import TradingEngine
from polystation.core.metrics import MetricsCollector
from polystation.core.orders import OrderManager
from polystation.core.portfolio import Portfolio
from polystation.market.client import MarketDataClient
from polystation.trading.execution import ExecutionEngine

logger = logging.getLogger(__name__)

# Global engine instance — attached during lifespan startup
engine: TradingEngine | None = None


def get_engine() -> TradingEngine:
    """Return the global TradingEngine, raising AssertionError if not yet initialised."""
    assert engine is not None, "Engine not initialized"
    return engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of the TradingEngine."""
    global engine
    engine = TradingEngine()
    engine.market_data = MarketDataClient()
    engine.portfolio = Portfolio()
    engine.orders = OrderManager()
    engine.metrics = MetricsCollector()
    engine.metrics.set_references(engine.portfolio, engine.orders)
    # ExecutionEngine requires a ClobClient for live trading; pass None for
    # dashboard-only / dry-run mode where no signed orders are submitted.
    engine.execution = ExecutionEngine(  # type: ignore[arg-type]
        None, engine.orders, engine.portfolio, metrics=engine.metrics
    )
    engine.execution.set_dry_run(True)  # Safe default — no live CLOB calls
    await engine.start()
    snapshot_task = asyncio.create_task(engine.metrics.run_snapshots())
    logger.info("Polystation dashboard started")
    yield
    engine.metrics.stop()
    snapshot_task.cancel()
    await engine.stop()
    logger.info("Polystation dashboard stopped")


def create_app() -> FastAPI:
    """Application factory consumed by uvicorn --factory."""
    app = FastAPI(
        title="Polystation",
        description="Polymarket Trading Station",
        version="3.0.0",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ #
    # API routers                                                          #
    # ------------------------------------------------------------------ #
    from polystation.dashboard.api.markets import router as markets_router
    from polystation.dashboard.api.orders import router as orders_router
    from polystation.dashboard.api.strategies import router as strategies_router
    from polystation.dashboard.api.portfolio import router as portfolio_router
    from polystation.dashboard.api.config import router as config_router
    from polystation.dashboard.api.performance import router as performance_router
    from polystation.dashboard.api.risk import router as risk_router
    from polystation.dashboard.ws import router as ws_router

    app.include_router(markets_router, prefix="/api/markets", tags=["markets"])
    app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
    app.include_router(strategies_router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(config_router, prefix="/api/config", tags=["config"])
    app.include_router(performance_router, prefix="/api/performance", tags=["performance"])
    app.include_router(risk_router, prefix="/api/risk", tags=["risk"])
    app.include_router(ws_router, tags=["websocket"])

    # ------------------------------------------------------------------ #
    # Static files (SPA)                                                   #
    # Mount last so API routes take precedence.                            #
    # ------------------------------------------------------------------ #
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
