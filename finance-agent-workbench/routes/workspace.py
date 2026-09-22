"""Workspace run/stop/events API — Phase 8 with context persistence.

Replaces Phase 5.2 mock runner with the full 7-stage General Agent pipeline:
  LLMClient → ContextManager → AgentCore.execute() in a daemon thread.
  Events flow: AgentCore emitter → in-memory queue → SSE polling endpoint.
  
Phase 8: Context auto-syncs to conversations+messages tables after each run.
Page refresh restores full conversation history from DB.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, request

from agent.agent_config import AgentConfig
from agent.context_manager import ContextManager
from agent.core import AgentCore
from agent.llm_client import LLMClient
from routes._utils import error, success
from storage.agent_store import AgentStore
from storage.db import get_db
from storage.model_store import ModelStore
from storage.project_store import ProjectStore
from storage.run_store import RunStore
from storage.tool_call_store import ToolCallStore

logger = logging.getLogger(__name__)

workspace_bp = Blueprint("workspace_api", __name__, url_prefix="/api/workspace")

# Phase 17: 长任务默认上下文窗口（模型表未配置时使用）
DEFAULT_CONTEXT_WINDOW = 200000


def _resolve_context_window(model_store: ModelStore, model_name: str) -> int:
    """Resolve the model's real context window from the models table.

    Phase 17: 模型表有值用模型值；无值/0（如 gpt-5.5）默认 200000。
    阶段 7.9: 优先按唯一 model.id 匹配（项目 default_model 新格式），
    兼容旧格式按 name 匹配。
    """
    try:
        for m in model_store.list_models():
            if (m.get("id") and m.get("id") == model_name) or m.get("name") == model_name:
                cw = m.get("context_window") or 0
                try:
                    cw = int(cw)
                except (TypeError, ValueError):
                    cw = 0
                return cw if cw > 0 else DEFAULT_CONTEXT_WINDOW
    except Exception:
        pass
    return DEFAULT_CONTEXT_WINDOW

# ------------------------------------------------------------------
# In-memory run + agent registry
# ------------------------------------------------------------------
_runs: dict[str, dict] = {}
_agent_cores: dict[str, AgentCore] = {}
_session_cores: dict[str, AgentCore] = {}  # Agent mode: reuse AgentCore for context continuity
_bare_ctx: dict[str, Any] = {}  # Bare chat mode: store ContextManager directly
_lock = threading.Lock()

# ------------------------------------------------------------------
# Phase 16-AI-Identity: bare chat's own identity system prompt.
# Injected at send-time (never stored in ctx._messages), so the shared
# conversation memory only ever holds user/assistant turns — no cross-mode
# system-prompt pollution, and the LLM always knows its capability boundary.
# ------------------------------------------------------------------
BARE_CHAT_SYSTEM_PROMPT = (
    "你是「纯 AI 对话助手」，当前处于纯模型对话模式。\n\n"
    "## 能力边界\n"
    "你没有文件读取、Excel 处理、数据库查询、命令执行、工具调用等任何能力。\n\n"
    "## 行为准则\n"
    "1. 只进行纯文本问答、解释、计算、讨论、写作建议。\n"
    "2. 当用户请求涉及读取/处理文件、操作 Excel、查询数据、执行命令、"
    "运行代码等任务时，必须明确告知：\n"
    "   「我当前是纯对话模式，没有文件读取和工具调用功能，"
    "请在左上角 Agent 选择器切换到『通用智能体』后再试。」\n"
    "3. 绝不假装执行工具操作或编造文件内容。\n"
    "用 Markdown 格式化输出。"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(run_id: str, event: dict) -> int:
    """Push a structured AgentEvent dict into the run's in-memory event queue."""
    with _lock:
        entry = _runs.get(run_id)
        if not entry:
            return -1
        seq = entry["_last_seq"] + 1
        entry["_last_seq"] = seq
        enriched = {"seq": seq, "ts": _now_iso()}
        # Support both AgentEvent dicts (from agent_events module → have "payload" key)
        # and raw dicts (build payload from all non-meta keys)
        enriched["type"] = event.get("type", event.get("event", "unknown"))
        if "payload" in event:
            enriched["payload"] = event["payload"]
        else:
            enriched["payload"] = {k: v for k, v in event.items()
                                   if k not in ("type", "event", "ts")}
        entry["_events"].append(enriched)
        return seq


# ------------------------------------------------------------------
# Public accessors (used by interactions.py and other API modules)
# ------------------------------------------------------------------

def get_agent_core(run_id: str) -> AgentCore | None:
    """Return the active AgentCore for a given run, or None."""
    with _lock:
        return _agent_cores.get(run_id)


def get_run_store() -> RunStore | None:
    """Return a fresh RunStore from the current DB connection."""
    try:
        db = get_db()
        return RunStore(db)
    except Exception as e:
        logger.warning("RunStore unavailable: %s", e)
        return None


# ------------------------------------------------------------------
# Helper: build LLMClient from DB model configuration
# ------------------------------------------------------------------

