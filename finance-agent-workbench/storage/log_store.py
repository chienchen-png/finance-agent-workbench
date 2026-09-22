"""local_logs table CRUD — Phase 2."""

from __future__ import annotations

from sqlite3 import Connection

from storage._utils import iso_now, row_to_dict


class LogStore:
    def __init__(self, db: Connection) -> None:
        self.db = db

    def write(
        self,
        event_type: str,
        *,
        project_id: str | None = None,
        event_summary: str | None = None,
        status: str | None = None,
        detail: str | None = None,
    ) -> dict:
        now = iso_now()
        cur = self.db.execute(
            """INSERT INTO local_logs
               (project_id, event_type, event_summary, status, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (project_id, event_type, event_summary, status, detail, now),
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT * FROM local_logs WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return row_to_dict(row)

    def get_by_project(
        self, project_id: str, limit: int = 100
    ) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM local_logs
               WHERE project_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (project_id, limit),
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def recent_errors(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM local_logs
               WHERE status = 'error'
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]
