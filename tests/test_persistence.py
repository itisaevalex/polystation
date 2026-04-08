"""Tests for polystation.persistence — StateDatabase SQLite persistence layer."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from polystation.persistence.database import StateDatabase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path) -> StateDatabase:
    """Connected StateDatabase backed by a temporary file."""
    database = StateDatabase(db_path=str(tmp_path / "test.db"))
    database.connect()
    yield database
    database.close()


@pytest.fixture()
def sample_order() -> dict[str, Any]:
    """Minimal valid order dict matching the orders table schema."""
    return {
        "id": "ORD-000001",
        "token_id": "tok_abc",
        "side": "BUY",
        "price": 0.65,
        "size": 100.0,
        "status": "filled",
        "order_type": "GTC",
        "filled_size": 100.0,
        "avg_fill_price": 0.65,
        "market_id": "mkt_001",
        "kernel_name": "voice_kernel",
        "exchange": "polymarket",
        "server_order_id": "srv-xyz",
        "error": "",
        "created_at": "2026-04-07T12:00:00",
        "updated_at": "2026-04-07T12:00:01",
    }


@pytest.fixture()
def sample_position() -> dict[str, Any]:
    """Minimal valid position dict matching the positions table schema."""
    return {
        "token_id": "tok_abc",
        "market_id": "mkt_001",
        "outcome": "Yes",
        "side": "BUY",
        "size": 100.0,
        "avg_entry_price": 0.65,
        "current_price": 0.70,
        "exchange": "polymarket",
    }


@pytest.fixture()
def sample_trade() -> dict[str, Any]:
    """Minimal valid trade dict matching the trades table schema."""
    return {
        "order_id": "ORD-000001",
        "token_id": "tok_abc",
        "side": "BUY",
        "price": 0.65,
        "size": 100.0,
        "pnl": 0.0,
        "kernel_name": "voice_kernel",
        "exchange": "polymarket",
        "timestamp": "2026-04-07T12:00:00",
    }


@pytest.fixture()
def sample_pnl_snapshot() -> dict[str, Any]:
    """Minimal valid P&L snapshot dict."""
    return {
        "ts": "2026-04-07T12:00:00",
        "realized": 5.0,
        "unrealized": 3.5,
        "total": 8.5,
        "position_count": 2,
        "market_value": 130.0,
        "trade_count": 4,
    }


# ---------------------------------------------------------------------------
# Connection and table creation
# ---------------------------------------------------------------------------


class TestConnect:

    def test_connect_creates_db_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "new.db"
        database = StateDatabase(db_path=str(db_path))
        database.connect()
        assert db_path.exists()
        database.close()

    def test_connect_creates_orders_table(self, db: StateDatabase) -> None:
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'"
        )
        assert cursor.fetchone() is not None

    def test_connect_creates_positions_table(self, db: StateDatabase) -> None:
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='positions'"
        )
        assert cursor.fetchone() is not None

    def test_connect_creates_trades_table(self, db: StateDatabase) -> None:
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        )
        assert cursor.fetchone() is not None

    def test_connect_creates_pnl_snapshots_table(self, db: StateDatabase) -> None:
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pnl_snapshots'"
        )
        assert cursor.fetchone() is not None

    def test_connect_creates_kernel_state_table(self, db: StateDatabase) -> None:
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kernel_state'"
        )
        assert cursor.fetchone() is not None

    def test_wal_mode_is_enabled(self, db: StateDatabase) -> None:
        cursor = db._conn.execute("PRAGMA journal_mode")
        row = cursor.fetchone()
        assert row[0] == "wal"


# ---------------------------------------------------------------------------
# Empty database returns empty lists
# ---------------------------------------------------------------------------


class TestEmptyDatabase:

    def test_get_orders_empty(self, db: StateDatabase) -> None:
        assert db.get_orders() == []

    def test_get_positions_empty(self, db: StateDatabase) -> None:
        assert db.get_positions() == []

    def test_get_trades_empty(self, db: StateDatabase) -> None:
        assert db.get_trades() == []

    def test_get_pnl_snapshots_empty(self, db: StateDatabase) -> None:
        assert db.get_pnl_snapshots() == []

    def test_get_kernel_states_empty(self, db: StateDatabase) -> None:
        assert db.get_kernel_states() == []


# ---------------------------------------------------------------------------
# Orders round-trip
# ---------------------------------------------------------------------------


class TestOrders:

    def test_save_and_retrieve_order(
        self, db: StateDatabase, sample_order: dict[str, Any]
    ) -> None:
        db.save_order(sample_order)
        orders = db.get_orders()
        assert len(orders) == 1
        assert orders[0]["id"] == "ORD-000001"

    def test_order_fields_preserved(
        self, db: StateDatabase, sample_order: dict[str, Any]
    ) -> None:
        db.save_order(sample_order)
        row = db.get_orders()[0]
        assert row["token_id"] == "tok_abc"
        assert row["side"] == "BUY"
        assert row["price"] == pytest.approx(0.65)
        assert row["size"] == pytest.approx(100.0)
        assert row["status"] == "filled"
        assert row["kernel_name"] == "voice_kernel"

    def test_upsert_updates_existing_order(
        self, db: StateDatabase, sample_order: dict[str, Any]
    ) -> None:
        db.save_order(sample_order)
        updated = {**sample_order, "status": "cancelled"}
        db.save_order(updated)
        orders = db.get_orders()
        assert len(orders) == 1
        assert orders[0]["status"] == "cancelled"

    def test_multiple_orders_saved(
        self, db: StateDatabase, sample_order: dict[str, Any]
    ) -> None:
        db.save_order(sample_order)
        second = {**sample_order, "id": "ORD-000002", "created_at": "2026-04-07T13:00:00"}
        db.save_order(second)
        assert len(db.get_orders()) == 2

    def test_get_orders_limit(
        self, db: StateDatabase, sample_order: dict[str, Any]
    ) -> None:
        for i in range(1, 6):
            db.save_order({**sample_order, "id": f"ORD-{i:06d}", "created_at": f"2026-04-07T{i:02d}:00:00"})
        assert len(db.get_orders(limit=3)) == 3

    def test_get_orders_returns_most_recent_first(
        self, db: StateDatabase, sample_order: dict[str, Any]
    ) -> None:
        db.save_order({**sample_order, "id": "ORD-000001", "created_at": "2026-04-07T10:00:00"})
        db.save_order({**sample_order, "id": "ORD-000002", "created_at": "2026-04-07T11:00:00"})
        orders = db.get_orders()
        assert orders[0]["id"] == "ORD-000002"


# ---------------------------------------------------------------------------
# Positions round-trip
# ---------------------------------------------------------------------------


class TestPositions:

    def test_save_and_retrieve_position(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position(sample_position)
        positions = db.get_positions()
        assert len(positions) == 1
        assert positions[0]["token_id"] == "tok_abc"

    def test_position_fields_preserved(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position(sample_position)
        row = db.get_positions()[0]
        assert row["market_id"] == "mkt_001"
        assert row["outcome"] == "Yes"
        assert row["side"] == "BUY"
        assert row["size"] == pytest.approx(100.0)
        assert row["avg_entry_price"] == pytest.approx(0.65)
        assert row["current_price"] == pytest.approx(0.70)

    def test_upsert_updates_existing_position(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position(sample_position)
        updated = {**sample_position, "size": 50.0}
        db.save_position(updated)
        positions = db.get_positions()
        assert len(positions) == 1
        assert positions[0]["size"] == pytest.approx(50.0)

    def test_zero_size_position_excluded_from_get_positions(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position({**sample_position, "size": 0.0})
        assert db.get_positions() == []

    def test_multiple_positions_saved(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position(sample_position)
        db.save_position({**sample_position, "token_id": "tok_xyz", "size": 50.0})
        assert len(db.get_positions()) == 2


# ---------------------------------------------------------------------------
# Trades round-trip
# ---------------------------------------------------------------------------


class TestTrades:

    def test_save_and_retrieve_trade(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        db.save_trade(sample_trade)
        trades = db.get_trades()
        assert len(trades) == 1
        assert trades[0]["order_id"] == "ORD-000001"

    def test_trade_fields_preserved(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        db.save_trade(sample_trade)
        row = db.get_trades()[0]
        assert row["token_id"] == "tok_abc"
        assert row["side"] == "BUY"
        assert row["price"] == pytest.approx(0.65)
        assert row["size"] == pytest.approx(100.0)
        assert row["pnl"] == pytest.approx(0.0)
        assert row["kernel_name"] == "voice_kernel"

    def test_multiple_trades_for_same_order(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        db.save_trade(sample_trade)
        db.save_trade(sample_trade)
        assert len(db.get_trades()) == 2

    def test_get_trades_limit(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        for _ in range(5):
            db.save_trade(sample_trade)
        assert len(db.get_trades(limit=3)) == 3

    def test_trade_autoincrement_id(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        db.save_trade(sample_trade)
        db.save_trade(sample_trade)
        trades = db.get_trades()
        ids = {t["id"] for t in trades}
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# P&L snapshots round-trip
# ---------------------------------------------------------------------------


class TestPnlSnapshots:

    def test_save_and_retrieve_snapshot(
        self, db: StateDatabase, sample_pnl_snapshot: dict[str, Any]
    ) -> None:
        db.save_pnl_snapshot(sample_pnl_snapshot)
        snaps = db.get_pnl_snapshots()
        assert len(snaps) == 1

    def test_snapshot_fields_preserved(
        self, db: StateDatabase, sample_pnl_snapshot: dict[str, Any]
    ) -> None:
        db.save_pnl_snapshot(sample_pnl_snapshot)
        row = db.get_pnl_snapshots()[0]
        assert row["realized"] == pytest.approx(5.0)
        assert row["unrealized"] == pytest.approx(3.5)
        assert row["total"] == pytest.approx(8.5)
        assert row["position_count"] == 2
        assert row["market_value"] == pytest.approx(130.0)
        assert row["trade_count"] == 4

    def test_multiple_snapshots_saved(
        self, db: StateDatabase, sample_pnl_snapshot: dict[str, Any]
    ) -> None:
        db.save_pnl_snapshot(sample_pnl_snapshot)
        db.save_pnl_snapshot(sample_pnl_snapshot)
        assert len(db.get_pnl_snapshots()) == 2

    def test_get_pnl_snapshots_limit(
        self, db: StateDatabase, sample_pnl_snapshot: dict[str, Any]
    ) -> None:
        for _ in range(5):
            db.save_pnl_snapshot(sample_pnl_snapshot)
        assert len(db.get_pnl_snapshots(limit=3)) == 3


# ---------------------------------------------------------------------------
# Kernel state round-trip
# ---------------------------------------------------------------------------


class TestKernelState:

    def test_save_and_retrieve_kernel_state(self, db: StateDatabase) -> None:
        db.save_kernel_state("voice_kernel", {"threshold": 0.7}, "running")
        states = db.get_kernel_states()
        assert len(states) == 1
        assert states[0]["name"] == "voice_kernel"

    def test_kernel_state_fields_preserved(self, db: StateDatabase) -> None:
        db.save_kernel_state("market_maker", {"spread": 0.02}, "stopped")
        row = db.get_kernel_states()[0]
        assert row["last_status"] == "stopped"
        assert row["name"] == "market_maker"

    def test_kernel_config_serialized_as_json(self, db: StateDatabase) -> None:
        import json
        config = {"alpha": 1.5, "beta": [1, 2, 3]}
        db.save_kernel_state("signal_kernel", config, "running")
        row = db.get_kernel_states()[0]
        assert json.loads(row["config"]) == config

    def test_upsert_updates_existing_kernel_state(self, db: StateDatabase) -> None:
        db.save_kernel_state("voice_kernel", {}, "running")
        db.save_kernel_state("voice_kernel", {}, "stopped")
        states = db.get_kernel_states()
        assert len(states) == 1
        assert states[0]["last_status"] == "stopped"

    def test_multiple_kernels_saved(self, db: StateDatabase) -> None:
        db.save_kernel_state("kernel_a", {}, "running")
        db.save_kernel_state("kernel_b", {}, "stopped")
        assert len(db.get_kernel_states()) == 2


# ---------------------------------------------------------------------------
# restore_portfolio_state
# ---------------------------------------------------------------------------


class TestRestorePortfolioState:

    def test_returns_empty_state_on_fresh_db(self, db: StateDatabase) -> None:
        state = db.restore_portfolio_state()
        assert state["positions"] == []
        assert state["realized_pnl"] == pytest.approx(0.0)
        assert state["trade_count"] == 0

    def test_returns_open_positions(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position(sample_position)
        state = db.restore_portfolio_state()
        assert len(state["positions"]) == 1
        assert state["positions"][0]["token_id"] == "tok_abc"

    def test_sums_pnl_correctly(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        db.save_trade({**sample_trade, "pnl": 2.50})
        db.save_trade({**sample_trade, "pnl": -1.25})
        db.save_trade({**sample_trade, "pnl": 0.75})
        state = db.restore_portfolio_state()
        assert state["realized_pnl"] == pytest.approx(2.0)

    def test_trade_count_matches_stored_trades(
        self, db: StateDatabase, sample_trade: dict[str, Any]
    ) -> None:
        for _ in range(7):
            db.save_trade(sample_trade)
        state = db.restore_portfolio_state()
        assert state["trade_count"] == 7

    def test_excludes_zero_size_positions(
        self, db: StateDatabase, sample_position: dict[str, Any]
    ) -> None:
        db.save_position({**sample_position, "size": 0.0})
        state = db.restore_portfolio_state()
        assert state["positions"] == []

    def test_combined_positions_and_pnl(
        self,
        db: StateDatabase,
        sample_position: dict[str, Any],
        sample_trade: dict[str, Any],
    ) -> None:
        db.save_position(sample_position)
        db.save_position({**sample_position, "token_id": "tok_xyz"})
        db.save_trade({**sample_trade, "pnl": 10.0})
        state = db.restore_portfolio_state()
        assert len(state["positions"]) == 2
        assert state["realized_pnl"] == pytest.approx(10.0)
        assert state["trade_count"] == 1


# ---------------------------------------------------------------------------
# Not-connected guard: all methods return empty / no-op gracefully
# ---------------------------------------------------------------------------


class TestDisconnectedDatabase:

    def test_get_orders_returns_empty_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        assert db.get_orders() == []

    def test_get_positions_returns_empty_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        assert db.get_positions() == []

    def test_get_trades_returns_empty_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        assert db.get_trades() == []

    def test_get_pnl_snapshots_returns_empty_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        assert db.get_pnl_snapshots() == []

    def test_get_kernel_states_returns_empty_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        assert db.get_kernel_states() == []

    def test_save_order_no_op_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        # Should not raise
        db.save_order({"id": "x", "token_id": "t", "side": "BUY", "price": 0.5,
                       "size": 10, "status": "pending", "created_at": "2026-04-07T00:00:00"})

    def test_save_position_no_op_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        db.save_position({"token_id": "t", "size": 10.0})

    def test_save_trade_no_op_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        db.save_trade({"order_id": "x", "token_id": "t", "side": "BUY",
                       "price": 0.5, "size": 10, "timestamp": "2026-04-07T00:00:00"})

    def test_save_pnl_snapshot_no_op_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        db.save_pnl_snapshot({"ts": "2026-04-07T00:00:00", "realized": 0.0,
                               "unrealized": 0.0, "total": 0.0})

    def test_save_kernel_state_no_op_when_not_connected(self, tmp_path: Path) -> None:
        db = StateDatabase(db_path=str(tmp_path / "nc.db"))
        db.save_kernel_state("k", {}, "stopped")
