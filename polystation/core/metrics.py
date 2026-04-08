"""In-memory performance tracking — P&L time-series, per-kernel stats, trade history."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KernelStats:
    """Aggregated performance stats for a single kernel."""

    name: str
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_pnl: float = 0.0
    total_volume: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_fill_price: float = 0.0
    _fill_prices_sum: float = field(default=0.0, repr=False)
    _slippage_sum: float = field(default=0.0, repr=False)
    _slippage_count: int = field(default=0, repr=False)

    @property
    def win_rate(self) -> float:
        """Fraction of closed trades that were profitable."""
        total = self.win_count + self.loss_count
        return self.win_count / total if total > 0 else 0.0

    @property
    def avg_slippage(self) -> float:
        """Mean absolute slippage across all fills."""
        return self._slippage_sum / self._slippage_count if self._slippage_count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize stats to a JSON-safe dict."""
        return {
            "name": self.name,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": round(self.win_rate, 4),
            "total_pnl": round(self.total_pnl, 4),
            "total_volume": round(self.total_volume, 4),
            "best_trade": round(self.best_trade, 4),
            "worst_trade": round(self.worst_trade, 4),
            "avg_slippage": round(self.avg_slippage, 4),
        }


@dataclass
class TradeRecord:
    """A single recorded trade for the history log."""

    timestamp: str
    kernel_name: str
    order_id: str
    token_id: str
    side: str
    price: float
    size: float
    pnl: float       # realized P&L from this fill (0 for buys)
    slippage: float  # abs(order_price - fill_price)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the trade record to a JSON-safe dict."""
        return vars(self)


