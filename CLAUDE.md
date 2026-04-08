# Polystation — Development Context

## Project
Universal trading kernel harness for Polymarket, Deribit, Binance, IBKR. Web dashboard, pluggable strategy kernels, live execution, performance tracking.

## Tech Stack
- Python 3.10+, FastAPI, uvicorn, asyncio
- py-clob-client (Polymarket CLOB), websockets, aiohttp
- Prometheus (optional), Redis (optional), Grafana (Docker)
- Chart.js (CDN) for frontend charts

## Package Structure
- `polystation/core/` — engine, kernel ABC, portfolio, orders, events, metrics, risk, prometheus
- `polystation/exchanges/` — Exchange ABC, polymarket adapter (deribit/binance coming)
- `polystation/market/` — MarketDataClient, OrderBook, MarketScanner, MarketFeed (WS)
- `polystation/trading/` — ExecutionEngine (async), order submission, recorder
- `polystation/kernels/` — voice, market-maker, signal (agentic coming)
- `polystation/dashboard/` — FastAPI app, 5 tabs (Trading/Logs/Settings/Performance/Risk)
- `polystation/infra/` — RedisManager (optional)
- `polystation/automation/` — (coming) PositionManager
- `polystation/persistence/` — (coming) SQLite state
- `polystation/backtest/` — (coming) BacktestEngine

## Commands
```bash
# Run tests (465 pass, 11 skip for Redis)
pytest tests/

# Start dashboard
uvicorn polystation.dashboard.app:create_app --factory --port 8420 --host 0.0.0.0

# Start monitoring stack
docker compose -f docker-compose.monitoring.yml up -d

# Lint
ruff check polystation/
```

## Git Remotes
- `origin` → github.com:itisaevalex/polystation.git (public)
- `private` → github.com:itisaevalex/polystation-private.git (private — push here)

## Key Patterns
- Exchange ABC is fully async — sync clients use asyncio.to_thread()
- ExecutionEngine.submit_order() is async — kernels use await, VoiceKernel uses submit_order_sync()
- Everything works without Redis/Prometheus (graceful degradation)
- Gamma API /public-search for market text search (NOT /markets params)
- All tests hit live API — no mocking

## Current Build Checklist (Phase 3)

### Done
- [x] Commit 1: Exchange ABC + PolymarketExchange adapter
- [x] Commit 2: Persistent state (SQLite) — 5 tables, WAL mode, restore on startup
- [x] Commit 3: Position exit automation — PositionManager with trailing stop, profit target, stop loss, time exit
- [x] Commits from Phase 1-2: core engine, market data, portfolio, orders, execution, 3 kernels, dashboard (5 tabs), RiskGuard, Prometheus, Redis, Grafana, MetricsCollector

### Remaining
- [ ] IBKR exchange adapter (TWS API)
- [ ] Historical data loader for backtesting (CSV file import, Polymarket trades API bulk download)
- [ ] Wire RiskGuard config form on Risk tab to POST /api/risk/guard
- [ ] Wire exit config form on Risk tab to POST /api/risk/exits

### Done (all wired)
- [x] PositionManager in app.py lifespan (disabled by default)
- [x] Backtest tab with form + Chart.js P&L chart
- [x] Portfolio state restore from SQLite on startup
- [x] Quick Trade panel in order book (BUY/SELL + auto-price)
- [x] Price history charts (modal overlay, 1D/1W/1M/ALL intervals)
- [x] Manual order placement API (POST /api/orders/create)

## Test Count
728 passed, 11 skipped (Redis live tests)
