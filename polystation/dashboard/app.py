"""FastAPI application for the Polystation dashboard."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from polystation.core.engine import TradingEngine
from polystation.core.metrics import MetricsCollector
from polystation.core.orders import OrderManager
from polystation.core.portfolio import Portfolio
from polystation.core.prometheus import PolystationMetrics
from polystation.core.risk import RiskGuard
from polystation.exchanges.polymarket import PolymarketExchange
from polystation.infra.redis_client import RedisManager
from polystation.market.client import MarketDataClient
from polystation.trading.execution import ExecutionEngine

logger = logging.getLogger(__name__)

# Global engine instance — attached during lifespan startup
engine: TradingEngine | None = None


def get_engine() -> TradingEngine:
    """Return the global TradingEngine, raising AssertionError if not yet initialised."""
    assert engine is not None, "Engine not initialized"
    return engine


async def _prometheus_scrape_loop(prom: PolystationMetrics, eng: TradingEngine) -> None:
    while True:
        prom.update_from_engine(eng)
        await asyncio.sleep(5)


async def _redis_heartbeat_loop(rm: RedisManager) -> None:
    while True:
        rm.heartbeat()
        await asyncio.sleep(10)


async def _redis_snapshot_loop(eng: TradingEngine) -> None:
    while True:
        if eng.redis and eng.redis.connected and eng.portfolio:
            eng.redis.snapshot_portfolio(eng.portfolio.get_summary())
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of the TradingEngine."""
    global engine
    engine = TradingEngine()
    engine.market_data = MarketDataClient()
    engine.portfolio = Portfolio()
    engine.orders = OrderManager()

    # MetricsCollector — in-memory performance tracking
    engine.metrics = MetricsCollector()
    engine.metrics.set_references(engine.portfolio, engine.orders)

    # Prometheus metrics (optional — no-op if prometheus_client not installed)
    engine.prom = PolystationMetrics()

    # RiskGuard — pre-trade risk checks
    risk_guard = RiskGuard()

    # Redis (optional — graceful degradation if unavailable)
    redis_url = os.getenv("REDIS_URL", "")
    engine.redis = RedisManager(redis_url) if redis_url else RedisManager()

    # Connect Polymarket exchange adapter
    poly_exchange = PolymarketExchange()
    await poly_exchange.connect()
    engine.register_exchange(poly_exchange)

    # ExecutionEngine with all integrations
    engine.execution = ExecutionEngine(
        poly_exchange, engine.orders, engine.portfolio,
        metrics=engine.metrics, risk_guard=risk_guard,
        redis_client=engine.redis if engine.redis and engine.redis.connected else None,
    )
    engine.execution.set_dry_run(True)  # Safe default

    # Persistence — SQLite state database
    from polystation.persistence.database import StateDatabase
    engine.db = StateDatabase()
    engine.db.connect()
    engine.metrics.set_database(engine.db)
    engine.execution.db = engine.db

    # Restore state from previous session
    if engine.db:
        try:
            state = engine.db.restore_portfolio_state()
            if state.get("positions"):
                for pos_dict in state["positions"]:
                    # Hydrate portfolio with saved positions
                    engine.portfolio.record_fill(
                        token_id=pos_dict["token_id"],
                        side=pos_dict.get("side", "BUY"),
                        price=pos_dict.get("avg_entry_price", 0),
                        size=pos_dict.get("size", 0),
                        market_id=pos_dict.get("market_id", ""),
                        outcome=pos_dict.get("outcome", ""),
                    )
                engine.portfolio.realized_pnl = state.get("realized_pnl", 0.0)
                engine.portfolio.trade_count = state.get("trade_count", 0)
                logger.info(
                    "Restored %d positions, P&L: $%.2f from previous session",
                    len(state["positions"]),
                    state.get("realized_pnl", 0),
                )
        except Exception:
            logger.exception("Failed to restore state from database")

    await engine.start()

    # PositionManager — auto-exit rules (disabled by default)
    from polystation.automation.position_manager import PositionManager, ExitConfig
    exit_config = ExitConfig(
        trailing_stop_pct=None,
        profit_target_pct=None,
        stop_loss_pct=None,
        max_hold_hours=None,
        expiry_exit_hours=2.0,
        enabled=False,  # user enables from Risk tab
    )
    engine.position_manager = PositionManager(engine, config=exit_config, check_interval=10.0)

    # Background tasks
    tasks = [
        asyncio.create_task(engine.metrics.run_snapshots()),
        asyncio.create_task(_prometheus_scrape_loop(engine.prom, engine)),
        asyncio.create_task(engine.position_manager.start()),
    ]
    if engine.redis and engine.redis.connected:
        tasks.append(asyncio.create_task(_redis_heartbeat_loop(engine.redis)))
        tasks.append(asyncio.create_task(_redis_snapshot_loop(engine)))

    logger.info("Polystation dashboard started")
    yield

    # Shutdown
    engine.metrics.stop()
    for t in tasks:
        t.cancel()

    if engine.position_manager:
        await engine.position_manager.stop()

    for ex in engine.exchanges.values():
        await ex.disconnect()

    if engine.redis:
        engine.redis.close()

    if engine.db:
        engine.db.close()

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

    # API routers
    from polystation.dashboard.api.markets import router as markets_router
    from polystation.dashboard.api.orders import router as orders_router
    from polystation.dashboard.api.strategies import router as strategies_router
    from polystation.dashboard.api.portfolio import router as portfolio_router
    from polystation.dashboard.api.config import router as config_router
    from polystation.dashboard.api.performance import router as performance_router
    from polystation.dashboard.api.risk import router as risk_router
    from polystation.dashboard.api.metrics_endpoint import router as metrics_router
    from polystation.dashboard.api.backtest import router as backtest_router
    from polystation.dashboard.ws import router as ws_router

    app.include_router(markets_router, prefix="/api/markets", tags=["markets"])
    app.include_router(orders_router, prefix="/api/orders", tags=["orders"])
    app.include_router(strategies_router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(config_router, prefix="/api/config", tags=["config"])
    app.include_router(performance_router, prefix="/api/performance", tags=["performance"])
    app.include_router(risk_router, prefix="/api/risk", tags=["risk"])
    app.include_router(metrics_router, tags=["metrics"])
    app.include_router(backtest_router, prefix="/api/backtest", tags=["backtest"])
    app.include_router(ws_router, tags=["websocket"])

    # Static files (SPA) — mount last so API routes take precedence
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
