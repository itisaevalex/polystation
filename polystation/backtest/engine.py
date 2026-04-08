"""Backtesting engine — replays price data through a kernel with a PaperExchange."""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Summary of a completed backtest run.

    Attributes:
        total_pnl: Total profit-and-loss over the run period.
        total_trades: Number of executions recorded by the paper exchange.
        win_count: Number of profitable trades (SELL-side fills).
        loss_count: Number of losing trades.
        max_drawdown: Peak-to-trough equity drawdown in USD.
        sharpe_ratio: Annualised Sharpe ratio computed from per-tick P&L returns.
        pnl_curve: P&L sampled at every price tick.
        trade_log: Raw trade records from :class:`~polystation.exchanges.paper.PaperExchange`.
        final_balance: Cash balance at the end of the backtest.
    """

    total_pnl: float = 0.0
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    pnl_curve: list[float] = field(default_factory=list)
    trade_log: list[dict[str, Any]] = field(default_factory=list)
    final_balance: float = 0.0

    @property
    def win_rate(self) -> float:
        """Fraction of winning trades over total resolved trades.

        Returns:
            Value between 0.0 and 1.0, or 0.0 when no trades have resolved.
        """
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe summary dictionary.

        Returns:
            Dict with rounded numeric fields and ``pnl_curve_length`` instead
            of the full curve (which can be large).
        """
        return {
            "total_pnl": round(self.total_pnl, 4),
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "final_balance": round(self.final_balance, 4),
            "pnl_curve_length": len(self.pnl_curve),
        }

    def summary(self) -> str:
        """Return a single-line human-readable summary.

        Returns:
            Formatted string with key metrics.
        """
        return (
            f"P&L: ${self.total_pnl:+.2f} | Trades: {self.total_trades} | "
            f"Win Rate: {self.win_rate:.1%} | Max DD: ${self.max_drawdown:.2f} | "
            f"Sharpe: {self.sharpe_ratio:.2f}"
        )


