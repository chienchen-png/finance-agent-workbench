"""Interactions API — user response handling for ask_user prompts.

Phase 7.3: Handles the backend side of the Human-in-the-loop interaction loop.
When the user answers an ask_user prompt (confirm/text/select), this API
routes the response back to the waiting AgentCore thread.
"""

from __future__ import annotations

from flask import Blueprint, request

from routes._utils import error, success
from routes.workspace import get_agent_core, get_run_store

interactions_bp = Blueprint("interactions_api", __name__, url_prefix="/api/interactions")


# ------------------------------------------------------------------
# POST /api/interactions/<interaction_id>/respond
# ------------------------------------------------------------------
@interactions_bp.post("/<interaction_id>/respond")
def respond(interaction_id: str):
    """Send user response to a waiting ask_user prompt."""
    payload = request.get_json(silent=True) or {}
    response_text = (payload.get("response") or "").strip()
    cancelled = payload.get("cancelled", False)

    if not response_text and not cancelled:
        return error("缺少响应内容")

    # Persist response (best-effort, may fail across threads)
    store = get_run_store()
    if store:
        try:
            interaction = store.get_interaction(interaction_id)
            if interaction:
                if cancelled:
                    store.cancel_interaction(interaction_id)
                else:
                    store.respond_interaction(interaction_id, response_text)
        except Exception:
            pass  # DB failure should not block user response

    # Route response to the waiting AgentCore (always try, regardless of DB status)
    core = None
    run_id = ""
    if store:
        try:
            interaction = store.get_interaction(interaction_id)
            if interaction:
                run_id = interaction.get("run_id") or ""
        except Exception:
            pass

    # Phase 8 fix: resolve core by run_id first (correct routing for concurrent runs)
    if run_id:
        core = get_agent_core(run_id)

    # Fallback: try all registered cores (only if run_id unavailable)
    if not core:
        from routes.workspace import _agent_cores
        for rid, c in list(_agent_cores.items()):
            core = c
            break

    if core and hasattr(core, 'provide_user_response'):
        core.provide_user_response(response_text, cancelled=cancelled)
        return success({"status": "ok", "interaction_id": interaction_id})

    return error("未找到对应的交互或运行")
