"""conversations / messages tables CRUD — Phase 2."""

from __future__ import annotations

import uuid
from sqlite3 import Connection

from storage._utils import iso_now, row_to_dict


class ConversationStore:
    def __init__(self, db: Connection) -> None:
        self.db = db

    # -- conversations -------------------------------------------------
    def create_conversation(self, project_id: str, title: str | None = None) -> dict:
        now = iso_now()
        cid = uuid.uuid4().hex
        self.db.execute(
            """INSERT INTO conversations (id, project_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (cid, project_id, title, now, now),
        )
        self.db.commit()
        return self.get_conversation(cid)

    def get_conversation(self, cid: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
        return row_to_dict(row)

    def list_conversations(self, project_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def delete_conversation(self, cid: str) -> bool:
        cur = self.db.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        self.db.commit()
        return cur.rowcount > 0

    # -- messages ------------------------------------------------------
    def create_message(
        self,
        conversation_id: str,
        role: str,
        *,
        content: str | None = None,
        agent_id: str | None = None,
        model_id: str | None = None,
        tokens_used: int | None = None,
    ) -> dict:
        mid = uuid.uuid4().hex
        now = iso_now()
        self.db.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, agent_id, model_id,
                tokens_used, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, conversation_id, role, content, agent_id, model_id,
             tokens_used, now),
        )
        self.db.commit()
        return self.get_message(mid)

    def get_message(self, mid: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM messages WHERE id = ?", (mid,)
        ).fetchone()
        return row_to_dict(row)

    def list_messages(self, conversation_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def delete_messages_by_conversation(self, conversation_id: str) -> int:
        cur = self.db.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        self.db.commit()
        return cur.rowcount
