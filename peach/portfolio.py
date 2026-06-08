"""SQLite-backed portfolio and alert ledger."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Position:
    ticker: str
    shares: float
    cost_basis: float
    entry_date: str
    thesis: str = ""

    @property
    def total_cost(self) -> float:
        return self.shares * self.cost_basis


@dataclass
class PriceAlert:
    id: int
    ticker: str
    direction: str  # "above" or "below"
    price: float
    note: str
    created_at: str
    fired_at: Optional[str] = None


class PortfolioLedger:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS positions (
                    ticker      TEXT PRIMARY KEY,
                    shares      REAL NOT NULL,
                    cost_basis  REAL NOT NULL,
                    entry_date  TEXT NOT NULL,
                    thesis      TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    price       REAL NOT NULL,
                    note        TEXT DEFAULT '',
                    created_at  TEXT NOT NULL,
                    fired_at    TEXT
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    side        TEXT NOT NULL,
                    shares      REAL NOT NULL,
                    price       REAL NOT NULL,
                    traded_at   TEXT NOT NULL,
                    note        TEXT DEFAULT ''
                );
            """)

    def add_position(self, ticker: str, shares: float, cost_basis: float, thesis: str = "") -> None:
        entry_date = datetime.now().date().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO positions (ticker, shares, cost_basis, entry_date, thesis)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    cost_basis = (cost_basis * shares + excluded.cost_basis * excluded.shares)
                                 / (shares + excluded.shares),
                    shares     = shares + excluded.shares,
                    thesis     = CASE WHEN excluded.thesis != '' THEN excluded.thesis ELSE thesis END
                """,
                (ticker.upper(), shares, cost_basis, entry_date, thesis),
            )

    def remove_position(self, ticker: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM positions WHERE ticker = ?", (ticker.upper(),))
            return cur.rowcount > 0

    def get_position(self, ticker: str) -> Optional[Position]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM positions WHERE ticker = ?", (ticker.upper(),)
            ).fetchone()
            return Position(**dict(row)) if row else None

    def get_all_positions(self) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM positions ORDER BY ticker").fetchall()
            return [Position(**dict(r)) for r in rows]

    def add_alert(self, ticker: str, direction: str, price: float, note: str = "") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO alerts (ticker, direction, price, note, created_at) VALUES (?, ?, ?, ?, ?)",
                (ticker.upper(), direction, price, note, datetime.now().isoformat()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_active_alerts(self) -> list[PriceAlert]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE fired_at IS NULL ORDER BY ticker"
            ).fetchall()
            return [PriceAlert(**dict(r)) for r in rows]

    def mark_alert_fired(self, alert_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE alerts SET fired_at = ? WHERE id = ?",
                (datetime.now().isoformat(), alert_id),
            )

    def log_trade(self, ticker: str, side: str, shares: float, price: float, note: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trades (ticker, side, shares, price, traded_at, note) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker.upper(), side, shares, price, datetime.now().isoformat(), note),
            )
