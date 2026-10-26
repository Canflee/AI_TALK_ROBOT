import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS document_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    msg_id TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    instruction TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    output_docx TEXT NOT NULL DEFAULT '',
    output_pdf TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_document_jobs_session
    ON document_jobs(session_key, id);
"""

UPDATABLE = {
    "text", "instruction", "status", "output_docx", "output_pdf", "error", "source_path", "source_name",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DocumentStore:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(document_jobs)").fetchall()
            }
            if "text" not in columns:
                conn.execute(
                    "ALTER TABLE document_jobs ADD COLUMN text TEXT NOT NULL DEFAULT ''"
                )

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

    def create(
        self,
        session_key: str,
        msg_id: str,
        source_path: str,
        source_name: str,
        source_type: str,
    ) -> int:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO document_jobs(
                    session_key, msg_id, source_path, source_name, source_type,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(msg_id) DO UPDATE SET
                    source_path=excluded.source_path,
                    source_name=excluded.source_name,
                    source_type=excluded.source_type,
                    updated_at=excluded.updated_at
                """,
                (session_key, msg_id, source_path, source_name, source_type, now, now),
            )
            row = conn.execute(
                "SELECT id FROM document_jobs WHERE msg_id=?", (msg_id,)
            ).fetchone()
        return int(row["id"])

    def get(self, job_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM document_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def latest(self, session_key: str, max_age_minutes: int = 30) -> dict | None:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat(
            timespec="seconds"
        )
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM document_jobs
                WHERE session_key=? AND created_at>=?
                ORDER BY id DESC LIMIT 1
                """,
                (session_key, cutoff),
            ).fetchone()
        return dict(row) if row else None

    def update(self, job_id: int, **fields) -> None:
        values = {key: value for key, value in fields.items() if key in UPDATABLE}
        if not values:
            return
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE document_jobs SET {assignments} WHERE id=?",
                (*values.values(), job_id),
            )
