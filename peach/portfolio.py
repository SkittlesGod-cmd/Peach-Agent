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
class PaperTrade:
    id: int
    ticker: str
    direction: str  # "long" or "short"
    entry_price: float
    shares: float
    entry_date: str
    notes: str
    is_open: int  # 1 = open, 0 = closed
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None

    @property
    def pnl(self) -> float | None:
        if self.is_open or self.exit_price is None:
            return None
        mult = 1 if self.direction == "long" else -1
        return round(mult * (self.exit_price - self.entry_price) * self.shares, 2)


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
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL UNIQUE,
                    total_value   REAL NOT NULL,
                    total_cost    REAL NOT NULL,
                    pnl           REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    shares      REAL NOT NULL DEFAULT 1,
                    entry_date  TEXT NOT NULL,
                    notes       TEXT DEFAULT '',
                    is_open     INTEGER NOT NULL DEFAULT 1,
                    exit_price  REAL,
                    exit_date   TEXT
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

    # ── Paper trades ──────────────────────────────────────────────────────────

    def add_paper_trade(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        shares: float = 1.0,
        notes: str = "",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO paper_trades
                   (ticker, direction, entry_price, shares, entry_date, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ticker.upper(), direction, entry_price, shares,
                 datetime.now().date().isoformat(), notes),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def close_paper_trade(self, trade_id: int, exit_price: float) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE id = ?", (trade_id,)
            ).fetchone()
            if not row:
                return f"No paper trade #{trade_id} found."
            trade = PaperTrade(**dict(row))
            if not trade.is_open:
                return f"Trade #{trade_id} is already closed."
            conn.execute(
                "UPDATE paper_trades SET is_open=0, exit_price=?, exit_date=? WHERE id=?",
                (exit_price, datetime.now().date().isoformat(), trade_id),
            )
        mult = 1 if trade.direction == "long" else -1
        pnl = mult * (exit_price - trade.entry_price) * trade.shares
        return (
            f"Closed #{trade_id} {trade.ticker} {trade.direction.upper()} "
            f"@ ${exit_price:.2f}  |  P&L: ${pnl:+.2f}"
        )

    def get_paper_trades(self, open_only: bool = False) -> list[PaperTrade]:
        query = "SELECT * FROM paper_trades"
        if open_only:
            query += " WHERE is_open = 1"
        query += " ORDER BY id DESC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
            return [PaperTrade(**dict(r)) for r in rows]

    # ── Portfolio snapshots ───────────────────────────────────────────────────

    def record_snapshot(self) -> str | None:
        """Fetch live prices and save today's portfolio value. Returns summary or None if empty."""
        import yfinance as yf
        positions = self.get_all_positions()
        if not positions:
            return None
        total_value = 0.0
        total_cost = 0.0
        for pos in positions:
            try:
                info = yf.Ticker(pos.ticker).info
                current = info.get("currentPrice") or info.get("regularMarketPrice") or pos.cost_basis
                total_value += float(current) * pos.shares
            except Exception:
                total_value += pos.cost_basis * pos.shares
            total_cost += pos.cost_basis * pos.shares
        pnl = total_value - total_cost
        today = datetime.now().date().isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO portfolio_snapshots (snapshot_date, total_value, total_cost, pnl)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(snapshot_date) DO UPDATE SET
                       total_value = excluded.total_value,
                       total_cost  = excluded.total_cost,
                       pnl         = excluded.pnl""",
                (today, round(total_value, 2), round(total_cost, 2), round(pnl, 2)),
            )
        return f"Snapshot {today}: value=${total_value:,.0f}  cost=${total_cost:,.0f}  P&L=${pnl:+,.0f}"

    def get_snapshots(self, days: int = 90) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT snapshot_date, total_value, total_cost, pnl FROM portfolio_snapshots "
                "ORDER BY snapshot_date DESC LIMIT ?",
                (days,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ── Drawdown check ────────────────────────────────────────────────────────

    def check_drawdowns(self, threshold: float = 0.05) -> list[tuple[str, float, float, float]]:
        """Return (ticker, cost_basis, current_price, drawdown_pct) for positions breaching threshold."""
        import yfinance as yf
        results = []
        for pos in self.get_all_positions():
            try:
                info = yf.Ticker(pos.ticker).info
                current = info.get("currentPrice") or info.get("regularMarketPrice")
                if current and pos.cost_basis > 0:
                    drawdown = (pos.cost_basis - float(current)) / pos.cost_basis
                    if drawdown >= threshold:
                        results.append((pos.ticker, pos.cost_basis, float(current), drawdown))
            except Exception:
                pass
        return results
