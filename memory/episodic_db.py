"""Persistencia episódica SQLite."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from config.settings import DATA_DIR, DB_PATH


class EpisodicMemory:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    motor_usado TEXT
                )"""
            )

    def _connect(self):
        return sqlite3.connect(DB_PATH)

    def save(self, role: str, content: str, motor: str | None = None) -> None:
        if not content:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(timestamp, role, content, motor_usado) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), role, content, motor),
            )

    def recent(self, limit: int = 12) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE role IN ('user', 'assistant') ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def recent_records(self, limit: int = 30) -> list[tuple[str, str, str | None]]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT timestamp, content, motor_usado FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
