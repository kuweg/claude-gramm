"""SQLite state DB: session bookkeeping + pending-entity queue (DESIGN §4.3).

The DB drives idempotency. A session is reprocessed only when its jsonl mtime or
size changed, its status isn't ``woven``, or ``--force`` is passed; combined with
in-place note rewrites, that makes re-runs no-ops.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id  TEXT PRIMARY KEY,
  jsonl_path  TEXT NOT NULL,
  project     TEXT,
  mtime       INTEGER NOT NULL,
  size        INTEGER NOT NULL,
  status      TEXT NOT NULL CHECK (status IN
              ('pending','compacted','distilled','woven','error')),
  note_path   TEXT,
  schema_version INTEGER,
  error       TEXT,
  processed_at TEXT
);
CREATE TABLE IF NOT EXISTS pending_entities (
  name          TEXT PRIMARY KEY,
  display       TEXT,
  count         INTEGER DEFAULT 1,
  first_session TEXT,
  status        TEXT DEFAULT 'pending'
                CHECK (status IN ('pending','approved','aliased','rejected'))
);
"""

_SESSION_COLUMNS = (
    "session_id", "jsonl_path", "project", "mtime", "size", "status",
    "note_path", "schema_version", "error", "processed_at",
)


class State:
    """Thin wrapper over the SQLite state DB."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.db_path.exists()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        if not existed:
            # Never world-readable: notes/DB may reference secrets (§8).
            os.chmod(self.db_path, 0o600)

    # -- sessions ---------------------------------------------------------

    def upsert_session(
        self,
        session_id: str,
        jsonl_path: str,
        *,
        project: str | None,
        mtime: int,
        size: int,
        status: str = "pending",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO sessions (session_id, jsonl_path, project, mtime, size, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                jsonl_path=excluded.jsonl_path,
                project=excluded.project,
                mtime=excluded.mtime,
                size=excluded.size
            """,
            (session_id, jsonl_path, project, mtime, size, status),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: str, **fields: Any) -> None:
        if not fields:
            return
        bad = set(fields) - set(_SESSION_COLUMNS)
        if bad:
            raise ValueError(f"unknown session columns: {sorted(bad)}")
        assignments = ", ".join(f"{col} = ?" for col in fields)
        params = list(fields.values()) + [session_id]
        self.conn.execute(
            f"UPDATE sessions SET {assignments} WHERE session_id = ?", params
        )
        self.conn.commit()

    def needs_processing(
        self, session_id: str, *, mtime: int, size: int, force: bool = False
    ) -> bool:
        if force:
            return True
        row = self.get_session(session_id)
        if row is None:
            return True
        if row["mtime"] != mtime or row["size"] != size:
            return True
        return row["status"] != "woven"

    # -- pending entities -------------------------------------------------

    def add_pending_entity(
        self, name: str, *, display: str, session_id: str
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO pending_entities (name, display, count, first_session)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(name) DO UPDATE SET count = count + 1
            """,
            (name, display, session_id),
        )
        self.conn.commit()

    def get_pending_entities(self, status: str = "pending") -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM pending_entities WHERE status = ? ORDER BY count DESC, name ASC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_pending_status(self, name: str, status: str) -> None:
        self.conn.execute(
            "UPDATE pending_entities SET status = ? WHERE name = ?", (status, name)
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "State":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
