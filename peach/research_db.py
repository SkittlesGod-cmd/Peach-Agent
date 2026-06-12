"""SQLite database layer for the research opportunity tracker."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Professor:
    name: str
    university: str
    research_focus: str
    department: str = ""
    email: str | None = None
    lab_url: str | None = None
    recent_paper_title: str | None = None
    recent_paper_summary: str | None = None
    status: str = "found"
    found_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str | None = None
    id: int | None = None


class ResearchDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._init()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS professors (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    university      TEXT NOT NULL,
                    department      TEXT,
                    email           TEXT,
                    lab_url         TEXT,
                    research_focus  TEXT,
                    recent_paper_title    TEXT,
                    recent_paper_summary  TEXT,
                    status          TEXT DEFAULT 'found',
                    found_at        TEXT,
                    notes           TEXT,
                    UNIQUE(name, university)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outreach (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    professor_id    INTEGER REFERENCES professors(id),
                    type            TEXT,
                    subject         TEXT,
                    body            TEXT,
                    sent_at         TEXT,
                    replied         INTEGER DEFAULT 0,
                    reply_at        TEXT
                )
            """)

    # ── Write ──────────────────────────────────────────────────────────────────

    def add_professor(self, prof: Professor) -> int | None:
        """Insert professor; returns new id or None if already exists."""
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    """INSERT INTO professors
                       (name, university, department, email, lab_url, research_focus,
                        recent_paper_title, recent_paper_summary, status, found_at, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (prof.name, prof.university, prof.department, prof.email, prof.lab_url,
                     prof.research_focus, prof.recent_paper_title, prof.recent_paper_summary,
                     prof.status, prof.found_at, prof.notes),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None

    def update_status(self, professor_id: int, status: str, notes: str | None = None) -> None:
        with self._conn() as conn:
            if notes:
                conn.execute(
                    "UPDATE professors SET status=?, notes=? WHERE id=?",
                    (status, notes, professor_id),
                )
            else:
                conn.execute("UPDATE professors SET status=? WHERE id=?", (status, professor_id))

    def log_outreach(self, professor_id: int, kind: str, subject: str, body: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO outreach (professor_id, type, subject, body, sent_at)
                   VALUES (?,?,?,?,?)""",
                (professor_id, kind, subject, body, datetime.now().isoformat()),
            )
            return cur.lastrowid

    def mark_replied(self, professor_id: int) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE professors SET status='replied' WHERE id=?", (professor_id,))
            conn.execute(
                "UPDATE outreach SET replied=1, reply_at=? WHERE professor_id=? AND replied=0",
                (datetime.now().isoformat(), professor_id),
            )

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_all(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM professors WHERE status=? ORDER BY found_at DESC", (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM professors ORDER BY found_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_followup_due(self, days: int = 14) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT p.*, o.sent_at AS last_sent
                   FROM professors p
                   JOIN outreach o ON o.professor_id = p.id
                   WHERE p.status IN ('emailed', 'followed_up')
                     AND o.replied = 0
                     AND julianday('now') - julianday(o.sent_at) >= ?
                   GROUP BY p.id
                   ORDER BY o.sent_at ASC""",
                (days,),
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        profs = self.get_all()
        counts: dict[str, int] = {}
        for p in profs:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        return counts

    def snapshot(self) -> dict[str, Any]:
        profs = self.get_all()
        return {
            "professors": profs,
            "stats": self.stats(),
            "total": len(profs),
            "updated_at": datetime.now().isoformat(),
        }
