"""Pre-trade risk management — multi-level veto system."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Configuration thresholds for the RiskGuard.

    Attributes:
        max_stake_per_trade: Maximum USD value for a single trade.
        max_gross_exposure: Maximum total portfolio market value in USD.
        max_position_per_token: Maximum USD value for any single token position.
        daily_loss_stop: Negative USD threshold that halts all trading for the day.
        max_active_orders: Maximum number of simultaneously active orders.
        max_daily_trades: Maximum number of trades executed within one UTC day.
        enabled: When False all checks are bypassed (pass-through mode).
    """

    max_stake_per_trade: float = 500.0
    max_gross_exposure: float = 10000.0
    max_position_per_token: float = 1000.0
    daily_loss_stop: float = -500.0
    max_active_orders: int = 50
    max_daily_trades: int = 200
    enabled: bool = True


class RiskGuard:
    """Pre-trade risk gatekeeper. Runs synchronous checks before order submission.

    Evaluates a candidate order against a series of configurable limits and
    either approves it or vetoes it with a human-readable reason.  A veto log
    of the last 100 rejections is maintained for dashboard inspection.
    """

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()
        self.daily_trade_count: int = 0
        self.daily_loss: float = 0.0
        self._day_start: datetime = datetime.now(timezone.utc)
        self._vetoes: list[dict[str, Any]] = []  # recent veto log

    def check(self, order: Any, portfolio: Any, orders: Any) -> tuple[bool, str]:
        """Run all risk checks against the candidate order.

        Evaluates checks in priority order.  Returns on the first failure so
        the caller receives a single, actionable rejection reason.

        Args:
            order: Order object with ``price``, ``size``, ``token_id``, and ``id``.
            portfolio: Portfolio instance exposing ``total_market_value``,
                ``realized_pnl``, and ``get_position()``.
            orders: OrderManager instance exposing ``get_active_orders()``.

        Returns:
            Tuple of ``(allowed, reason)``.  ``allowed`` is True when all
            checks pass; ``reason`` is an empty string on approval and a
            human-readable explanation on rejection.
        """
        if not self.config.enabled:
            return True, ""

        # Reset daily counters if new day
        self._check_day_reset()

        # 1. Max stake per trade
        trade_value = order.price * order.size
        if trade_value > self.config.max_stake_per_trade:
            return self._veto(
                order,
                f"Trade value ${trade_value:.2f} exceeds max stake ${self.config.max_stake_per_trade:.2f}",
            )

        # 2. Max gross exposure
        current_exposure = portfolio.total_market_value if portfolio else 0
        if current_exposure + trade_value > self.config.max_gross_exposure:
            return self._veto(
                order,
                (
                    f"Gross exposure would be ${current_exposure + trade_value:.2f},"
                    f" exceeds max ${self.config.max_gross_exposure:.2f}"
                ),
            )

        # 3. Max position per token
        if portfolio:
            pos = portfolio.get_position(order.token_id)
            if pos and pos.size > 0:
                new_size_value = (pos.size + order.size) * order.price
                if new_size_value > self.config.max_position_per_token:
                    return self._veto(
                        order,
                        (
                            f"Position in token would be ${new_size_value:.2f},"
                            f" exceeds max ${self.config.max_position_per_token:.2f}"
                        ),
                    )

        # 4. Daily loss stop
        daily_pnl = portfolio.realized_pnl if portfolio else 0  # simplified — should track daily only
        if daily_pnl <= self.config.daily_loss_stop:
            return self._veto(
                order,
                f"Daily P&L ${daily_pnl:.2f} hit loss stop ${self.config.daily_loss_stop:.2f}",
            )

        # 5. Max active orders
        if orders:
            active_count = len(orders.get_active_orders())
            if active_count >= self.config.max_active_orders:
                return self._veto(
                    order,
                    f"Active orders ({active_count}) at max ({self.config.max_active_orders})",
                )

        # 6. Max daily trades
        if self.daily_trade_count >= self.config.max_daily_trades:
            return self._veto(
                order,
                f"Daily trades ({self.daily_trade_count}) at max ({self.config.max_daily_trades})",
            )

        # All checks passed
        self.daily_trade_count += 1
        return True, ""

    def _veto(self, order: Any, reason: str) -> tuple[bool, str]:
        """Record a veto and return the rejection tuple.

        Args:
            order: The order being rejected.
            reason: Human-readable rejection reason.

        Returns:
            Always ``(False, reason)``.
        """
        logger.warning("RiskGuard VETO: %s (order %s)", reason, order.id)
        self._vetoes.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "order_id": order.id,
                "reason": reason,
            }
        )
        if len(self._vetoes) > 100:
            self._vetoes = self._vetoes[-100:]
        return False, reason

    def _check_day_reset(self) -> None:
        """Reset daily counters when the UTC day has rolled over."""
        now = datetime.now(timezone.utc)
        if now.date() > self._day_start.date():
            self.daily_trade_count = 0
            self.daily_loss = 0.0
            self._day_start = now
            logger.info("RiskGuard daily counters reset")

    def record_loss(self, amount: float) -> None:
        """Record a realized loss for daily P&L tracking.

        Args:
            amount: Realized P&L amount.  Only negative values are accumulated.
        """
        if amount < 0:
            self.daily_loss += amount

    def get_status(self) -> dict[str, Any]:
        """Return the current RiskGuard state for dashboard display.

        Returns:
            Dict with enabled flag, config thresholds, daily counters, and
            the ten most-recent vetoes.
        """
        return {
            "enabled": self.config.enabled,
            "config": {
                "max_stake_per_trade": self.config.max_stake_per_trade,
                "max_gross_exposure": self.config.max_gross_exposure,
                "max_position_per_token": self.config.max_position_per_token,
                "daily_loss_stop": self.config.daily_loss_stop,
                "max_active_orders": self.config.max_active_orders,
                "max_daily_trades": self.config.max_daily_trades,
            },
            "daily_trade_count": self.daily_trade_count,
            "daily_loss": round(self.daily_loss, 4),
            "recent_vetoes": self._vetoes[-10:],
        }

    def update_config(self, **kwargs: Any) -> None:
        """Update one or more RiskConfig fields at runtime.

        Unknown keys are silently ignored so callers can pass arbitrary dicts
        without causing errors.

        Args:
            **kwargs: Field names and their new values.
        """
        for key, val in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, val)
                logger.info("RiskGuard config updated: %s = %s", key, val)

    def reset_daily(self) -> None:
        """Force-reset daily counters regardless of the current time."""
        self.daily_trade_count = 0
        self.daily_loss = 0.0
        self._day_start = datetime.now(timezone.utc)
