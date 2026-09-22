"""Run Store — persistence for runs, run_events, plans, plan_steps, interactions.

Phase 7.1: Provides CRUD for all 5 runtime tables.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from storage._utils import iso_now, row_to_dict


class RunStore:
    """CRUD for the runs, run_events, plans, plan_steps, interactions tables."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(self, run_id: str, project_id: str = "",
                   conversation_id: str = "", user_message_id: str = "",
                   agent_id: str = "", model_id: str = "",
                   title: str = "") -> dict:
        now = iso_now()
        self.db.execute(
            """INSERT INTO runs (id, project_id, conversation_id, user_message_id,
               agent_id, model_id, title, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,'starting',?,?)""",
            (run_id, project_id, conversation_id, user_message_id,
             agent_id, model_id, title, now, now),
        )
        self.db.commit()
        return self.get_run(run_id) or {}

    def get_run(self, run_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return row_to_dict(row) if row else None

    def update_run_status(self, run_id: str, status: str,
                          progress: float | None = None,
                          progress_message: str | None = None,
                          error_message: str | None = None) -> None:
        sets = ["status=?", "updated_at=?"]
        params: list[Any] = [status, iso_now()]
        if progress is not None:
            sets.append("progress=?")
            params.append(progress)
        if progress_message is not None:
            sets.append("progress_message=?")
            params.append(progress_message)
        if error_message is not None:
            sets.append("error_message=?")
            params.append(error_message)
        if status in ("completed", "stopped", "failed"):
            sets.append("completed_at=?")
            params.append(iso_now())
        params.append(run_id)
        self.db.execute(
            f"UPDATE runs SET {', '.join(sets)} WHERE id=?",
            params,
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Run Events
    # ------------------------------------------------------------------

    def insert_event(self, run_id: str, seq: int, event_type: str,
                     payload: dict | None = None) -> int:
        payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
        self.db.execute(
            """INSERT INTO run_events (run_id, seq, event_type, payload_json, created_at)
               VALUES (?,?,?,?,?)""",
            (run_id, seq, event_type, payload_json, iso_now()),
        )
        self.db.commit()
        return seq

    def get_events_after(self, run_id: str, after_seq: int) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM run_events
               WHERE run_id=? AND seq > ?
               ORDER BY seq ASC""",
            (run_id, after_seq),
        ).fetchall()
        result = []
        for r in rows:
            d = row_to_dict(r)
            if d.get("payload_json"):
                try:
                    d["payload"] = json.loads(d["payload_json"])
                except (json.JSONDecodeError, TypeError):
                    d["payload"] = {}
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def create_interaction(self, interaction_id: str, run_id: str,
                           interaction_type: str, prompt: str,
                           options: list[str] | None = None,
                           tool_call_id: str = "") -> dict:
        options_json = json.dumps(options, ensure_ascii=False) if options else None
        now = iso_now()
        self.db.execute(
            """INSERT INTO interactions
               (id, run_id, tool_call_id, interaction_type, prompt, options_json, status, created_at)
               VALUES (?,?,?,?,?,?,'pending',?)""",
            (interaction_id, run_id, tool_call_id, interaction_type, prompt, options_json, now),
        )
        self.db.commit()
        return self.get_interaction(interaction_id) or {}

    def get_interaction(self, interaction_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM interactions WHERE id=?", (interaction_id,)
        ).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        if d.get("options_json"):
            try:
                d["options"] = json.loads(d["options_json"])
            except (json.JSONDecodeError, TypeError):
                d["options"] = []
        return d

    def respond_interaction(self, interaction_id: str, response: str) -> None:
        self.db.execute(
            "UPDATE interactions SET user_response=?, status='responded', responded_at=? WHERE id=?",
            (response, iso_now(), interaction_id),
        )
        self.db.commit()

    def cancel_interaction(self, interaction_id: str) -> None:
        self.db.execute(
            "UPDATE interactions SET status='cancelled', responded_at=? WHERE id=?",
            (iso_now(), interaction_id),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Plans (Phase 16 P3: plan persistence — single source of truth)
    # ------------------------------------------------------------------

    def create_plan(self, run_id: str, version: int = 1, summary: str = "",
                    total_estimated_steps: int = 0,
                    total_weight: float = 100) -> str:
        """Insert a plan row, return its plan_id."""
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        self.db.execute(
            """INSERT INTO plans
               (id, run_id, version, total_estimated_steps, total_weight,
                summary, is_confirmed, created_at)
               VALUES (?,?,?,?,?,?,0,?)""",
            (plan_id, run_id, version, total_estimated_steps, total_weight,
             summary, iso_now()),
        )
        self.db.commit()
        return plan_id

    def create_plan_step(self, plan_id: str, step: dict, sort_order: int = 0) -> None:
        """Insert one plan step row."""
        self.db.execute(
            """INSERT INTO plan_steps
               (plan_id, step_id, parent_step_id, title, description, weight,
                status, tool_name, output_summary, started_at, completed_at, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (plan_id,
             step.get("step_id", f"step-{sort_order+1}"),
             step.get("parent_step_id"),
             step.get("title", f"步骤 {sort_order+1}"),
             step.get("description", ""),
             float(step.get("weight", 25) or 25),
             step.get("status", "pending"),
             (step.get("tools_used") or [None])[0] if step.get("tools_used") else None,
             step.get("expected_output", ""),
             None, None, sort_order),
        )
        self.db.commit()

    def update_plan_step_status(self, plan_id: str, step_id: str, status: str,
                                started_at: str | None = None,
                                completed_at: str | None = None) -> None:
        sets = ["status=?"]
        params: list[Any] = [status]
        if started_at is not None:
            sets.append("started_at=?")
            params.append(started_at)
        if completed_at is not None:
            sets.append("completed_at=?")
            params.append(completed_at)
        params.extend([plan_id, step_id])
        self.db.execute(
            f"UPDATE plan_steps SET {', '.join(sets)} WHERE plan_id=? AND step_id=?",
            params,
        )
        self.db.commit()

    def get_latest_plan(self, run_id: str) -> dict | None:
        """Return the most recent plan (highest version) for a run."""
        row = self.db.execute(
            """SELECT * FROM plans WHERE run_id=?
               ORDER BY version DESC, created_at DESC LIMIT 1""",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        plan = row_to_dict(row)
        rows = self.db.execute(
            "SELECT * FROM plan_steps WHERE plan_id=? ORDER BY sort_order ASC",
            (plan["id"],),
        ).fetchall()
        plan["steps"] = [row_to_dict(r) for r in rows]
        return plan
