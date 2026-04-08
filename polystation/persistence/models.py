"""SQL table definitions as string constants for the SQLite persistence layer."""
from __future__ import annotations

ORDERS_TABLE = """CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, token_id TEXT NOT NULL, side TEXT NOT NULL,
    price REAL NOT NULL, size REAL NOT NULL, status TEXT NOT NULL,
    order_type TEXT DEFAULT 'GTC', filled_size REAL DEFAULT 0.0,
    avg_fill_price REAL DEFAULT 0.0, market_id TEXT DEFAULT '',
    kernel_name TEXT DEFAULT '', exchange TEXT DEFAULT '',
    server_order_id TEXT DEFAULT '', error TEXT DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT DEFAULT ''
)"""

POSITIONS_TABLE = """CREATE TABLE IF NOT EXISTS positions (
    token_id TEXT PRIMARY KEY, market_id TEXT DEFAULT '',
    outcome TEXT DEFAULT '', side TEXT DEFAULT '',
    size REAL DEFAULT 0.0, avg_entry_price REAL DEFAULT 0.0,
    current_price REAL, exchange TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
)"""

TRADES_TABLE = """CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT, token_id TEXT, side TEXT,
    price REAL, size REAL, pnl REAL DEFAULT 0.0,
    kernel_name TEXT DEFAULT '', exchange TEXT DEFAULT '',
    timestamp TEXT NOT NULL
)"""

PNL_SNAPSHOTS_TABLE = """CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL, realized REAL, unrealized REAL,
    total REAL, position_count INTEGER, market_value REAL,
    trade_count INTEGER
)"""

KERNEL_STATE_TABLE = """CREATE TABLE IF NOT EXISTS kernel_state (
    name TEXT PRIMARY KEY, config TEXT DEFAULT '{}',
    last_status TEXT DEFAULT 'stopped', updated_at TEXT DEFAULT ''
)"""

ALL_TABLES = [ORDERS_TABLE, POSITIONS_TABLE, TRADES_TABLE, PNL_SNAPSHOTS_TABLE, KERNEL_STATE_TABLE]
