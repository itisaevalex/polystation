"""SQLite database for persistent state."""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from polystation.persistence.models import ALL_TABLES

logger = logging.getLogger(__name__)


class StateDatabase:
    """SQLite-backed state persistence.

    Synchronous (sqlite3 is thread-safe with check_same_thread=False).
    Uses WAL journal mode for concurrent read performance and NORMAL
    synchronous mode for an acceptable durability/speed trade-off.

    Args:
        db_path: Path to the SQLite database file.  The parent directory is
            created automatically if it does not already exist.
    """

    def __init__(self, db_path: str = "data/polystation.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the database connection and create tables if missing."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        for table_sql in ALL_TABLES:
            self._conn.execute(table_sql)
        self._conn.commit()
        logger.info("StateDatabase connected: %s", self.db_path)

    def close(self) -> None:
        """Close the database connection if it is open."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def save_order(self, order_dict: dict[str, Any]) -> None:
        """Upsert an order record.

        Args:
            order_dict: Dict produced by :meth:`Order.to_dict`.
        """
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT OR REPLACE INTO orders
            (id, token_id, side, price, size, status, order_type, filled_size,
             avg_fill_price, market_id, kernel_name, exchange, server_order_id,
             error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_dict.get("id"),
                order_dict.get("token_id"),
                order_dict.get("side"),
                order_dict.get("price"),
                order_dict.get("size"),
                order_dict.get("status"),
                order_dict.get("order_type", "GTC"),
                order_dict.get("filled_size", 0),
                order_dict.get("avg_fill_price", 0),
                order_dict.get("market_id", ""),
                order_dict.get("kernel_name", ""),
                order_dict.get("exchange", ""),
                order_dict.get("server_order_id", ""),
                order_dict.get("error", ""),
                order_dict.get("created_at", ""),
                order_dict.get("updated_at", ""),
            ),
        )
        self._conn.commit()

    def save_position(self, pos_dict: dict[str, Any]) -> None:
        """Upsert a position record.

        Args:
            pos_dict: Dict produced by :meth:`Position.to_dict` (or equivalent).
        """
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT OR REPLACE INTO positions
            (token_id, market_id, outcome, side, size, avg_entry_price,
             current_price, exchange, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pos_dict.get("token_id"),
                pos_dict.get("market_id", ""),
                pos_dict.get("outcome", ""),
                pos_dict.get("side", ""),
                pos_dict.get("size", 0),
                pos_dict.get("avg_entry_price", 0),
                pos_dict.get("current_price"),
                pos_dict.get("exchange", ""),
                datetime.now().isoformat(),
            ),
        )
        self._conn.commit()

    def save_trade(self, trade_dict: dict[str, Any]) -> None:
        """Insert a new trade record.

        Args:
            trade_dict: Dict with keys: order_id, token_id, side, price,
                size, pnl, kernel_name, exchange, timestamp.
        """
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT INTO trades (order_id, token_id, side, price, size, pnl,
                               kernel_name, exchange, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_dict.get("order_id", ""),
                trade_dict.get("token_id", ""),
                trade_dict.get("side", ""),
                trade_dict.get("price", 0),
                trade_dict.get("size", 0),
                trade_dict.get("pnl", 0),
                trade_dict.get("kernel_name", ""),
                trade_dict.get("exchange", ""),
                trade_dict.get("timestamp", datetime.now().isoformat()),
            ),
        )
        self._conn.commit()

    def save_pnl_snapshot(self, snap: dict[str, Any]) -> None:
        """Insert a P&L snapshot row.

        Args:
            snap: Dict with keys: ts, realized, unrealized, total,
                position_count, market_value, trade_count.
        """
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT INTO pnl_snapshots (timestamp, realized, unrealized, total,
                                       position_count, market_value, trade_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snap.get("ts", datetime.now().isoformat()),
                snap.get("realized", 0),
                snap.get("unrealized", 0),
                snap.get("total", 0),
                snap.get("position_count", 0),
                snap.get("market_value", 0),
                snap.get("trade_count", 0),
            ),
        )
        self._conn.commit()

    def save_kernel_state(self, name: str, config: dict[str, Any], status: str) -> None:
        """Upsert a kernel state record.

        Args:
            name: Kernel name (primary key).
            config: Kernel configuration dict (serialized as JSON).
            status: Current kernel status string (e.g. "running", "stopped").
        """
        if not self._conn:
            return
        self._conn.execute(
            """
            INSERT OR REPLACE INTO kernel_state (name, config, last_status, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (name, json.dumps(config), status, datetime.now().isoformat()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent orders ordered by creation time descending.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of order dicts, or empty list when not connected.
        """
        if not self._conn:
            return []
        cursor = self._conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_positions(self) -> list[dict[str, Any]]:
        """Return all open positions (size > 0).

        Returns:
            List of position dicts, or empty list when not connected.
        """
        if not self._conn:
            return []
        cursor = self._conn.execute("SELECT * FROM positions WHERE size > 0")
        return [dict(row) for row in cursor.fetchall()]

    def get_trades(self, limit: int = 500) -> list[dict[str, Any]]:
        """Return the most recent trade records ordered by insertion descending.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of trade dicts, or empty list when not connected.
        """
        if not self._conn:
            return []
        cursor = self._conn.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_pnl_snapshots(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Return the most recent P&L snapshots ordered by insertion descending.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            List of snapshot dicts, or empty list when not connected.
        """
        if not self._conn:
            return []
        cursor = self._conn.execute(
            "SELECT * FROM pnl_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_kernel_states(self) -> list[dict[str, Any]]:
        """Return all kernel state records.

        Returns:
            List of kernel state dicts, or empty list when not connected.
        """
        if not self._conn:
            return []
        cursor = self._conn.execute("SELECT * FROM kernel_state")
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # Restoration helper
    # ------------------------------------------------------------------

    def restore_portfolio_state(self) -> dict[str, Any]:
        """Load positions and realized P&L for Portfolio hydration on restart.

        Returns:
            Dict with keys ``positions`` (list), ``realized_pnl`` (float),
            and ``trade_count`` (int).
        """
        positions = self.get_positions()
        trades = self.get_trades(limit=10000)
        realized_pnl = sum(t.get("pnl", 0) for t in trades)
        return {
            "positions": positions,
            "realized_pnl": realized_pnl,
            "trade_count": len(trades),
        }
