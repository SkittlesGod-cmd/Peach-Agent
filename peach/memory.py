"""Persistent key-value memory store for Peach agent context."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class AgentMemory:
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def set(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value      = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), datetime.now().isoformat()),
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM memory WHERE key = ?", (key,)).fetchone()
            return json.loads(row["value"]) if row else default

    def get_all(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM memory").fetchall()
            return {r["key"]: json.loads(r["value"]) for r in rows}

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memory WHERE key = ?", (key,))

    def context_summary(self) -> str:
        """Compact string of stored facts for injection into prompts."""
        data = {k: v for k, v in self.get_all().items() if not k.startswith("_")}
        if not data:
            return ""
        lines = ["Remembered context:"]
        for k, v in data.items():
            lines.append(f"  {k}: {v}")
        return "\n".join(lines)