def _build_llm_client(model_store: ModelStore, model_name: str) -> LLMClient:
    """Create LLMClient from database model configuration by model identity.

    Looks up the model in the models table, reads its api_url and api_key
    (inherited from provider), and constructs a client.

    阶段 7.9: model_name 可能是唯一 id（provider_xxx_modelname，新格式
    default_model）或模型名（旧格式）。优先按 id 精确匹配（一个模型名可
    由多个供应商提供，必须用 id 区分），再按 name 兼容。

    Fallback chain (fix for "WinError 10061 连接被拒绝"):
      1. Exact model id match, then exact name match in DB.
      2. No/invalid model_name → default model (is_default=1) in DB.
      3. No default → first chat-capable model with an api_url in DB.
      4. DB completely empty → LLMClient.from_env() (last resort).

    This prevents the old behaviour where an empty model_name fell back to
    LLMClient.from_env(), which defaults to http://127.0.0.1:11434/v1
    (Ollama) when no env vars are set → connection refused on this host.
    """
    all_models = model_store.list_models()

    # 1. Exact match by id (新格式) then by name (旧格式)
    if model_name:
        for m in all_models:
            if m.get("id") and m.get("id") == model_name:
                api_url = m.get("api_url") or ""
                api_key = m.get("api_key") or ""
                if api_url:
                    logger.info(
                        "Building LLMClient for model_id=%s (name=%s, provider api_url=%s)",
                        model_name, m.get("name"), api_url[:50],
                    )
                    return LLMClient(
                        api_url=api_url,
                        api_key=api_key,
                        model=m.get("name") or model_name,
                    )
                break
        for m in all_models:
            if m.get("name") == model_name:
                api_url = m.get("api_url") or ""
                api_key = m.get("api_key") or ""
                if api_url:
                    logger.info(
                        "Building LLMClient for model=%s from DB (provider api_url=%s)",
                        model_name, api_url[:50],
                    )
                    return LLMClient(
                        api_url=api_url,
                        api_key=api_key,
                        model=model_name,
                    )
                break
        logger.warning("Model %s not usable in DB; trying default model", model_name)
    else:
        logger.info("No model selected; falling back to default DB model")

    # 2. Default model (is_default=1)
    for m in all_models:
        if m.get("is_default") and (m.get("api_url") or ""):
            logger.info(
                "Using default model=%s (api_url=%s)",
                m.get("name"), (m.get("api_url") or "")[:50],
            )
            return LLMClient(
                api_url=m.get("api_url"),
                api_key=m.get("api_key") or "",
                model=m.get("name"),
            )

    # 3. First chat-capable model with api_url
    for m in all_models:
        if m.get("type") == "chat" and (m.get("api_url") or ""):
            logger.info(
                "Using first chat model=%s (api_url=%s)",
                m.get("name"), (m.get("api_url") or "")[:50],
            )
            return LLMClient(
                api_url=m.get("api_url"),
                api_key=m.get("api_key") or "",
                model=m.get("name"),
            )

    # 4. Last resort
    logger.warning("No usable models in DB; falling back to env vars")
    return LLMClient.from_env()


# ------------------------------------------------------------------
# POST /api/workspace/run
# ------------------------------------------------------------------
@workspace_bp.post("/run")
def start_run():
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return error("请输入任务描述")

    project_id = payload.get("project_id", "")
    agent_id = payload.get("agent", "general-agent")
    model_id = payload.get("model", "gpt-4o")
    context_files = payload.get("context_files") or []
    # 阶段 1：引擎选择（smol = smolagents 引擎，唯一实际使用；legacy = 自研 AgentCore 后备轨）
    # 智能体优化 3.0：前端恒传 "smol"，默认值改为 smol——legacy 仅作防御性后备不再默认启用
    engine = payload.get("engine", "smol") or "smol"
    # 阶段 G：工作模式（manual=人工审批 / auto=全自动），会话级临时切换，
    # 与模型切换同构（前端 state + updateProject 持久化 + 发送时 payload 传递）。
    # payload 未传时回退项目级配置（projects.work_mode，默认 manual）。
    work_mode = (payload.get("work_mode") or "").strip()
    if work_mode not in ("manual", "auto"):
        work_mode = ""
        try:
            _proj = ProjectStore(get_db()).get_by_id(project_id)
            if _proj and _proj.get("work_mode") in ("manual", "auto"):
                work_mode = _proj["work_mode"]
        except Exception:
            pass
        if not work_mode:
            work_mode = "manual"

    run_id = uuid.uuid4().hex
    stop_event = threading.Event()
    app = current_app._get_current_object()  # capture for thread context

    # ================================================================
    # Internal runner — wires up AgentCore and calls execute()
    # ================================================================
    def _runner() -> None:
        with app.app_context():
            _run_in_context(run_id, prompt, agent_id, model_id, project_id,
                            context_files, stop_event, engine=engine,
                            work_mode=work_mode)

    # Register run in in-memory registry
    with _lock:
        _runs[run_id] = {
            "run_id": run_id,
            "prompt": prompt,
            "agent": agent_id,
            "model": model_id,
            "project_id": project_id,
            "context_files": context_files,
            "engine": engine,
            "status": "starting",
            "stop_event": stop_event,
            "created_at": _now_iso(),
            "started_at": None,
            "stopped_at": None,
            "finished_at": None,
            "_events": [],
            "_last_seq": 0,
        }

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()

    with _lock:
        _runs[run_id]["thread"] = thread

    return success({
        "run_id": run_id,
        "status": "starting",
    }, status_code=201)


# ------------------------------------------------------------------
# Helper: core execution logic (must run inside app_context)
# ------------------------------------------------------------------

