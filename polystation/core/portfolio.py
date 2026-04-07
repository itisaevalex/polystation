"""Portfolio tracking — positions, P&L, and balance management."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """A position in a single prediction market token."""

    token_id: str
    market_id: str = ""
    outcome: str = ""       # "Yes" / "No"
    side: str = ""          # "BUY" / "SELL"
    size: float = 0.0       # Number of shares
    avg_entry_price: float = 0.0
    current_price: float | None = None

    @property
    def cost_basis(self) -> float:
        """Total amount paid to enter the current position."""
        return self.size * self.avg_entry_price

    @property
    def market_value(self) -> float | None:
        """Current mark-to-market value, or None if price is unavailable."""
        if self.current_price is None:
            return None
        return self.size * self.current_price

    @property
    def unrealized_pnl(self) -> float | None:
        """Unrealized profit/loss, or None if price is unavailable."""
        mv = self.market_value
        if mv is None:
            return None
        return mv - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float | None:
        """Unrealized P&L as a percentage of cost basis, or None if unavailable."""
        pnl = self.unrealized_pnl
        if pnl is None or self.cost_basis == 0:
            return None
        return (pnl / self.cost_basis) * 100

    def to_dict(self) -> dict[str, Any]:
        """Serialize the position to a JSON-safe dict."""
        return {
            "token_id": self.token_id,
            "market_id": self.market_id,
            "outcome": self.outcome,
            "side": self.side,
            "size": self.size,
            "avg_entry_price": self.avg_entry_price,
            "current_price": self.current_price,
            "cost_basis": self.cost_basis,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
        }


class Portfolio:
    """Tracks all positions and calculates aggregate P&L.

    Maintains a dictionary of open positions keyed by token_id, a running
    realized P&L total, and a full trade history.  Prices must be pushed in
    externally via update_price() to keep unrealized P&L current.
    """

    def __init__(self) -> None:
        self.positions: dict[str, Position] = {}   # keyed by token_id
        self.realized_pnl: float = 0.0
        self.trade_count: int = 0
        self._trade_history: list[dict[str, Any]] = []

    def record_fill(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        market_id: str = "",
        outcome: str = "",
    ) -> None:
        """Record a trade fill and update the corresponding position.

        For BUY fills the position is increased and the average entry price is
        recalculated using a weighted average.  For SELL fills, realized P&L is
        booked on the closed portion and the position size is reduced.

        Args:
            token_id: Polymarket token identifier for the outcome.
            side: "BUY" or "SELL".
            price: Fill price between 0 and 1.
            size: Number of shares filled.
            market_id: Optional parent market identifier.
            outcome: Optional outcome label, e.g. "Yes" or "No".
        """
        self.trade_count += 1
        self._trade_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "token_id": token_id,
                "side": side,
                "price": price,
                "size": size,
            }
        )

        pos = self.positions.get(token_id)
        if pos is None:
            pos = Position(token_id=token_id, market_id=market_id, outcome=outcome)
            self.positions[token_id] = pos

        if side == "BUY":
            total_cost = pos.cost_basis + (price * size)
            pos.size += size
            pos.avg_entry_price = total_cost / pos.size if pos.size > 0 else 0.0
            pos.side = "BUY"
        elif side == "SELL":
            if pos.size > 0:
                # Realize P&L on the sold portion (capped at existing long size)
                sold = min(size, pos.size)
                pnl = (price - pos.avg_entry_price) * sold
                self.realized_pnl += pnl
                pos.size -= size
                if pos.size <= 0:
                    pos.size = 0.0
                    pos.avg_entry_price = 0.0
            else:
                # Opening or increasing a short position
                total_cost = pos.cost_basis + (price * size)
                pos.size += size
                pos.avg_entry_price = total_cost / pos.size if pos.size > 0 else 0.0
                pos.side = "SELL"

        logger.info(
            "Fill recorded: %s %s %.0f @ %.4f (token %s)",
            side,
            outcome,
            size,
            price,
            token_id[:20],
        )

    def update_price(self, token_id: str, price: float) -> None:
        """Push a current market price into the matching position.

        Args:
            token_id: Token whose price has changed.
            price: Latest mid/last price.
        """
        pos = self.positions.get(token_id)
        if pos:
            pos.current_price = price

    def get_position(self, token_id: str) -> Position | None:
        """Return the Position for *token_id*, or None if not held."""
        return self.positions.get(token_id)

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized P&L across all positions with a known price."""
        total = 0.0
        for pos in self.positions.values():
            pnl = pos.unrealized_pnl
            if pnl is not None:
                total += pnl
        return total

    @property
    def total_pnl(self) -> float:
        """Combined realized and unrealized P&L."""
        return self.realized_pnl + self.total_unrealized_pnl

    @property
    def total_market_value(self) -> float:
        """Sum of mark-to-market value across all positions with a known price."""
        total = 0.0
        for pos in self.positions.values():
            mv = pos.market_value
            if mv is not None:
                total += mv
        return total

    def get_summary(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of portfolio state.

        Returns:
            Dict with positions (non-zero only), P&L figures, market value,
            and trade count.
        """
        return {
            "positions": {
                tid: p.to_dict()
                for tid, p in self.positions.items()
                if p.size > 0
            },
            "position_count": sum(1 for p in self.positions.values() if p.size > 0),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(self.total_unrealized_pnl, 4),
            "total_pnl": round(self.total_pnl, 4),
            "total_market_value": round(self.total_market_value, 4),
            "trade_count": self.trade_count,
        }
