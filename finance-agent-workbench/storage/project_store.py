"""projects table CRUD — Phase 2."""

from __future__ import annotations

import uuid
from sqlite3 import Connection

from storage._utils import iso_now, row_to_dict


class ProjectStore:
    def __init__(self, db: Connection) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    def create(
        self,
        name: str,
        work_dir: str,
        *,
        description: str | None = None,
        year: int | None = None,
        quarter: str | None = None,
        default_agent: str | None = None,
        default_model: str | None = None,
        work_mode: str = "manual",
    ) -> dict:
        now = iso_now()
        pid = uuid.uuid4().hex
        self.db.execute(
            """INSERT INTO projects
               (id, name, description, year, quarter, work_dir,
                default_agent, default_model, work_mode, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, description, year, quarter, work_dir,
             default_agent, default_model, work_mode, now, now),
        )
        self.db.commit()
        return self.get_by_id(pid)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_all(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_by_id(self, pid: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        return row_to_dict(row)

    def search_by_name(self, keyword: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM projects WHERE name LIKE ? ORDER BY updated_at DESC",
            (f"%{keyword}%",),
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    def update(
        self,
        pid: str,
        *,
        name: str | None = None,
        description: str | None = None,
        year: int | None = None,
        quarter: str | None = None,
        default_agent: str | None = None,
        default_model: str | None = None,
        work_mode: str | None = None,
    ) -> dict | None:
        existing = self.get_by_id(pid)
        if not existing:
            return None
        self.db.execute(
            """UPDATE projects
               SET name            = COALESCE(?, name),
                   description     = COALESCE(?, description),
                   year            = COALESCE(?, year),
                   quarter         = COALESCE(?, quarter),
                   default_agent   = COALESCE(?, default_agent),
                   default_model   = COALESCE(?, default_model),
                   work_mode       = COALESCE(?, work_mode),
                   updated_at      = ?
               WHERE id = ?""",
            (name, description, year, quarter, default_agent,
             default_model, work_mode, iso_now(), pid),
        )
        self.db.commit()
        return self.get_by_id(pid)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    def delete(self, pid: str) -> bool:
        conversation_rows = self.db.execute(
            "SELECT id FROM conversations WHERE project_id = ?", (pid,)
        ).fetchall()
        conversation_ids = [row["id"] for row in conversation_rows]
        for conversation_id in conversation_ids:
            self.db.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
        self.db.execute("DELETE FROM conversations WHERE project_id = ?", (pid,))
        self.db.execute("DELETE FROM token_usage WHERE project_id = ?", (pid,))
        self.db.execute("DELETE FROM tool_calls WHERE project_id = ?", (pid,))
        self.db.execute("DELETE FROM local_logs WHERE project_id = ?", (pid,))
        # Phase 14A: cascade-delete project data plane (data tables + metadata)
        data_file_rows = self.db.execute(
            "SELECT id FROM project_data_files WHERE project_id = ?", (pid,)
        ).fetchall()
        for row in data_file_rows:
            sheet_rows = self.db.execute(
                "SELECT table_name FROM project_data_sheets WHERE file_id = ?",
                (row["id"],),
            ).fetchall()
            for srow in sheet_rows:
                table_name = srow["table_name"]
                if table_name.startswith("data_"):
                    self.db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            self.db.execute(
                "DELETE FROM project_data_sheets WHERE file_id = ?", (row["id"],)
            )
            # Phase 14C: cascade-delete cell change log
            self.db.execute(
                "DELETE FROM project_data_changes WHERE file_id = ?", (row["id"],)
            )
        self.db.execute(
            "DELETE FROM project_data_files WHERE project_id = ?", (pid,)
        )
        cur = self.db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        self.db.commit()
        return cur.rowcount > 0