def _set_run_status(run_id: str, status: str) -> None:
    """Update the in-memory run status (thread-safe).

    Phase 17 fix: AgentCore._update_status 通过 status_callback 同步
    waiting_for_user 等状态到 _runs，使 /events 与 /status 可见。
    """
    with _lock:
        entry = _runs.get(run_id)
        if entry and status in ("running", "waiting_for_user",
                                "completed", "stopped", "failed"):
            entry["status"] = status

def _run_in_context(run_id: str, prompt: str, agent_id: str, model_id: str,
                    project_id: str, context_files: list,
                    stop_event: threading.Event,
                    engine: str = "smol",
                    work_mode: str = "manual") -> None:
    """Execute the AgentCore pipeline OR bare chat inside a Flask application context.

    Phase 7.4: When agent_id is empty or '', runs bare chat mode (pure LLM streaming).
    阶段 1: engine=smol 时使用 SmolAgentEngine（smolagents，默认），否则 legacy 自研 AgentCore（后备轨）。
    """
    try:
        db = get_db()

        # Create LLM client from DB model configuration
        model_store = ModelStore(db)
        llm_client = _build_llm_client(model_store, model_id)

        # ── Bare chat mode (no Agent) — share context with Agent mode ──
        if not agent_id or agent_id.strip() == "":
            # Phase 13: find existing agent context for this project+model,
            # so bare chat and agent mode share the same conversation history.
            shared_ctx = None
            for key, core in _session_cores.items():
                if key.startswith(f"{project_id}:") and key.endswith(f":{model_id}"):
                    shared_ctx = core.ctx
                    break
            _run_bare_chat(run_id, prompt, llm_client, project_id, context_files,
                           stop_event, model_store, model_id,
                           shared_ctx=shared_ctx)
            return

        # ── Agent mode ──
        run_store = RunStore(db)
        tool_call_store = ToolCallStore(db)

        # Emitter: bridge AgentEvent → in-memory queue + persistence
        def emitter(event: dict) -> None:
            seq = _emit(run_id, event)
            try:
                event_type = event.get("type", event.get("event", "unknown"))
                payload = event.get("payload", {})
                run_store.insert_event(run_id, seq, event_type, payload)
            except Exception:
                pass

        # 阶段 1：smolagents 引擎分流
        if engine == "smol":
            _run_smol_engine(run_id, prompt, agent_id, model_id, project_id,
                             context_files, stop_event, llm_client, emitter,
                             work_mode=work_mode)
            return

        # Load agent config
        agent_store = AgentStore(db)
        agent_row = agent_store.get_by_id(agent_id)
        if not agent_row:
            agent_row = agent_store.ensure_default_agent()
        agent_config = AgentConfig.from_db_row(agent_row)

        # Get project work_dir for tool sandboxing
        project_work_dir = ""
        try:
            pstore = ProjectStore(db)
            proj = pstore.get_by_id(project_id)
            if proj:
                project_work_dir = proj.get("work_dir", "")
        except Exception:
            pass
            # Create context manager — Phase 17: use the model's real context
            # window (fallback 200000) instead of the hardcoded 8192 budget.
            context_manager = ContextManager(
                agent_config=agent_config,
                context_window=_resolve_context_window(model_store, model_id),
            )

            # Phase 8: load persisted conversation history from DB into fresh context
            # (load directly into the new context_manager; legacy _load_context_from_db
            #  only operated on a pre-existing core, so it is not called here)
            try:
                from storage.conversation_store import ConversationStore
                store = ConversationStore(get_db())
                convs = store.list_conversations(project_id)
                if convs:
                    msgs = store.list_messages(convs[0]["id"])
                    for m in msgs:
                        if m["role"] in ("user", "assistant") and m.get("content", "").strip():
                            context_manager._messages.append({
                                "role": m["role"],
                                "content": m.get("content", ""),
                            })
                    logger.info("Loaded %d messages from DB into fresh AgentCore", len(msgs))
                    # Phase 12: sync flat messages into partitions
                    if hasattr(context_manager, '_sync_to_partitions'):
                        context_manager._sync_to_partitions()
            except Exception as e:
                logger.warning("Failed to load DB context into fresh core: %s", e)

            # Create AgentCore
            core = AgentCore(
                llm_client=llm_client,
                agent_config=agent_config,
                context_manager=context_manager,
                emitter=emitter,
                stop_event=stop_event,
                work_dir=project_work_dir,
                project_id=project_id,
                run_store=run_store,
                tool_call_store=tool_call_store,
                # Phase 17 fix: 同步核心状态（waiting_for_user 等）到内存 _runs
                status_callback=lambda s: _set_run_status(run_id, s),
            )
            _session_cores[session_key] = core
        else:
            # Reuse existing core — update run-level settings for the new run
            # P1 fix: rebind stores to the CURRENT request's db connection.
            # get_db() returns a per-app-context connection (stored in `g`),
            # which is closed by close_db() when that context tears down.
            # Without this, create_run()/insert_event() silently fail on the
            # closed connection left over from the first run, so later runs
            # never persist to the runs/run_events tables.
            core.run_store = run_store
            core.tool_call_store = tool_call_store
            core.stop_event = stop_event
            core.emitter = emitter  # Update emitter so events go to new run_id queue
            core.work_dir = project_work_dir
            core.tool_registry.work_dir = project_work_dir
            core.status_callback = lambda s: _set_run_status(run_id, s)

        # Register for external access (interactions.py)
        with _lock:
            _agent_cores[run_id] = core

        # Mark running
        with _lock:
            entry = _runs.get(run_id)
            if entry:
                entry["status"] = "running"
                entry["started_at"] = _now_iso()

        # Execute — blocks until done or stopped
        core.execute(
            run_id=run_id,
            prompt=prompt,
            agent_id=agent_id,
            model_id=model_id,
            context_files=context_files,
        )

    except Exception as e:
        logger.exception("AgentCore runner crashed: run=%s", run_id)
        _emit(run_id, {
            "type": "run_failed",
            "payload": {"reason": str(e)[:300]},
        })
        with _lock:
            entry = _runs.get(run_id)
            if entry:
                entry["status"] = "failed"
                entry["finished_at"] = _now_iso()
    finally:
        # Cleanup AgentCore reference
        with _lock:
            _agent_cores.pop(run_id, None)
            entry = _runs.get(run_id)
            if entry:
                # Phase 8 fix: also promote waiting_for_user (e.g. cancelled ask_user)
                if entry["status"] in ("running", "waiting_for_user"):
                    entry["status"] = "completed"
                entry["finished_at"] = _now_iso()

        # Phase 8: auto-sync context to DB after every run
        try:
            session_key = f"{project_id}:{agent_id}:{model_id}"
            core = _session_cores.get(session_key)
            if core and hasattr(core, 'ctx') and core.ctx._messages:
                _sync_context_to_db(project_id, agent_id, model_id, core.ctx._messages)
        except Exception:
            pass