class MetricsCollector:
    """Aggregates performance data from the trading engine.

    Tracks per-kernel stats, rolling P&L time-series, and trade history.
    All data is in-memory — no external dependencies required.

    Attributes:
        snapshot_interval: Seconds between automatic P&L snapshots.
        kernel_stats: Per-kernel aggregated statistics keyed by kernel name.
        trade_history: Rolling deque of individual trade records (newest first).
        pnl_snapshots: Rolling deque of time-series P&L data points.
    """

    def __init__(
        self,
        snapshot_interval: float = 5.0,
        max_history: int = 10000,
        max_snapshots: int = 8640,
    ) -> None:
        self.snapshot_interval = snapshot_interval
        self.kernel_stats: dict[str, KernelStats] = {}
        self.trade_history: deque[TradeRecord] = deque(maxlen=max_history)
        self.pnl_snapshots: deque[dict[str, Any]] = deque(maxlen=max_snapshots)
        self._running = False
        # References set after construction via set_references()
        self._portfolio: Any = None
        self._orders: Any = None
        self._db: Any = None  # StateDatabase — set via set_database()

    def set_references(self, portfolio: Any, orders: Any) -> None:
        """Set references to Portfolio and OrderManager for snapshot access.

        Args:
            portfolio: Portfolio instance to read P&L and positions from.
            orders: OrderManager instance (reserved for future use).
        """
        self._portfolio = portfolio
        self._orders = orders

    def set_database(self, db: Any) -> None:
        """Attach a StateDatabase for persistent snapshot storage.

        Args:
            db: Connected :class:`~polystation.persistence.database.StateDatabase`
                instance.  When set, every call to :meth:`snapshot` will also
                persist the snapshot to SQLite.
        """
        self._db = db

    def record_fill(
        self,
        order_id: str,
        token_id: str,
        side: str,
        order_price: float,
        fill_price: float,
        fill_size: float,
        kernel_name: str,
        realized_pnl: float = 0.0,
    ) -> None:
        """Record a trade fill and update per-kernel stats.

        Args:
            order_id: Internal order identifier.
            token_id: Polymarket token identifier.
            side: "BUY" or "SELL".
            order_price: The price specified on the order.
            fill_price: The actual price at which the fill occurred.
            fill_size: Number of shares filled.
            kernel_name: Name of the kernel that placed the order.
            realized_pnl: Realized profit/loss booked by this fill (sells only).
        """
        if kernel_name not in self.kernel_stats:
            self.kernel_stats[kernel_name] = KernelStats(name=kernel_name)
        ks = self.kernel_stats[kernel_name]

        slippage = abs(order_price - fill_price)

        ks.trade_count += 1
        ks.total_volume += fill_price * fill_size
        ks._fill_prices_sum += fill_price
        ks._slippage_sum += slippage
        ks._slippage_count += 1

        if side == "SELL" and realized_pnl != 0:
            ks.total_pnl += realized_pnl
            if realized_pnl > 0:
                ks.win_count += 1
                ks.best_trade = max(ks.best_trade, realized_pnl)
            else:
                ks.loss_count += 1
                ks.worst_trade = min(ks.worst_trade, realized_pnl)

        safe_token = token_id[:20] + "..." if len(token_id) > 20 else token_id
        record = TradeRecord(
            timestamp=datetime.now().isoformat(),
            kernel_name=kernel_name,
            order_id=order_id,
            token_id=safe_token,
            side=side,
            price=fill_price,
            size=fill_size,
            pnl=realized_pnl,
            slippage=slippage,
        )
        self.trade_history.appendleft(record)
        logger.debug(
            "Recorded fill: %s %s %.0f @ %.4f (kernel=%s)",
            side,
            safe_token,
            fill_size,
            fill_price,
            kernel_name,
        )

    def snapshot(self) -> None:
        """Capture a P&L time-series point from the current portfolio state."""
        if self._portfolio is None:
            return
        p = self._portfolio
        snap: dict[str, Any] = {
            "ts": datetime.now().isoformat(),
            "realized": round(p.realized_pnl, 4),
            "unrealized": round(p.total_unrealized_pnl, 4),
            "total": round(p.total_pnl, 4),
            "position_count": sum(1 for pos in p.positions.values() if pos.size > 0),
            "market_value": round(p.total_market_value, 4),
            "trade_count": p.trade_count,
        }
        self.pnl_snapshots.append(snap)
        if self._db is not None:
            try:
                self._db.save_pnl_snapshot(snap)
            except Exception:
                logger.exception("Failed to persist P&L snapshot to database")

    async def run_snapshots(self) -> None:
        """Background task that takes periodic P&L snapshots."""
        self._running = True
        while self._running:
            self.snapshot()
            await asyncio.sleep(self.snapshot_interval)

    def stop(self) -> None:
        """Signal the snapshot loop to exit on the next iteration."""
        self._running = False

    def get_performance_summary(self) -> dict[str, Any]:
        """Return a full performance summary for the dashboard.

        Returns:
            Dict with aggregate trade stats across all kernels.
        """
        total_trades = sum(ks.trade_count for ks in self.kernel_stats.values())
        total_wins = sum(ks.win_count for ks in self.kernel_stats.values())
        total_losses = sum(ks.loss_count for ks in self.kernel_stats.values())
        total_pnl = sum(ks.total_pnl for ks in self.kernel_stats.values())
        total_volume = sum(ks.total_volume for ks in self.kernel_stats.values())

        win_rate = (
            total_wins / (total_wins + total_losses)
            if (total_wins + total_losses) > 0
            else 0.0
        )

        return {
            "total_trades": total_trades,
            "total_pnl": round(total_pnl, 4),
            "total_volume": round(total_volume, 4),
            "win_rate": round(win_rate, 4),
            "win_count": total_wins,
            "loss_count": total_losses,
            "kernel_count": len(self.kernel_stats),
            "active_since": self.pnl_snapshots[0]["ts"] if self.pnl_snapshots else None,
        }

    def get_pnl_history(self, limit: int = 500) -> list[dict[str, Any]]:
        """Return P&L time-series snapshots, downsampled when needed.

        Args:
            limit: Maximum number of data points to return.

        Returns:
            List of snapshot dicts ordered oldest-first.
        """
        snaps = list(self.pnl_snapshots)
        if limit and len(snaps) > limit:
            step = max(1, len(snaps) // limit)
            snaps = snaps[::step]
        return snaps

    def get_trade_history(
        self, limit: int = 100, kernel: str | None = None
    ) -> list[dict[str, Any]]:
        """Return recent trade records, optionally filtered by kernel.

        Args:
            limit: Maximum number of records to return.
            kernel: When provided, only records for this kernel are returned.

        Returns:
            List of trade record dicts, most-recent first.
        """
        trades = list(self.trade_history)
        if kernel:
            trades = [t for t in trades if t.kernel_name == kernel]
        return [t.to_dict() for t in trades[:limit]]

    def get_kernel_stats(self) -> list[dict[str, Any]]:
        """Return per-kernel performance breakdown.

        Returns:
            List of KernelStats dicts, one per kernel seen.
        """
        return [ks.to_dict() for ks in self.kernel_stats.values()]

    def get_risk_summary(self) -> dict[str, Any]:
        """Return risk-related data derived from current portfolio state.

        Returns:
            Dict with exposure, P&L totals, and the largest open position.
        """
        if self._portfolio is None:
            return {"error": "no portfolio"}
        p = self._portfolio
        positions = [pos for pos in p.positions.values() if pos.size > 0]
        largest = (
            max(positions, key=lambda x: abs(x.cost_basis)) if positions else None
        )

        return {
            "gross_exposure": round(p.total_market_value, 4),
            "position_count": len(positions),
            "realized_pnl": round(p.realized_pnl, 4),
            "unrealized_pnl": round(p.total_unrealized_pnl, 4),
            "total_pnl": round(p.total_pnl, 4),
            "trade_count": p.trade_count,
            "largest_position": {
                "token_id": largest.token_id,
                "size": largest.size,
                "cost_basis": round(largest.cost_basis, 4),
                "unrealized_pnl": round(largest.unrealized_pnl or 0, 4),
            }
            if largest
            else None,
        }
