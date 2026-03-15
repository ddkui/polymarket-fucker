"""
logging_utils.py – Structured logging + SQLite trade database
=============================================================
Writes human-readable logs to a file and stores every trade in
a SQLite database so the dashboard can read them.
"""

import os
import json
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------

def setup_logger(level: str = "INFO", log_file: str = "logs/bot.log") -> logging.Logger:
    """Create and return the bot-wide logger."""
    # Make sure the log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("btc_bot")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler — always show INFO and above
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(console)

    # File handler — captures everything at the configured level
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  [%(module)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    return logger


# ---------------------------------------------------------------------------
# SQLite Trade Database
# ---------------------------------------------------------------------------

class TradeDB:
    """
    Thread-safe SQLite database for storing trades, equity snapshots,
    and bot status.  The dashboard reads from this same file.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_tables()

    # -- internal helpers ---------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._lock:
            conn = self._connect()
            c = conn.cursor()

            # Trades table — one row per trade
            c.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp   TEXT    NOT NULL,
                    market      TEXT    NOT NULL,
                    timeframe   INTEGER NOT NULL,
                    side        TEXT    NOT NULL,
                    direction   TEXT    NOT NULL,
                    entry_price REAL    NOT NULL,
                    size_usd    REAL    NOT NULL,
                    exit_price  REAL,
                    pnl         REAL,
                    result      TEXT,
                    strategy_tag TEXT,
                    regime      TEXT,
                    params_json TEXT,
                    status      TEXT    DEFAULT 'open'
                )
            """)

            # Equity snapshots — for the equity curve chart
            c.execute("""
                CREATE TABLE IF NOT EXISTS equity (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    equity    REAL    NOT NULL,
                    realized  REAL    NOT NULL,
                    unrealized REAL   NOT NULL
                )
            """)

            # Bot status — single row, upserted
            c.execute("""
                CREATE TABLE IF NOT EXISTS bot_status (
                    id     INTEGER PRIMARY KEY CHECK (id = 1),
                    status TEXT    NOT NULL DEFAULT 'stopped',
                    state_json TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.commit()
            conn.close()

    # -- Trades -------------------------------------------------------------

    def record_trade(self, trade: Dict[str, Any]) -> int:
        """Insert a new trade and return its row id."""
        with self._lock:
            conn = self._connect()
            c = conn.cursor()
            c.execute("""
                INSERT INTO trades
                    (timestamp, market, timeframe, side, direction,
                     entry_price, size_usd, strategy_tag, regime, params_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """, (
                trade.get("timestamp", datetime.now(timezone.utc).isoformat()),
                trade.get("market", ""),
                trade.get("timeframe", 5),
                trade.get("side", ""),
                trade.get("direction", ""),
                trade.get("entry_price", 0),
                trade.get("size_usd", 0),
                trade.get("strategy_tag", ""),
                trade.get("regime", ""),
                json.dumps(trade.get("params", {})),
            ))
            row_id = c.lastrowid
            conn.commit()
            conn.close()
            return row_id

    def close_trade(self, trade_id: int, exit_price: float, pnl: float, result: str):
        """Mark a trade as closed with its outcome."""
        with self._lock:
            conn = self._connect()
            conn.execute("""
                UPDATE trades
                SET exit_price = ?, pnl = ?, result = ?, status = 'closed'
                WHERE id = ?
            """, (exit_price, pnl, result, trade_id))
            conn.commit()
            conn.close()

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Return all currently open trades."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY timestamp DESC"
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_recent_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent trades (open and closed)."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    def get_closed_trades(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Return closed trades for statistics."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'closed' ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    # -- Equity snapshots ---------------------------------------------------

    def record_equity(self, equity: float, realized: float, unrealized: float):
        """Store an equity snapshot for charting."""
        with self._lock:
            conn = self._connect()
            conn.execute("""
                INSERT INTO equity (timestamp, equity, realized, unrealized)
                VALUES (?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(), equity, realized, unrealized))
            conn.commit()
            conn.close()

    def get_equity_history(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Return equity snapshots for the equity curve."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM equity ORDER BY timestamp ASC LIMIT ?", (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]

    # -- Bot status ---------------------------------------------------------

    def set_status(self, status: str, state: Optional[Dict[str, Any]] = None):
        """Update bot status and optional detailed state."""
        with self._lock:
            conn = self._connect()
            conn.execute("""
                INSERT INTO bot_status (id, status, state_json, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status = excluded.status,
                                              state_json = excluded.state_json,
                                              updated_at = excluded.updated_at
            """, (status, json.dumps(state) if state else None, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            conn.close()

    def get_status_detail(self) -> Dict[str, Any]:
        """Get current bot status and state."""
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT * FROM bot_status WHERE id = 1").fetchone()
            conn.close()
            if not row:
                return {"status": "stopped", "state": {}}
            d = dict(row)
            return {
                "status": d["status"],
                "state": json.loads(d["state_json"]) if d.get("state_json") else {},
                "updated_at": d["updated_at"]
            }

    def get_status(self) -> str:
        """Get current bot status string."""
        with self._lock:
            conn = self._connect()
            row = conn.execute("SELECT status FROM bot_status WHERE id = 1").fetchone()
            conn.close()
            return dict(row)["status"] if row else "stopped"

    # -- Aggregate stats for dashboard -------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Compute summary statistics for the dashboard."""
        with self._lock:
            conn = self._connect()
            c = conn.cursor()

            # Total realized PnL
            row = c.execute(
                "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE status = 'closed'"
            ).fetchone()
            total_pnl = dict(row)["total"]

            # Today's PnL
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            row = c.execute(
                "SELECT COALESCE(SUM(pnl), 0) as today_pnl, COUNT(*) as today_count "
                "FROM trades WHERE status = 'closed' AND timestamp LIKE ?",
                (today + "%",)
            ).fetchone()
            today_data = dict(row)
            today_pnl = today_data["today_pnl"]
            today_count = today_data["today_count"]

            # Win rate
            row = c.execute(
                "SELECT COUNT(*) as wins FROM trades WHERE status='closed' AND result='win'"
            ).fetchone()
            wins = dict(row)["wins"]
            row = c.execute(
                "SELECT COUNT(*) as total FROM trades WHERE status='closed'"
            ).fetchone()
            total_closed = dict(row)["total"]
            win_rate = (wins / total_closed * 100) if total_closed > 0 else 0

            # Average win / loss
            row = c.execute(
                "SELECT COALESCE(AVG(pnl), 0) as avg_win FROM trades "
                "WHERE status='closed' AND result='win'"
            ).fetchone()
            avg_win = dict(row)["avg_win"]
            row = c.execute(
                "SELECT COALESCE(AVG(pnl), 0) as avg_loss FROM trades "
                "WHERE status='closed' AND result='loss'"
            ).fetchone()
            avg_loss = dict(row)["avg_loss"]

            # Open positions count and unrealized PnL placeholder
            row = c.execute(
                "SELECT COUNT(*) as open_count FROM trades WHERE status='open'"
            ).fetchone()
            open_count = dict(row)["open_count"]

            conn.close()

            return {
                "total_pnl": round(float(total_pnl or 0.0), 2),
                "today_pnl": round(float(today_pnl or 0.0), 2),
                "today_trades": int(today_count or 0),
                "total_trades": int(total_closed or 0),
                "win_rate": round(float(win_rate or 0.0), 1),
                "avg_win": round(float(avg_win or 0.0), 2),
                "avg_loss": round(float(avg_loss or 0.0), 2),
                "open_positions": int(open_count or 0),
            }