# ------------------------------------------------------------------
# 阶段 1: smolagents 引擎（SmolAgentEngine）执行入口
# ------------------------------------------------------------------

def _run_smol_engine(run_id: str, prompt: str, agent_id: str, model_id: str,
                     project_id: str, context_files: list,
                     stop_event: threading.Event,
                     llm_client: LLMClient, emitter,
                     work_mode: str = "manual") -> None:
    """使用 SmolAgentEngine（smolagents）执行任务。

    engine=smol 时由 _run_in_context 分流到此。事件契约与 legacy
    完全一致（24 种 AgentEvent），旧前端无需改动。
    """
    from agent.smol_engine import SmolAgentEngine
    from agent.agent_events import run_failed

    # 阶段 7.7 补：RunStore 持久化 run 记录（此前 smol 模式 history 为空）
    run_store = None
    try:
        from storage.run_store import RunStore
        run_store = RunStore(get_db())
    except Exception as e:
        logger.warning("RunStore unavailable for smol engine: %s", e)

    # Get project work_dir for tool sandboxing
    project_work_dir = ""
    try:
        pstore = ProjectStore(get_db())
        proj = pstore.get_by_id(project_id)
        if proj:
            project_work_dir = proj.get("work_dir", "")
    except Exception:
        pass

    # 思考模式参数（复用现有判定：deepseek/glm 支持，qwen 不支持）
    flags = _thinking_flags(model_id)

    # 阶段 7.7 补：收集正文文本（最终答案）供上下文持久化
    assistant_text: list[str] = []

    def _collecting_emitter(event: dict) -> None:
        try:
            if event.get("type") == "message_delta":
                text = event.get("payload", {}).get("text") or event.get("payload", {}).get("delta") or ""
                if text:
                    assistant_text.append(text)
        except Exception:
            pass
        emitter(event)

    # P17：为 run 创建 conversation + user message 记录，前端历史才能
    # 显示完整 user prompt（此前为空 → 回退 run.title 80 字截断 → 用户看到的
    # 对话里"没有变量名"，实际 AI 收到的 prompt 是完整的）。
    conversation_id = ""
    user_message_id = ""
    try:
        from storage.conversation_store import ConversationStore
        cstore = ConversationStore(get_db())
        conv = cstore.create_conversation(
            project_id, title=prompt[:60])
        conversation_id = conv["id"]
        msg = cstore.create_message(
            conversation_id, "user", content=prompt,
            agent_id=agent_id, model_id=model_id)
        user_message_id = msg["id"]
    except Exception as e:
        logger.warning("Failed to link user message for run %s: %s", run_id, e)

    engine = SmolAgentEngine(
        llm_client=llm_client,
        emitter=_collecting_emitter,
        stop_event=stop_event,
        work_dir=project_work_dir,
        project_id=project_id,
        model_id=model_id,
        # 阶段 G：工作模式（manual=人工审批 / auto=全自动）
        work_mode=work_mode,
        # P17：单变量核对标准做法 6 次工具调用，12 步上限足够且
        # 强制模型聚焦收敛（此前 18/60 步都给了模型超额探索空间）
        max_steps=12,
        thinking=flags["thinking"],
        clear_thinking=flags["clear_thinking"],
        reasoning_effort=flags["effort"],
        run_store=run_store,
        conversation_id=conversation_id,   # P17：关联对话
        user_message_id=user_message_id,   # P17：关联用户消息
    )

    # 注册供 interactions.py 访问（兼容）
    with _lock:
        _agent_cores[run_id] = engine

    # 标记 running
    with _lock:
        entry = _runs.get(run_id)
        if entry:
            entry["status"] = "running"
            entry["started_at"] = _now_iso()

    try:
        engine.execute(
            run_id=run_id, prompt=prompt, agent_id=agent_id,
            model_id=model_id, context_files=context_files,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("SmolAgentEngine runner crashed: run=%s", run_id)
        emitter(run_failed(str(e)[:300]))
        with _lock:
            entry = _runs.get(run_id)
            if entry:
                entry["status"] = "failed"
                entry["finished_at"] = _now_iso()
    finally:
        with _lock:
            _agent_cores.pop(run_id, None)
            entry = _runs.get(run_id)
            if entry and entry["status"] in ("running", "waiting_for_user"):
                entry["status"] = "completed"
            if entry:
                entry["finished_at"] = _now_iso()

        # 阶段 7.7 补：同步 run 状态到 DB（此前 smol 模式 runs 表状态滞留 starting）
        try:
            if run_store and entry:
                db_status = entry["status"]
                if db_status in ("completed", "stopped", "failed", "waiting_for_user"):
                    run_store.update_run_status(run_id, db_status)
        except Exception:
            pass

        # 阶段 7.7 补：上下文持久化（user prompt + 最终答案 → conversations/messages）
        try:
            answer = "".join(assistant_text).strip()
            if answer:
                msgs = [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                ]
                _sync_context_to_db(project_id, agent_id, model_id, msgs)
        except Exception:
            pass


def _thinking_flags(model_name: str) -> dict:
    """思考模式参数判定（2026-08-19 统一为 medium，不做动态分级/强度选择）。

    - deepseek / glm（智谱）：官方支持 thinking.type + reasoning_effort，
      effort 统一 medium；
    - 其他模型（qwen 千问、本地部署等）：官方 OpenAI 兼容接口无
      reasoning_effort / thinking 字段（标准 OpenAI 参数集），返回 None →
      请求体完全不携带思考相关字段（传未知字段可能被严格网关 400 拒绝）。
    """
    name = (model_name or "").lower()
    if "deepseek" in name:
        return {"thinking": True, "clear_thinking": True, "effort": "medium"}
    if "glm" in name:
        return {"thinking": True, "clear_thinking": False, "effort": "medium"}
    # qwen / 本地部署：不支持思考参数 → 不传（避免未知字段被拒）
    return {"thinking": None, "clear_thinking": None, "effort": None}


# ------------------------------------------------------------------
# Phase 7.4: Bare chat mode — pure LLM streaming, no Agent/plan/tools
# ------------------------------------------------------------------

def _run_bare_chat(run_id: str, prompt: str, llm_client: LLMClient,
                   project_id: str, context_files: list,
                   stop_event: threading.Event,
                   model_store: ModelStore, model_id: str,
                   shared_ctx: Any = None) -> None:
    """Run a pure LLM chat session without any Agent orchestration.

    Retains deep thinking (reasoning_delta) streaming and context management,
    but removes plan generation, tool calling, task panel, and auto-audit.
    """
    from agent.agent_events import (
        message_delta as _msg_delta,
        reasoning_delta as _reas_delta,
        reasoning_closed as _reas_closed,
        run_completed as _run_done,
        run_created as _run_init,
        run_failed as _run_err,
    )

    # Mark running
    with _lock:
        entry = _runs.get(run_id)
        if entry:
            entry["status"] = "running"
            entry["started_at"] = _now_iso()

    try:
        # Emit run_created
        _emit(run_id, _run_init(
            run_id=run_id,
            agent="无（纯模型对话）",
            model=model_id,
            context_file_count=len(context_files or []),
            title=prompt[:80],
        ))

        # Phase 13: reuse agent-mode ContextManager if available (seamless switch)
        if shared_ctx is not None:
            ctx = shared_ctx
            ctx.add_user_message(prompt)
        else:
            session_key = f"{project_id}:::{model_id}"
            ctx = _bare_ctx.get(session_key)
            if ctx is None:
                ctx = ContextManager(
                    context_window=_resolve_context_window(model_store, model_id)
                )
                _bare_ctx[session_key] = ctx
            ctx.add_user_message(prompt)

        # Phase 16-AI-Identity: assemble at send-time — bare-chat identity
        # system prompt + shared user/assistant memory only. Never send the
        # agent-mode system prompt (which may live in shared ctx) to the LLM.
        messages: list[dict] = [
            {"role": "system", "content": BARE_CHAT_SYSTEM_PROMPT}
        ]
        for m in ctx.get_messages():
            if m.get("role") in ("user", "assistant"):
                messages.append(m)

        accumulated = ""
        has_reasoning = False

        for chunk in llm_client.chat_stream(
            messages, temperature=0.3, max_tokens=8192
        ):
            if stop_event.is_set():
                _emit(run_id, {"type": "run_stopped", "payload": {"reason": "user_cancelled"}})
                with _lock:
                    entry = _runs.get(run_id)
                    if entry:
                        entry["status"] = "stopped"
                        entry["finished_at"] = _now_iso()
                return

            reasoning_text = chunk.get("reasoning_delta") or ""
            if reasoning_text:
                has_reasoning = True
                _emit(run_id, _reas_delta(reasoning_text))

            text = chunk.get("delta") or ""
            if text:
                if has_reasoning:
                    _emit(run_id, _reas_closed())
                    has_reasoning = False
                _emit(run_id, _msg_delta(text))
                accumulated += text

        if has_reasoning:
            _emit(run_id, _reas_closed())

        # Save to context for next turn
        if accumulated.strip():
            ctx.add_assistant_message(content=accumulated)

        _emit(run_id, _run_done())

        # Phase 8: register bare chat context for continuity
        session_key = f"{project_id}:::{model_id}"
        _bare_ctx[session_key] = ctx
        _sync_context_to_db(project_id, "", model_id, ctx._messages)

        with _lock:
            entry = _runs.get(run_id)
            if entry:
                entry["status"] = "completed"
                entry["finished_at"] = _now_iso()

    except Exception as e:
        logger.exception("Bare chat crashed: run=%s", run_id)
        _emit(run_id, _run_err(str(e)[:300]))
        with _lock:
            entry = _runs.get(run_id)
            if entry:
                entry["status"] = "failed"
                entry["finished_at"] = _now_iso()


# ------------------------------------------------------------------
# POST /api/workspace/context/reset — 清空上下文缓存
# ------------------------------------------------------------------
@workspace_bp.post("/context/reset")
def reset_context():
    """Reset the session-level context cache AND clear in-memory messages.

    Phase 10: Also calls ctx.clear_messages() on any active session cores
    so the in-memory state matches the cleared DB. This prevents the model
    from \"remembering\" deleted context when a new run starts on a cached core.
    """
    payload = request.get_json(silent=True) or {}
    project_id = (payload.get("project_id") or "").strip()
    if not project_id:
        return error("缺少 project_id")

    cleared_cores = 0
    # Clear in-memory messages first, then pop the cache
    keys_to_remove = [k for k in _session_cores if k.startswith(f"{project_id}:")]
    for k in keys_to_remove:
        core = _session_cores.get(k)
        if core and core.ctx:
            core.ctx.clear_messages(keep_system=True)
            core._context_initialized = False
            # Phase 13: keep core alive, just clear messages (don't pop)
        cleared_cores += 1

    bare_keys_to_remove = [k for k in _bare_ctx if k.startswith(f"{project_id}:")]
    for k in bare_keys_to_remove:
        ctx = _bare_ctx.get(k)
        if ctx and hasattr(ctx, 'clear_messages'):
            ctx.clear_messages(keep_system=False)
            # Phase 13: keep bare ctx alive, just clear messages (don't pop)
        cleared_cores += 1

    # Phase 12: clear DB using standalone connection (avoids Flask g thread issues)
    try:
        import sqlite3 as _sqlite
        from config.settings import DB_PATH as _DB_PATH
        conn = _sqlite.connect(str(_DB_PATH))
        conn.row_factory = _sqlite.Row
        from storage.conversation_store import ConversationStore
        store = ConversationStore(conn)
        convs = store.list_conversations(project_id)
        for c in convs:
            store.delete_messages_by_conversation(c["id"])
            store.delete_conversation(c["id"])

        # P3 fix: "清空上下文" must also clear the persisted run history
        # (runs + run_events + plans/plan_steps + interactions), otherwise
        # /api/workspace/history still returns old runs after refresh even
        # though conversations/messages were cleared.
        run_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM runs WHERE project_id=?", (project_id,)
            ).fetchall()
        ]
        for rid in run_ids:
            conn.execute("DELETE FROM run_events WHERE run_id=?", (rid,))
            conn.execute("DELETE FROM interactions WHERE run_id=?", (rid,))
            plan_ids = [
                p[0] for p in conn.execute(
                    "SELECT id FROM plans WHERE run_id=?", (rid,)
                ).fetchall()
            ]
            for pid in plan_ids:
                conn.execute("DELETE FROM plan_steps WHERE plan_id=?", (pid,))
            conn.execute("DELETE FROM plans WHERE run_id=?", (rid,))
        conn.execute("DELETE FROM runs WHERE project_id=?", (project_id,))
        conn.execute("DELETE FROM tool_calls WHERE project_id=?", (project_id,))
        conn.commit()
        conn.close()
        logger.info("Context reset: cleared %d session(s) + %d DB conversations + %d runs for project %s",
                    cleared_cores, len(convs), len(run_ids), project_id)
    except Exception as e:
        logger.warning("Context reset DB cleanup failed: %s", e)

    return success({"status": "reset", "sessions_cleared": cleared_cores})



