"""Tool Call Store — persistence for tool_calls table.

Phase 7.3: Provides CRUD for tool call records, approval status, and result tracking.
Reuses the existing tool_calls table from schema.sql.
"""

from __future__ import annotations

import sqlite3

from storage._utils import iso_now, row_to_dict


class ToolCallStore:
    """CRUD for the tool_calls table."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def create_tool_call(self, tool_call_id: str, project_id: str = "",
                         conversation_id: str = "", message_id: str = "",
                         tool_name: str = "", params_summary: str = "",
                         approval_status: str = "auto",
                         status: str = "pending") -> dict:
        now = iso_now()
        self.db.execute(
            """INSERT INTO tool_calls
               (id, project_id, conversation_id, message_id, tool_name,
                parameters_summary, approval_status, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (tool_call_id, project_id, conversation_id, message_id,
             tool_name, params_summary, approval_status, status, now),
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT * FROM tool_calls WHERE id=?", (tool_call_id,)
        ).fetchone()
        return row_to_dict(row) if row else {}

    def update_tool_call(self, tool_call_id: str, status: str,
                         result_summary: str = "",
                         approval_status: str | None = None) -> None:
        sets = ["status=?"]
        params: list = [status]
        if result_summary:
            sets.append("result_summary=?")
            params.append(result_summary)
        if approval_status:
            sets.append("approval_status=?")
            params.append(approval_status)
        params.append(tool_call_id)
        self.db.execute(
            f"UPDATE tool_calls SET {', '.join(sets)} WHERE id=?",
            params,
        )
        self.db.commit()
