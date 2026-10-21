import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import HistoryMessage

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sender TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key, id);

CREATE TABLE IF NOT EXISTS sessions (
    session_key TEXT PRIMARY KEY,
    persona_key TEXT,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_messages (
    msg_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryStore:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add_message(self, session_key: str, role: str, content: str, sender: str = "") -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(session_key, role, content, sender, created_at) VALUES(?,?,?,?,?)",
                (session_key, role, content, sender, now),
            )
            conn.execute(
                """
                INSERT INTO sessions(session_key, updated_at) VALUES(?,?)
                ON CONFLICT(session_key) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (session_key, now),
            )

    def recent_messages(self, session_key: str, limit: int) -> list[HistoryMessage]:
        if limit <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, sender FROM messages WHERE session_key=? ORDER BY id DESC LIMIT ?",
                (session_key, limit),
            ).fetchall()
        return [HistoryMessage(role=row["role"], content=row["content"], sender=row["sender"]) for row in reversed(rows)]

    def last_user_activity(self, session_key: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE session_key=? AND role='user' ORDER BY id DESC LIMIT 1",
                (session_key,),
            ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            return None

    def last_activity(self, session_key: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE session_key=? ORDER BY id DESC LIMIT 1",
                (session_key,),
            ).fetchone()
        if not row:
            return None
        try:
            return datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            return None

    def claim_message(self, msg_id: str) -> bool:
        if not msg_id:
            return True
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO processed_messages(msg_id, created_at) VALUES(?,?)",
                (msg_id, _now()),
            )
            return cursor.rowcount > 0

    def get_persona_key(self, session_key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT persona_key FROM sessions WHERE session_key=?",
                (session_key,),
            ).fetchone()
        return row["persona_key"] if row else None

    def set_persona_key(self, session_key: str, persona_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_key, persona_key, updated_at) VALUES(?,?,?)
                ON CONFLICT(session_key) DO UPDATE SET persona_key=excluded.persona_key, updated_at=excluded.updated_at
                """,
                (session_key, persona_key, _now()),
            )

    def get_summary(self, session_key: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT summary FROM sessions WHERE session_key=?",
                (session_key,),
            ).fetchone()
        return row["summary"] if row else ""

    def set_summary(self, session_key: str, summary: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_key, summary, updated_at) VALUES(?,?,?)
                ON CONFLICT(session_key) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at
                """,
                (session_key, summary, _now()),
            )

    def clear_session(self, session_key: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE session_key=?", (session_key,))
            conn.execute(
                "UPDATE sessions SET summary='', updated_at=? WHERE session_key=?",
                (_now(), session_key),
            )