# ------------------------------------------------------------------
# GET /api/workspace/context/messages — 从数据库加载对话历史
# ------------------------------------------------------------------
@workspace_bp.get("/context/messages")
def load_messages():
    """Return conversation messages history for the given project."""
    project_id = request.args.get("project_id", "").strip()
    agent_id = request.args.get("agent", "")
    model_id = request.args.get("model", "")

    if not project_id:
        return error("缺少 project_id")

    messages = _load_context_from_db(project_id, agent_id, model_id)
    return success({"messages": messages})


# ------------------------------------------------------------------
# GET /api/workspace/history — 结构化运行历史（含工具卡 + 思考摘要）
# ------------------------------------------------------------------
@workspace_bp.get("/history")
def workspace_history():
    """Return per-run structured history for a project.

    Unlike /context/messages (which returns only the final user/assistant
    text), this endpoint aggregates each run's persisted run_events into a
    replayable structure: user prompt → reasoning (collapsed) → tool calls
    (start/completed pairs) → final assistant text → plan tree.

    This is what the frontend uses to restore the full conversation after
    a page refresh (Codex-style: tools + thinking + final answer), instead
    of just the final message.
    """
    project_id = request.args.get("project_id", "").strip()
    if not project_id:
        return error("缺少 project_id")

    try:
        db = get_db()
        from storage.run_store import RunStore
        store = RunStore(db)

        # All runs for this project, oldest first.
        runs = db.execute(
            """SELECT id, title, status, created_at, conversation_id,
                      user_message_id, agent_id, model_id
               FROM runs WHERE project_id=?
               ORDER BY created_at ASC""",
            (project_id,),
        ).fetchall()

        history = []
        for r in runs:
            run = dict(r)
            run_id = run["id"]

            # Fetch all events for this run (from DB).
            events = store.get_events_after(run_id, 0)

            # Group events into a structured run.
            reasoning_parts: list[str] = []
            tool_cards: list[dict] = []
            message_parts: list[str] = []
            open_tools: dict[str, dict] = {}
            plan = None
            user_prompt = ""
            assistant_text = ""

            for ev in events:
                etype = ev.get("event_type") or ev.get("type") or ""
                payload = ev.get("payload") or {}
                if etype == "reasoning_delta":
                    text = payload.get("text") or payload.get("delta") or ""
                    if text:
                        reasoning_parts.append(text)
                elif etype == "reasoning_closed":
                    continue
                elif etype == "message_delta":
                    text = payload.get("text") or payload.get("delta") or ""
                    if text:
                        message_parts.append(text)
                elif etype == "tool_started":
                    tool_id = payload.get("tool_id") or payload.get("id") or f"t{len(tool_cards)}"
                    open_tools[tool_id] = {
                        "tool_id": tool_id,
                        "name": payload.get("name") or "",
                        # Phase 16: semantic fields (fall back to raw name)
                        "title": payload.get("title") or payload.get("name") or "",
                        "icon": payload.get("icon") or "",
                        "step_id": payload.get("step_id") or "",
                        "input_summary": payload.get("input") or payload.get("input_summary") or "",
                        "status": "running",
                    }
                elif etype == "tool_completed":
                    tool_id = payload.get("tool_id") or payload.get("id") or ""
                    card = open_tools.pop(tool_id, None)
                    if card is None:
                        card = {
                            "tool_id": tool_id,
                            "name": payload.get("name") or "",
                            "title": payload.get("title") or payload.get("name") or "",
                            "icon": payload.get("icon") or "",
                            "step_id": payload.get("step_id") or "",
                            "input_summary": "",
                        }
                    card["status"] = payload.get("status") or ("success" if payload.get("success", True) else "failed")
                    card["duration_ms"] = payload.get("duration_ms") or 0
                    # Phase 16: prefer one-line human summary over raw output
                    card["output_summary"] = payload.get("output_summary") or \
                        payload.get("result_summary") or \
                        payload.get("output") or ""
                    tool_cards.append(card)
                elif etype == "plan_proposed":
                    plan = {
                        "steps": payload.get("steps") or [],
                        "summary": payload.get("summary") or "",
                        "version": payload.get("version") or 1,
                    }

            # Phase 16 P3-③: prefer REAL persisted step statuses from the
            # plan_steps table over the initial plan_proposed snapshot (which
            # is all "pending"). This makes the history plan card reflect the
            # true execution state after a refresh.
            if plan:
                try:
                    db_plan = store.get_latest_plan(run_id)
                    if db_plan and db_plan.get("steps"):
                        real_steps = []
                        for s in db_plan["steps"]:
                            real_steps.append({
                                "step_id": s.get("step_id"),
                                "title": s.get("title", ""),
                                "description": s.get("description", ""),
                                "status": s.get("status", "pending"),
                            })
                        if real_steps:
                            plan["steps"] = real_steps
                except Exception:
                    pass  # keep the plan_proposed snapshot as fallback

            # Leftover running tools (run interrupted) → keep as cards.
            for card in open_tools.values():
                card["status"] = "running"
                tool_cards.append(card)

            assistant_text = "".join(message_parts).strip()

            # User prompt: prefer the linked message row, fall back to run title.
            umid = run.get("user_message_id") or ""
            if umid:
                row = db.execute(
                    "SELECT content FROM messages WHERE id=?", (umid,)
                ).fetchone()
                if row and row["content"]:
                    user_prompt = row["content"]
            if not user_prompt:
                user_prompt = run.get("title") or ""

            history.append({
                "run_id": run_id,
                "title": run.get("title") or "",
                "status": run.get("status") or "",
                "created_at": run.get("created_at") or "",
                "conversation_id": run.get("conversation_id") or "",
                "user_prompt": user_prompt,
                "reasoning": "".join(reasoning_parts).strip(),
                "tool_cards": tool_cards,
                "assistant_text": assistant_text,
                "plan": plan,
            })

        return success({"runs": history})
    except Exception as e:
        logger.exception("workspace_history failed")
        return error(f"加载运行历史失败: {e}")


