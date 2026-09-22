"""Context API — context file management and token statistics.

Provides the frontend context panel with token usage statistics.
"""

from __future__ import annotations

from flask import Blueprint, request

from routes._utils import success

context_bp = Blueprint("context_api", __name__, url_prefix="/api/context")

DEFAULT_CONTEXT_WINDOW = 200000


def _resolve_window_for_project(project_id: str) -> int:
    """Resolve the project default model's real context window.

    阶段 7: 无活跃会话时（bare chat / DB 持久化 / 全空）用模型真实窗口
    估算占用，缺省回退 DEFAULT_CONTEXT_WINDOW。
    """
    try:
        from storage.db import get_db
        from storage.project_store import ProjectStore
        from storage.model_store import ModelStore
        proj = ProjectStore(get_db()).get_by_id(project_id)
        model_name = (proj or {}).get("default_model") or ""
        if model_name:
            from routes.workspace import _resolve_context_window
            return _resolve_context_window(ModelStore(get_db()), model_name)
    except Exception:
        pass
    return DEFAULT_CONTEXT_WINDOW


# ------------------------------------------------------------------
# GET /api/context/stats
# ------------------------------------------------------------------
@context_bp.get("/stats")
def context_stats():
    """Return current context occupancy statistics from the active session.

    Semantics (Phase 16 P2 fix):
      - usage_pct reflects the CURRENT context window occupancy, sourced
        from ContextManager.get_stats() (live partition estimation), NOT
        the historical token_usage table. token_usage is a *cumulative
        spend* counter (every LLM call re-sends the whole history), so it
        would over-count and show 100% after a single run.
      - token_usage's real cumulative spend is returned as an extra field
        (consumed_tokens) for display, but never drives the occupancy bar.
    """
    project_id = request.args.get("project_id", "")

    def _with_consumed(stats: dict) -> dict:
        """Attach real cumulative spend as an informational field."""
        try:
            from storage.db import get_db
            from storage.token_store import TokenStore
            summary = TokenStore(get_db()).project_summary(project_id, limit_hours=24)
            stats["consumed_tokens"] = int(summary.get("total_tokens") or 0)
            stats["consumed_calls"] = int(summary.get("calls") or 0)
        except Exception:
            stats["consumed_tokens"] = 0
            stats["consumed_calls"] = 0
        return stats

    # Primary path: live session core (Agent mode) — real current occupancy
    from routes.workspace import _session_cores, _bare_ctx

    for key, core in list(_session_cores.items()):
        if key.startswith(f"{project_id}:"):
            stats = core.ctx.get_stats() if hasattr(core, 'ctx') else {
                "current_tokens": 0, "context_window": 8192,
                "response_reserve": 1228, "effective_budget": 6964,
                "usage_pct": 0, "message_count": 0,
                "context_files_count": 0, "tool_result_count": 0,
                "partitions": {},
            }
            return success(_with_consumed(stats))  # Phase 12: full dict

    # Bare chat mode
    for key, ctx in list(_bare_ctx.items()):
        if key.startswith(f"{project_id}:"):
            if hasattr(ctx, '_messages'):
                total_chars = sum(len(m.get("content", "")) for m in ctx._messages)
                estimated_tokens = total_chars // 2
                context_window = _resolve_window_for_project(project_id)
                reserve = int(context_window * 0.15)
                usage_pct = min(100, round(estimated_tokens / context_window * 100, 1))
                return success(_with_consumed({
                    "current_tokens": estimated_tokens,
                    "context_window": context_window,
                    "response_reserve": reserve,
                    "effective_budget": context_window - reserve,
                    "usage_pct": usage_pct,
                    "message_count": len(ctx._messages),
                    "context_files_count": 0,
                    "partitions": {},
                }))

    # No active session — check DB for persisted context
    try:
        from storage.db import get_db
        from storage.conversation_store import ConversationStore
        from storage.project_store import ProjectStore
        from storage.model_store import ModelStore
        store = ConversationStore(get_db())
        convs = store.list_conversations(project_id)
        if convs:
            msgs = store.list_messages(convs[0]["id"])
            total_chars = sum(len(m.get("content", "")) for m in msgs)
            estimated_tokens = total_chars // 2
            context_window = _resolve_window_for_project(project_id)
            reserve = int(context_window * 0.15)
            usage_pct = min(100, round(estimated_tokens / context_window * 100, 1))
            return success(_with_consumed({
                "current_tokens": estimated_tokens,
                "context_window": context_window,
                "response_reserve": reserve,
                "effective_budget": context_window - reserve,
                "usage_pct": usage_pct,
                "message_count": len(msgs),
                "context_files_count": 0,
                "partitions": {},
            }))
    except Exception:
        pass

    # Nothing at all
    context_window = _resolve_window_for_project(project_id)
    reserve = int(context_window * 0.15)
    return success(_with_consumed({
        "current_tokens": 0,
        "context_window": context_window,
        "response_reserve": reserve,
        "effective_budget": context_window - reserve,
        "usage_pct": 0,
        "message_count": 0,
        "context_files_count": 0,
        "partitions": {},
    }))
