"""token_usage table CRUD — Phase 2."""

from __future__ import annotations

from sqlite3 import Connection

from storage._utils import iso_now, row_to_dict


class TokenStore:
    def __init__(self, db: Connection) -> None:
        self.db = db

    def today_counts(self) -> dict:
        row = self.db.execute(
            """SELECT COUNT(*) AS conversations,
                      SUM(total_tokens) AS tokens
               FROM token_usage
               WHERE date(created_at) = date('now')"""
        ).fetchone()
        return row_to_dict(row)

    # ── Phase 16 P1-D: real token usage persistence ──

    def record(self, project_id: str = "", agent_id: str = "", model_id: str = "",
               input_tokens: int = 0, output_tokens: int = 0,
               reasoning_tokens: int = 0, run_id: str = "",
               conversation_id: str = "", message_id: str = "") -> int:
        """Record one LLM call's usage into the token_usage table.

        Phase 17 fix: reasoning_tokens (DeepSeek/GLM thinking tokens) is
        now persisted instead of being dropped.  `run_id` remains unused
        by the schema (kept for future run-level attribution).

        Returns new row id, or 0 if no tokens were reported (skip).
        """
        total = (input_tokens or 0) + (output_tokens or 0)
        if total <= 0:
            return 0
        cur = self.db.execute(
            """INSERT INTO token_usage
               (project_id, conversation_id, message_id, agent_id, model_id,
                input_tokens, output_tokens, reasoning_tokens, total_tokens, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (project_id, conversation_id or "", message_id or "",
             agent_id or "", model_id or "",
             int(input_tokens or 0), int(output_tokens or 0),
             int(reasoning_tokens or 0), total,
             iso_now()),
        )
        self.db.commit()
        return cur.lastrowid

    def project_summary(self, project_id: str, limit_hours: int = 24) -> dict:
        """Aggregate token usage for a project over the last N hours."""
        row = self.db.execute(
            f"""SELECT COUNT(*) AS calls,
                      COALESCE(SUM(input_tokens), 0) AS input_tokens,
                      COALESCE(SUM(output_tokens), 0) AS output_tokens,
                      COALESCE(SUM(total_tokens), 0) AS total_tokens
               FROM token_usage
               WHERE project_id=?
                 AND created_at >= datetime('now', '-{int(limit_hours)} hours')""",
            (project_id,),
        ).fetchone()
        return row_to_dict(row)

    # ── Phase 9: dashboard stats (trend + agent distribution) ──

    def daily_trend(self, days: int = 14) -> list[dict]:
        """Token consumption per day for the last N days (oldest first)."""
        rows = self.db.execute(
            """SELECT date(created_at) AS day,
                      COUNT(*) AS calls,
                      COALESCE(SUM(total_tokens), 0) AS tokens
               FROM token_usage
               WHERE created_at >= datetime('now', ?)
               GROUP BY date(created_at)
               ORDER BY day ASC""",
            (f"-{int(days)} days",),
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def agent_distribution(self, days: int = 30) -> list[dict]:
        """Token usage share per agent (bare chat excluded), for a donut."""
        rows = self.db.execute(
            """SELECT COALESCE(NULLIF(agent_id, ''), '未标注') AS agent,
                      COALESCE(SUM(total_tokens), 0) AS tokens,
                      COUNT(*) AS calls
               FROM token_usage
               WHERE created_at >= datetime('now', ?)
               GROUP BY COALESCE(NULLIF(agent_id, ''), '未标注')
               ORDER BY tokens DESC""",
            (f"-{int(days)} days",),
        ).fetchall()
        return [row_to_dict(r) for r in rows]