# ------------------------------------------------------------------
# Context persistence helpers
# ------------------------------------------------------------------

def _sync_context_to_db(project_id: str, agent_id: str, model_id: str,
                         messages: list[dict]) -> int:
    """Save all context messages to the conversations + messages tables.

    Each (project_id, agent_id, model_id) combo maps to one conversation.
    Returns number of messages saved.
    """
    try:
        db = get_db()
        from storage.conversation_store import ConversationStore
        store = ConversationStore(db)

        # Find or create conversation for this project+agent+model combo
        convs = store.list_conversations(project_id)
        conv_id = None
        for c in convs:
            # Reuse the most recent conversation (simplified: per project)
            conv_id = c["id"]
            break

        if not conv_id:
            conv = store.create_conversation(project_id, title=f"对话 {project_id[:8]}")
            conv_id = conv["id"]

        # Delete old messages to avoid duplicates, then re-insert
        store.delete_messages_by_conversation(conv_id)

        saved = 0
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                continue  # skip system prompt
            if not content or not content.strip():
                continue
            store.create_message(
                conversation_id=conv_id,
                role=role,
                content=content,
                agent_id=agent_id,
                model_id=model_id,
            )
            saved += 1

        logger.info("Synced %d messages to conversation %s", saved, conv_id)
        return saved
    except Exception as e:
        logger.warning("Context sync failed: %s", e)
        return 0


