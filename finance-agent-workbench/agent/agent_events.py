"""AgentEvent protocol — 13 structured event types for SSE streaming.

Phase 7.1: Defines the contract between AgentCore (backend) and the frontend
SSE event consumer (workspace.js / interactions.js / taskpanel.js).

Each event is a dict with at least: { "seq": int, "type": str, "ts": str }
and optionally a "payload" dict with event-specific data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

EventType = Literal[
    "run_created",           # Run created with initial metadata
    "plan_proposed",         # Plan generated, waiting for user confirmation
    "plan_updated",          # Plan status changed (approved/cancelled/step update)
    "user_input_required",   # Agent needs user input (confirm/text/select)
    "reasoning_summary",     # Agent loop reasoning summary (collapsed by default)
    "reasoning_delta",       # Streaming LLM reasoning content (deep thinking tokens)
    "reasoning_closed",      # Streaming reasoning ended, collapse drawer (Phase 7.3)
    "step_started",          # Plan step execution started with container info (Phase 7.3)
    "step_completed",        # Plan step execution finished (Phase 7.3)
    "tool_started",          # Tool execution started
    "tool_completed",        # Tool execution finished
    "run_progress",          # Throttled progress heartbeat (Phase 16: step/tool/elapsed)
    "message_delta",         # Streaming text chunk from AI
    "run_completed",         # All steps + audit finished
    "run_stopped",           # User cancelled
    "run_failed",            # Execution error
    # Phase 18 H0/H1: 阶段状态机事件（harness 显式阶段推进）
    "stage_changed",         # Harness 阶段切换（classify/evidence/execute/verify）
    "intent_declared",       # 模型声明当前意图（要做什么）
    "evidence_plan",         # 声明要采集哪些证据
    "evidence_collected",    # 证据已采集（附关键事实）
    # Phase 18 H2: 写后强制验证事件
    "verification_started",  # 验证阶段开始（test/stat/readback/sample）
    "verification_completed",# 验证完成（passed/summary）
]

ALL_EVENT_TYPES: tuple[EventType, ...] = (
    "run_created",
    "plan_proposed",
    "plan_updated",
    "user_input_required",
    "reasoning_summary",
    "reasoning_delta",
    "reasoning_closed",
    "step_started",
    "step_completed",
    "tool_started",
    "tool_completed",
    "run_progress",
    "message_delta",
    "run_completed",
    "run_stopped",
    "run_failed",
    "stage_changed",
    "intent_declared",
    "evidence_plan",
    "evidence_collected",
    "verification_started",
    "verification_completed",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Event factory functions
# ------------------------------------------------------------------

def create_event(event_type: EventType, payload: dict[str, Any] | None = None) -> dict:
    """Create a raw event dict (without seq — seq is assigned by emitter)."""
    event: dict[str, Any] = {
        "type": event_type,
        "ts": now_iso(),
    }
    if payload is not None:
        event["payload"] = payload
    return event


def run_created(run_id: str, agent: str | None, model: str | None,
                context_file_count: int = 0, title: str = "",
                task_mode: str = "") -> dict:
    """task_mode: "simple"（简单问答，无规划）/ "complex"（复杂任务，含规划）。
    智能体优化 3.0（阶段 A2，铁律 000）：前端据此显示任务模式徽标。"""
    return create_event("run_created", {
        "run_id": run_id,
        "agent": agent or "",
        "model": model or "",
        "context_file_count": context_file_count,
        "title": title,
        "task_mode": task_mode,
    })


def plan_proposed(steps: list[dict], version: int = 1,
                  summary: str = "", total_weight: float = 100) -> dict:
    """Emit when a plan is ready for user confirmation.

    steps: list of {step_id, title, description, weight, status, tools_used, expected_output}
    """
    return create_event("plan_proposed", {
        "steps": steps,
        "version": version,
        "status": "proposed",
        "summary": summary,
        "total_weight": total_weight,
    })


def plan_updated(steps: list[dict] | None = None, status: str = "",
                 version: int | None = None) -> dict:
    """Emit when plan status changes: approved, cancelled, or step status changes."""
    payload: dict[str, Any] = {"status": status}
    if steps is not None:
        payload["steps"] = steps
    if version is not None:
        payload["version"] = version
    return create_event("plan_updated", payload)


def user_input_required(question: str, input_type: str = "text",
                        options: list[str] | None = None,
                        tool_call_id: str = "",
                        interaction_id: str = "",
                        progress: dict | None = None,
                        allow_skip: bool = False,
                        multi_select: bool = False,
                        answers_so_far: str = "") -> dict:
    """Emit when agent needs user clarification or approval.

    input_type: 'text' | 'select' | 'confirm'
    progress: {'current': int, 'total': int} for progressive clarification
    allow_skip: whether user can skip this question
    multi_select: when input_type='select', allow choosing multiple options
    answers_so_far: summary of already-answered questions
    """
    payload = {
        "question": question,
        "input_type": input_type,
        "options": options or [],
        "tool_call_id": tool_call_id,
        "interaction_id": interaction_id,
        "allow_skip": allow_skip,
        "multi_select": multi_select,
        "answers_so_far": answers_so_far,
    }
    if progress:
        payload["progress"] = progress
    return create_event("user_input_required", payload)


def reasoning_summary(summary: str, detail: str = "") -> dict:
    return create_event("reasoning_summary", {
        "summary": summary,
        "detail": detail,
    })


def reasoning_delta(text: str) -> dict:
    """Streaming LLM reasoning content — real model thinking tokens."""
    return create_event("reasoning_delta", {"text": text})


def reasoning_closed() -> dict:
    """Signal that streaming reasoning has ended; frontend collapses the drawer."""
    return create_event("reasoning_closed", {})


def step_started(step_id: str, title: str, index: int = 0, total: int = 0) -> dict:
    """Emit when a plan step begins execution (Phase 7.3).

    Frontend creates a <div class="run-step"> container for this step's content.
    """
    return create_event("step_started", {
        "step_id": step_id,
        "title": title,
        "index": index,
        "total": total,
    })


def step_completed(step_id: str, success: bool = True, summary: str = "") -> dict:
    """Emit when a plan step finishes execution (Phase 7.3).

    Frontend closes the <div class="run-step"> container and marks it done/failed.
    """
    return create_event("step_completed", {
        "step_id": step_id,
        "success": success,
        "summary": summary,
    })


def tool_started(tool_id: str, name: str, input_summary: str = "",
                 title: str = "", icon: str = "", category: str = "",
                 step_id: str = "") -> dict:
    """Phase 16: title/icon/category/step_id are semantic fields for the
    human-readable tool card; frontend falls back to name when absent."""
    return create_event("tool_started", {
        "tool_id": tool_id,
        "name": name,
        "input": input_summary,
        "title": title or name,
        "icon": icon,
        "category": category,
        "step_id": step_id,
    })


def tool_completed(tool_id: str, name: str, output: str = "",
                   status: str = "success", duration_ms: float = 0,
                   output_summary: str = "", step_id: str = "") -> dict:
    """Phase 16: output_summary = one-line human summary of the result."""
    return create_event("tool_completed", {
        "tool_id": tool_id,
        "name": name,
        "output": output,
        "status": status,
        "duration_ms": duration_ms,
        "output_summary": output_summary,
        "step_id": step_id,
    })


def message_delta(text: str) -> dict:
    return create_event("message_delta", {"text": text})


def run_progress(current_step: int = 0, total_steps: int = 0,
                 tool_count: int = 0, elapsed_ms: int = 0,
                 label: str = "", round_idx: int = 0) -> dict:
    """Phase 16: throttled progress heartbeat for status bars / task panel.

    Phase 17 P4: round_idx = 已执行轮次（长任务观测，无上限时用户可见进度）。
    """
    return create_event("run_progress", {
        "current_step": current_step,
        "total_steps": total_steps,
        "tool_count": tool_count,
        "elapsed_ms": elapsed_ms,
        "label": label,
        "round_idx": round_idx,
    })


# ------------------------------------------------------------------
# Phase 18 H0/H1: 阶段状态机事件（harness 显式阶段推进）
# ------------------------------------------------------------------

def stage_changed(stage: str, label: str, prev_stage: str = "",
                  detail: str = "") -> dict:
    """Emit when the harness stage transitions.

    stage: classify | clarify | evidence_plan | evidence_collect |
           execution_plan | execute | verify | finalize
    """
    return create_event("stage_changed", {
        "stage": stage,
        "label": label,
        "prev_stage": prev_stage,
        "detail": detail,
    })


def intent_declared(kind: str, summary: str, targets: list[str] | None = None,
                    reason: str = "") -> dict:
    """Model declares what it intends to do (before tool calls).

    kind: explain | read_file | read_data | reconcile | update | report | inspect
    """
    return create_event("intent_declared", {
        "kind": kind,
        "summary": summary,
        "targets": targets or [],
        "reason": reason,
    })


def evidence_plan(targets: list[str], reason: str = "",
                  tools: list[str] | None = None) -> dict:
    """Harness declares which evidence will be collected and why."""
    return create_event("evidence_plan", {
        "targets": targets,
        "reason": reason,
        "tools": tools or [],
    })


def evidence_collected(summary: str, key_facts: list[str] | None = None,
                       sufficient: bool = False) -> dict:
    """Evidence collection finished with a summary + key facts."""
    return create_event("evidence_collected", {
        "summary": summary,
        "key_facts": key_facts or [],
        "sufficient": sufficient,
    })


def verification_started(kind: str, summary: str = "") -> dict:
    """Phase 18 H2: verification phase started.

    kind: test | compile | stat | readback | sample
    """
    return create_event("verification_started", {
        "kind": kind,
        "summary": summary,
    })


def verification_completed(passed: bool, summary: str = "",
                           details: str = "") -> dict:
    """Phase 18 H2: verification finished with a pass/fail result."""
    return create_event("verification_completed", {
        "passed": passed,
        "summary": summary,
        "details": details,
    })


def run_completed() -> dict:
    return create_event("run_completed")


def run_stopped(reason: str = "user_cancelled") -> dict:
    return create_event("run_stopped", {"reason": reason})


def run_failed(error: str) -> dict:
    return create_event("run_failed", {"error": error})