class BacktestEngine:
    """Replays price data through a kernel using a :class:`~polystation.exchanges.paper.PaperExchange`.

    The engine wires a fresh :class:`~polystation.core.engine.TradingEngine` around
    a :class:`~polystation.exchanges.paper.PaperExchange` and injects each price tick
    into the exchange before giving the kernel an opportunity to react.

    Args:
        start_balance: Initial simulated USD balance. Defaults to 10 000.
        slippage_bps: One-way slippage in basis points. Defaults to 5 bps.
    """

    def __init__(
        self,
        start_balance: float = 10000.0,
        slippage_bps: float = 5.0,
    ) -> None:
        self.start_balance = start_balance
        self.slippage_bps = slippage_bps

    async def run(
        self,
        kernel: Any,
        price_data: list[dict[str, Any]],
        token_id: str,
    ) -> BacktestResult:
        """Execute a backtest by replaying *price_data* through *kernel*.

        Args:
            kernel: A :class:`~polystation.core.kernel.Kernel` instance.
                Must expose ``start`` / ``stop`` and, optionally,
                ``_check_signal`` or ``_refresh_quotes`` for per-tick hooks.
            price_data: Ordered list of ``{"timestamp": str, "price": float}``
                dicts representing historical price samples.
            token_id: The symbol to trade during the backtest.

        Returns:
            :class:`BacktestResult` containing P&L, trade counts, drawdown,
            and Sharpe ratio.
        """
        from polystation.exchanges.paper import PaperExchange
        from polystation.core.engine import TradingEngine
        from polystation.core.orders import OrderManager
        from polystation.core.portfolio import Portfolio
        from polystation.trading.execution import ExecutionEngine

        # Build a fully isolated backtest environment
        exchange = PaperExchange(
            initial_balance=self.start_balance,
            slippage_bps=self.slippage_bps,
        )
        engine = TradingEngine()
        engine.portfolio = Portfolio()
        engine.orders = OrderManager()
        engine.execution = ExecutionEngine(exchange, engine.orders, engine.portfolio)
        engine.execution.set_dry_run(False)  # Use PaperExchange for real fills
        engine.register_exchange(exchange)

        # Provide a minimal market data interface backed by PaperExchange prices
        engine.market_data = _BacktestMarketData(exchange)

        await engine.start()

        # Attach and start the kernel
        kernel.engine = engine
        engine.register_kernel(kernel)
        await engine.start_kernel(kernel.name)

        # ------------------------------------------------------------------
        # Price replay loop
        # ------------------------------------------------------------------
        pnl_curve: list[float] = []
        peak_pnl: float = 0.0
        max_drawdown: float = 0.0
        returns: list[float] = []
        prev_pnl: float = 0.0

        for tick in price_data:
            price = tick.get("price", 0)
            if price <= 0:
                continue

            exchange.set_price(token_id, price)

            # Let the kernel react to the new price tick
            if hasattr(kernel, "_check_signal"):
                await kernel._check_signal()
            elif hasattr(kernel, "_refresh_quotes"):
                await kernel._refresh_quotes()

            # Track P&L curve and drawdown
            current_pnl = exchange.get_pnl()
            pnl_curve.append(current_pnl)

            if current_pnl > peak_pnl:
                peak_pnl = current_pnl
            drawdown = peak_pnl - current_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown

            # Collect per-tick returns for Sharpe calculation
            returns.append(current_pnl - prev_pnl)
            prev_pnl = current_pnl

        # Tear down kernel and engine
        await engine.stop_kernel(kernel.name)
        await engine.stop()

        # ------------------------------------------------------------------
        # Sharpe ratio (annualised, assuming daily ticks)
        # ------------------------------------------------------------------
        sharpe = 0.0
        if len(returns) > 1:
            avg_ret = sum(returns) / len(returns)
            variance = sum((r - avg_ret) ** 2 for r in returns) / (len(returns) - 1)
            std_ret = math.sqrt(variance)
            if std_ret > 0:
                sharpe = (avg_ret / std_ret) * math.sqrt(252)

        # ------------------------------------------------------------------
        # Win/loss count — use SELL fills as proxies for closed positions
        # ------------------------------------------------------------------
        wins = sum(
            1
            for t in exchange._trade_log
            if t.get("side") == "SELL" and t.get("price", 0) > 0
        )

        return BacktestResult(
            total_pnl=exchange.get_pnl(),
            total_trades=len(exchange._trade_log),
            win_count=wins,
            loss_count=0,   # full entry/exit matching is left to callers
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            pnl_curve=pnl_curve,
            trade_log=list(exchange._trade_log),
            final_balance=exchange.balance,
        )


class _BacktestMarketData:
    """Minimal market data adapter backed by :class:`~polystation.exchanges.paper.PaperExchange` prices.

    Exposes the same interface that kernels expect from a live
    :class:`~polystation.market.client.MarketDataClient` but reads from the
    paper exchange's internal price dict so no network calls are needed.

    Args:
        exchange: Configured :class:`~polystation.exchanges.paper.PaperExchange` instance.
    """

    def __init__(self, exchange: Any) -> None:
        self._exchange = exchange

    def get_midpoint(self, token_id: str) -> float | None:
        """Return the current price for *token_id*.

        Args:
            token_id: Token or instrument identifier.

        Returns:
            Current price, or None when not set.
        """
        return self._exchange._prices.get(token_id)

    def get_price(self, token_id: str, side: str) -> float | None:
        """Return the slippage-adjusted price for *token_id* on *side*.

        Args:
            token_id: Token or instrument identifier.
            side: ``"BUY"`` or ``"SELL"``.

        Returns:
            Adjusted price, or None when not set.
        """
        price = self._exchange._prices.get(token_id)
        if price is None:
            return None
        slippage = price * (self._exchange.slippage_bps / 10000)
        return price + slippage if side == "BUY" else price - slippage

    def health(self) -> bool:
        """Always returns True — the paper market data is always available.

        Returns:
            ``True``
        """
        return True