def _load_context_from_db(project_id: str, agent_id: str = "",
                           model_id: str = "") -> list[dict]:
    """Load conversation messages from database and inject into ContextManager."""
    try:
        db = get_db()
        from storage.conversation_store import ConversationStore
        store = ConversationStore(db)

        convs = store.list_conversations(project_id)
        if not convs:
            return []

        conv_id = convs[0]["id"]
        messages = store.list_messages(conv_id)

        # Inject into session core if it exists
        session_key = f"{project_id}:{agent_id}:{model_id}"
        core = _session_cores.get(session_key)
        if core and messages:
            core.ctx._messages = [
                {"role": m["role"], "content": m.get("content", "")}
                for m in messages
            ]
            if hasattr(core.ctx, '_sync_to_partitions'):
                core.ctx._sync_to_partitions()
        # Also try bare chat context
        bare_key = f"{project_id}:::{model_id}"
        bare = _bare_ctx.get(bare_key) if not agent_id else None
        if bare and messages:
            bare._messages = [
                {"role": m["role"], "content": m.get("content", "")}
                for m in messages
            ]
            if hasattr(bare, '_sync_to_partitions'):
                bare._sync_to_partitions()

        return [{"role": m["role"], "content": m.get("content", "")}
                for m in messages]
    except Exception as e:
        logger.warning("Context load failed: %s", e)
        return []


# ------------------------------------------------------------------
# POST /api/workspace/stop
# ------------------------------------------------------------------
@workspace_bp.post("/stop")
def stop_run():
    payload = request.get_json(silent=True) or {}
    run_id = (payload.get("run_id") or "").strip()
    if not run_id:
        return error("缺少 run_id")

    with _lock:
        entry = _runs.get(run_id)

    if not entry:
        return error("未找到该运行任务", 404)

    if entry["status"] in ("completed", "stopped", "failed"):
        return success({"run_id": run_id, "status": entry["status"]})

    stop_event = entry.get("stop_event")
    if stop_event:
        stop_event.set()

    # Update run_store
    try:
        run_store = get_run_store()
        if run_store:
            run_store.update_run_status(run_id, "stopped", progress_message="用户终止")
    except Exception:
        pass

    return success({"run_id": run_id, "status": "stopping"})


# ------------------------------------------------------------------
# GET /api/workspace/status?run_id=...
# ------------------------------------------------------------------
@workspace_bp.get("/status")
def run_status():
    run_id = request.args.get("run_id", "").strip()
    if not run_id:
        return error("缺少 run_id")

    with _lock:
        entry = _runs.get(run_id)

    if not entry:
        return error("未找到该运行任务", 404)

    return success({
        "run_id": entry["run_id"],
        "status": entry["status"],
        "created_at": entry.get("created_at"),
        "started_at": entry.get("started_at"),
        "stopped_at": entry.get("stopped_at"),
        "finished_at": entry.get("finished_at"),
    })


# ------------------------------------------------------------------
# GET /api/workspace/events?run_id=...&after_seq=0
# ------------------------------------------------------------------
@workspace_bp.get("/events")
def run_events():
    run_id = request.args.get("run_id", "").strip()
    if not run_id:
        return error("缺少 run_id")

    try:
        after_seq = int(request.args.get("after_seq", "0"))
    except (TypeError, ValueError):
        after_seq = 0

    with _lock:
        entry = _runs.get(run_id)

    if not entry:
        # Fallback: try run_store for historical events
        try:
            run_store = get_run_store()
            if run_store:
                events = run_store.get_events_after(run_id, after_seq)
                return success({
                    "run_id": run_id,
                    "status": "completed",
                    "last_seq": events[-1]["seq"] if events else after_seq,
                    "events": events,
                })
        except Exception:
            pass
        return error("未找到该运行任务", 404)

    with _lock:
        events = [e for e in entry["_events"] if e["seq"] > after_seq]
        last_seq = entry["_last_seq"]
        status = entry["status"]

    return success({
        "run_id": run_id,
        "status": status,
        "last_seq": last_seq,
        "events": events,
    })

# ------------------------------------------------------------------
# POST /api/workspace/context/reset — 清空上下文缓存
# ------------------------------------------------------------------
