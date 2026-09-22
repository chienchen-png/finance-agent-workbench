"""AgentCore — 7-stage General Agent main loop.

⚠️ DEPRECATED（智能体优化 3.0）：本引擎为 legacy 后备轨，已不再默认启用。
前端恒走 smolagents 引擎（agent/smol_engine.py）；本文件保留仅作防御性
后备（routes/workspace.py 的 engine != "smol" 分支），新功能一律加在 smol 引擎。

Phase 7.2: Implements the full guided-execution workflow:
  1. 需求引导与澄清 (Clarification)
  2. 需求完备性判断 (Completeness Check)
  3. 计划生成 (Plan Generation)
  4. 用户确认 (User Confirmation Gate)
  5. 实时执行 (ReAct Execution Loop)
  6. 自动审计 (Auto Audit)
  7. 最终报告 (Final Report)

Communicates with the frontend via an event emitter callback that pushes
structured AgentEvent dicts through SSE /api/workspace/events.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Callable

from agent.agent_config import AgentConfig
from agent.agent_events import (
    evidence_collected,
    evidence_plan,
    intent_declared,
    message_delta,
    plan_proposed,
    plan_updated,
    reasoning_closed,
    reasoning_delta,
    reasoning_summary,
    run_completed,
    run_created,
    run_failed,
    run_progress,
    run_stopped,
    stage_changed,
    step_completed,
    step_started,
    tool_completed,
    tool_started,
    user_input_required,
    verification_completed,
    verification_started,
)
from agent.context_manager import ContextManager
from agent.llm_client import LLMClient
from agent.tool_registry import ToolRegistry, ALL_TOOL_SCHEMAS
from agent.tool_titles import humanize_tool_call, summarize_output

logger = logging.getLogger(__name__)

# Event emitter type: (event_dict) -> None
Emitter = Callable[[dict], None]

# Run status values
STATUS_RUNNING = "running"
STATUS_WAITING = "waiting_for_user"
STATUS_COMPLETED = "completed"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"

# Phase 18 H0: 写类工具集合 —— 用于「写后强制 verify」阶段判定（H2 正式启用）
WRITE_TOOLS = frozenset({
    "write_file", "create_directory", "move_path", "copy_path",
    "delete_path", "write_excel", "update_rows", "insert_rows",
    "delete_rows", "export_project_data", "run_command",
})

# Phase 18 H1: 证据采集阶段推荐工具（软引导，非硬限制）
EVIDENCE_TOOLS = frozenset({
    "read_file", "list_directory", "search_files", "read_excel",
    "get_sheet_info", "analyze_excel", "query_table", "table_stats",
    "get_python_version", "get_python_executable", "get_installed_packages",
})


def _normalize_delta_text(text: str) -> str:
    """Normalize streaming text that may contain broken whitespace.

    Some LLMs (observed with deepseek-v4-flash in long tool-calling
    sessions) intermittently emit content as "word-by-word separated by
    3+ newlines" (e.g. "存在\\n\\n\\n多个\\n\\n\\nPython"), which breaks
    markdown rendering into one paragraph per word.

    Normal markdown uses:
      - 1 newline for line breaks inside blocks (tables, lists)
      - 2 newlines for paragraph separation

    So we:
      1. Collapse runs of 3+ newlines down to a single newline.
      2. If the result still looks "word-per-line" (many consecutive short
         lines without sentence-ending punctuation), merge those runs into
         single lines so markdown renders continuous prose instead of one
         paragraph per word.
    """
    if not text:
        return text
    text = re.sub(r"\n{3,}", "\n", text)

    lines = text.split("\n")
    if len(lines) < 4:
        return "\n".join(lines)

    def _is_short_line(line: str) -> bool:
        t = line.strip()
        if not t:
            return False
        # Legitimate markdown structure lines are never merged:
        #  - bullet/quote/code/table: - * | # > `
        #  - ordered list: digits followed by . or ) (e.g. "1. step")
        # A BARE number (e.g. "4") is a word fragment and IS merged.
        if t[0] in ("-", "*", "|", "#", ">", "`"):
            return False
        if re.match(r"\d+[.)]", t):
            return False
        if len(t) > 10:
            return False
        # A complete short sentence (>4 chars ending in punctuation) is a
        # real line end.  Bare punctuation fragments (。，, etc.) must NOT
        # break a word-per-line run — otherwise a lone "。" or a 2-3 char
        # fragment becomes an orphaned line / <br> in the markdown output.
        if re.search(r"[。！？；：,.!?;:：)]$", t) and len(t) > 4:
            return False
        return True

    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        # Detect a run of consecutive short lines (>=3) → merge them
        if _is_short_line(lines[i]):
            j = i
            while j < n and _is_short_line(lines[j]):
                j += 1
            run_len = j - i
            if run_len >= 3:
                merged = "".join(l.strip() for l in lines[i:j])
                out.append(merged)
                i = j
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ------------------------------------------------------------------
# Phase 18 H1: 意图推断辅助（harness 层，非 LLM 判定）
# ------------------------------------------------------------------

def _infer_intent_kind(task_type: str, prompt: str) -> str:
    """Infer the intent category from task type + prompt keywords.

    Used to emit intent_declared BEFORE any tool call, so the user sees
    "AI 先声明要做什么" rather than a flat tool-call stream.
    """
    p = prompt
    if any(k in p for k in ("对比", "比对", "核对", "对账", "对不上", "差异")):
        return "reconcile"
    if any(k in p for k in ("统计", "汇总", "聚合", "平均", "合计", "分组")):
        return "read_data"
    if any(k in p for k in ("修改", "更新", "写入", "删除", "改名", "移动")):
        return "update"
    if any(k in p for k in ("方案", "报告", "文档", "计划书", "预算")):
        return "report"
    if any(k in p for k in ("排查", "定位", "为什么", "问题", "报错")):
        return "inspect"
    if task_type == "qa":
        return "explain"
    return "read_file"


def _infer_evidence_targets(prompt: str) -> list[str]:
    """Extract likely evidence targets (file/sheet/table names) from prompt.

    Best-effort keyword capture; empty list is fine (harness still proceeds).
    """
    import re as _re
    targets: list[str] = []
    # 匹配「xx.xlsx / xx.xls / xx.csv / xx.txt / xx.md」等文件名
    for m in _re.finditer(r"[^\s，。；、,;:（）()「」\"']+\.(?:xlsx|xls|csv|txt|md|json|py)\b", prompt):
        t = m.group(0).strip()
        if t not in targets:
            targets.append(t)
    if not targets:
        # 匹配「XX表」「XX汇总表」等
        for m in _re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}(?:表|文件|文档|sheet)", prompt):
            t = m.group(0).strip()
            if t not in targets:
                targets.append(t)
    return targets[:6]


def _intent_summary(kind: str, prompt: str) -> str:
    """One-line human summary of the declared intent."""
    first = prompt[:60] + ("…" if len(prompt) > 60 else "")
    kind_label = {
        "explain": "解释/问答", "read_file": "读取文件", "read_data": "数据查询",
        "reconcile": "对账/比对", "update": "修改/写回", "report": "生成报告",
        "inspect": "排查/定位",
    }.get(kind, "执行")
    return f"{kind_label}：{first}"


class AgentCore:
    """General Agent executor — runs the 7-stage workflow in a background thread."""

    def __init__(self, llm_client: LLMClient, agent_config: AgentConfig,
                 context_manager: ContextManager,
                 emitter: Emitter,
                 stop_event: threading.Event,
                 work_dir: str = "",
                 project_id: str = "",
                 run_store=None,
                 tool_call_store=None,
                 status_callback=None) -> None:
        self.llm = llm_client
        self.config = agent_config
        self.ctx = context_manager
        self.emitter = emitter
        self.stop_event = stop_event
        self.work_dir = work_dir
        self.project_id = project_id
        self.run_store = run_store
        self.tool_call_store = tool_call_store
        # Phase 17 fix: run 状态回调（workspace 层用它同步内存 _runs 状态，
        # 使 waiting_for_user 等状态对 /api/workspace/events 可见）
        self.status_callback = status_callback
        self.tool_registry = ToolRegistry(work_dir=work_dir, project_id=project_id)

        # Run state
        self.run_id = ""
        self.plan_db_id = ""  # Phase 16 P3: persisted plan row id
        self.plan_version = 0
        self.plan_steps: list[dict] = []
        self.current_step_idx = 0
        # Phase 16: step lifecycle + progress tracking
        self._active_step_id = ""
        self._total_tool_calls = 0
        self._round_tool_count = 0
        self._round_count = 0  # Phase 17 P4: 已执行轮次（长任务观测）
        self._run_start_ts = 0.0
        self._last_progress_ts = 0.0
        # Phase 16 P3-B2: plan injected into LLM context (set by plan_task)
        self._pending_plan_guidance = ""
        # Phase 16 P1-D: real token usage accumulation (LLM response usage)
        self._usage_total = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
        self._agent_id = ""
        self._model_id = ""
        self._user_response_event = threading.Event()
        self._user_response: dict | None = None
        self._accumulated_message = ""
        self._final_reply = ""  # 最终纯文本回复（区别于工具轮 process content）
        self._run_had_tool_calls = False  # 本轮 run 是否发生过工具调用（决定最终 ctx 存储）
        self._context_initialized = False  # Track whether context already has messages
        # Phase 18 H0/H1: 阶段状态机（harness 显式阶段推进）
        self._stage = "classify"
        self._evidence_facts: list[str] = []
        self._plan_reminder_injected = False
        self._has_write_this_run = False
        self._verify_injected = False  # Phase 18 H2: 是否已注入验证提示
        self._verify_checked = False   # Phase 18 H2: 验证是否已发出

    # ==================================================================
    # Public entry point
    # ==================================================================

    def execute(self, run_id: str, prompt: str, agent_id: str, model_id: str,
                context_files: list[str] | None = None) -> None:
        """Execute the 7-stage workflow for a user prompt.

        Args:
            run_id: Unique run identifier.
            prompt: User's raw input message.
            agent_id: Identifier of the agent configuration.
            model_id: Identifier of the LLM model.
            context_files: List of file paths selected by the user.
        """
        self.run_id = run_id
        logger.info("AgentCore start: run=%s prompt=%.100s", run_id, prompt)
        self._agent_id = agent_id or ""
        self._model_id = model_id or ""

        # Reset per-run token accounting
        self._usage_total = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}

        # Phase 18 H0: 每 run 重置阶段状态（AgentCore 会话复用，避免跨 run 残留）
        self._stage = ""
        self._evidence_facts = []
        self._plan_reminder_injected = False
        self._has_write_this_run = False
        self._verify_injected = False
        self._verify_checked = False

        # Persist run
        if self.run_store:
            try:
                self.run_store.create_run(
                    run_id=run_id,
                    project_id=self.project_id,
                    agent_id=agent_id,
                    model_id=model_id,
                    title=prompt[:80],
                )
            except Exception as e:
                logger.warning("Failed to persist run: %s", e)

        # Initialize or append user message to context
        if not self._context_initialized:
            self.ctx.reset(prompt)
            self._context_initialized = True
        else:
            self.ctx.add_user_message(prompt)
        
        # Reset accumulated message for this run
        self._accumulated_message = ""

        # Emit run_created
        self._emit(run_created(
            run_id=run_id,
            agent=agent_id,
            model=model_id,
            context_file_count=len(context_files or []),
            title=prompt[:80],
        ))

        try:
            self._run_workflow(prompt)
        except Exception as e:
            logger.exception("AgentCore fatal error: run=%s", run_id)
            self._emit(run_failed(str(e)))
            self._update_status(STATUS_FAILED, error_message=str(e))

    # ==================================================================
    # Task Classification → Routing
    # ==================================================================

    def _classify_task(self, prompt: str) -> dict:
        """Use LLM to classify the task as QA (问答), DESIGN (设计策划), or OP (操作).

        Phase 7.3: Extended from binary to ternary classification.
        Uses streaming to capture reasoning_content so users can see
        how the classification was determined.
        """
        classify_prompt = (
            "你是一个任务分类器。判断用户的任务属于以下哪一类：\n\n"
            "- qa (问答类): 纯知识问答、计算、解释、讨论、建议。不需要读写文件。\n"
            "- design (设计策划类): 需要产出方案、报告、预算、架构文档、策划案等主观文本产物。\n"
            "  用户描述通常简短、信息可能不完备。\n"
            "- op (操作类): 涉及明确的文件读写、项目目录操作、搜索文件、修改代码文件、\n"
            "  Excel处理等客观操作。\n\n"
            f"用户任务：{prompt}\n\n"
            "请只返回一个 JSON 对象，不要任何其他文字：\n"
            '{"type": "qa", "reason": "简短理由"}\n'
            "或\n"
            '{"type": "design", "reason": "简短理由"}\n'
            "或\n"
            '{"type": "op", "reason": "简短理由"}'
        )
        raw_parts: list[str] = []
        reasoning_parts: list[str] = []

        try:
            for chunk in self.llm.chat_stream(
                [{"role": "user", "content": classify_prompt}],
                temperature=0.0,
                max_tokens=100,
                thinking=True if self._supports_thinking() else None,
                reasoning_effort="medium" if self._supports_thinking() else None,
                clear_thinking=False if (self._model_id or "").lower().startswith("glm") else None,
            ):
                reasoning_text = chunk.get("reasoning_delta") or ""
                if reasoning_text:
                    reasoning_text = _normalize_delta_text(reasoning_text)
                    if reasoning_text:
                        reasoning_parts.append(reasoning_text)
                        self._emit(reasoning_delta(reasoning_text))

                text = chunk.get("delta") or ""
                if text:
                    raw_parts.append(text)

                # Phase 16 P1-D: accumulate real token usage
                self._accumulate_usage(chunk)

            raw = "".join(raw_parts)
        except Exception as e:
            logger.warning("Task classification failed: %s — defaulting to qa", e)
            return {"type": "qa", "reason": "分类失败，默认走问答路径"}

        # Close classification reasoning drawer before routing decision
        self._emit(reasoning_closed())

        # Parse JSON from response
        try:
            json_str = raw
            if "```" in raw:
                start = raw.index("```") + 3
                end = raw.index("```", start) if "```" in raw[start:] else len(raw)
                json_str = raw[start:end].strip()
            result = json.loads(json_str)
            task_type = result.get("type", "qa")
            if task_type not in ("qa", "design", "op"):
                task_type = "qa"
            return {"type": task_type, "reason": result.get("reason", "")}
        except Exception as e:
            logger.warning("Task classification parse failed: %s", e)
            return {"type": "qa", "reason": "分类解析失败，默认走问答路径"}

    # ==================================================================
    # Phase 18 H0/H1: 阶段状态机（harness 显式阶段推进）
    # ==================================================================

    def _set_stage(self, stage: str, label: str, detail: str = "") -> None:
        """Transition the harness stage and emit stage_changed.

        Stages: classify → clarify → evidence_plan → evidence_collect →
                execution_plan → execute → verify → finalize
        """
        prev = self._stage
        if prev == stage:
            return
        self._stage = stage
        self._emit(stage_changed(stage=stage, label=label,
                                 prev_stage=prev, detail=detail))
        logger.info("Stage transition: %s → %s (%s)", prev, stage, detail)

    def _needs_plan(self, task_type: str, prompt: str) -> bool:
        """Phase 18 H1: 复杂度判定（用户确认规则）。

        涉及 2+ 文件 / 读后写 / 数据库查询 / 跨表比对 / 代码修改 /
        预计超 3 次工具调用 → 必须 plan_task。
        """
        if task_type == "qa":
            return False
        if task_type == "design":
            return True
        hints = ("修改", "编辑", "写入", "更新", "删除", "对比", "比对",
                 "核对", "对账", "多个文件", "两个文件", "代码", "函数",
                 "重构", "跨表", "关联", "统计", "汇总", "聚合", "导入",
                 "导出", "合并", "拆分", "分组")
        return any(h in prompt for h in hints)

    # ==================================================================
    # Phase 11: Unified Tool-Driven Loop (replaces hardcoded pipelines)
    # ==================================================================

    def _run_workflow(self, prompt: str) -> None:
        """Unified LLM loop — all tools available, LLM decides what to do.

        Phase 11: Instead of routing to three separate hardcoded pipelines
        (QA / Design / OP), provide ALL tools to the LLM and let it decide
        which ones to use. This means:
        - A QA question can still call ask_user or plan_task if needed
        - A design task gets ask_user + plan_task + direct streaming
        - An OP task gets plan_task + file tools (future) + ask_user

        The _classify_task call remains only to emit a reasoning_summary
        for user visibility — it no longer controls execution flow.
        """
        if self._check_interrupt():
            return

        self._update_status(STATUS_RUNNING)

        # Classify for user visibility only (no routing)
        classification = self._classify_task(prompt)
        task_type = classification.get("type", "qa")
        reason = classification.get("reason", "")
        logger.info("Task classified as '%s': %s", task_type, reason)

        type_label = {"qa": "📚 问答类", "design": "🎨 设计策划类", "op": "🔧 操作类"}
        # Phase 18 H0: 分类阶段显式进入状态机（阶段卡承担「任务分类」展示，
        # 不再额外发 reasoning_summary，避免前端出现两个「任务分类」）
        self._set_stage("classify", "任务分类",
                        f"{type_label.get(task_type, '📚 问答类')} — {reason}")

        # Phase 18 H1: 证据阶段强制（涉及文件/数据/方案任务）+ 复杂度判定
        needs_evidence = task_type in ("op", "design")
        needs_plan = self._needs_plan(task_type, prompt)
        self._plan_reminder_injected = False

        # Run the unified loop — one loop for all task types
        self._run_unified_loop(prompt, task_type,
                               needs_evidence=needs_evidence,
                               needs_plan=needs_plan)

    def _supports_thinking(self) -> bool:
        """判断模型是否支持思考模式参数（thinking.type + reasoning_effort）。

        调研确认（2026-08-17）：
          - DeepSeek V3.2+：支持 `thinking: {"type": "enabled/disabled"}` +
            `reasoning_effort`，流式返回 `reasoning_content`，思考模式默认开启。
          - 智谱 GLM-5.2（z.ai/bigmodel.cn）：参数格式与 DeepSeek **完全一致**
            （`thinking.type` + `reasoning_effort`，流式返回 `delta.reasoning_content`），
            思考模式默认 enabled；HTTP 请求时 thinking 为顶层参数。
          - 千问 Qwen（阿里云百炼 OpenAI 兼容）：标准 OpenAI 参数集，
            **无 thinking/reasoning_effort 参数**（qwen-plus 等不支持），
            传未知字段可能被拒绝 → 不传。
        因此 thinking 参数仅对 deepseek / glm 系模型启用。
        """
        m = (self._model_id or "").lower()
        if "deepseek" in m:
            return True
        if "glm" in m:
            return True
        return False

    def _run_unified_loop(self, prompt: str, task_type: str,
                          needs_evidence: bool = False,
                          needs_plan: bool = False) -> None:
        """Single ReAct-style loop: LLM streams + tool-calls until done.

        Phase 11: All tools (ask_user, plan_task, future: read/write/search)
        are available. LLM picks tools autonomously. No hardcoded branches.

        Phase 18 H0/H1: harness 显式阶段推进 ——
          classify → evidence_plan → evidence_collect → execute；
        涉及文件/数据/方案任务先声明意图 + 证据计划，再采集证据；
        写类工具检测为「写后强制 verify」（H2）预留 _has_write_this_run；
        复杂任务（needs_plan）在工具数 ≥3 且未规划时注入 plan 提醒。
        """
        # Phase 17: max_iterations=0 表示无上限（默认），唯一终止 = 手动停止
        max_rounds = self.config.workflow.max_iterations or 0
        self._run_start_ts = time.time()  # Phase 16: progress heartbeat baseline

        # Phase 18 H1: 证据阶段 —— 先声明意图 + 证据计划，再进入采集
        self._evidence_facts = []
        self._has_write_this_run = False
        if needs_evidence:
            intent_kind = _infer_intent_kind(task_type, prompt)
            targets = _infer_evidence_targets(prompt)
            self._emit(intent_declared(
                kind=intent_kind,
                summary=_intent_summary(intent_kind, prompt),
                targets=targets,
                reason=f"任务分类: {task_type}",
            ))
            self._set_stage("evidence_plan", "证据规划",
                            "任务涉及文件/数据，先明确要读取哪些证据")
            self._emit(evidence_plan(
                targets=targets,
                reason="确认目标对象的结构/字段后再决策",
                tools=sorted(EVIDENCE_TOOLS),
            ))
            self._set_stage("evidence_collect", "证据采集",
                            "按计划读取证据")
        else:
            self._set_stage("execute", "执行", "纯问答直接执行")

        # System guidance varies slightly by task type
        system_msg = self._build_unified_system_prompt(task_type)
        messages: list[dict] = [{"role": "system", "content": system_msg}]
        # Include existing conversation context (skip the prompt that's already added by execute())
        # Phase 8 fix: use get_messages() so compression is applied before sending to LLM
        # Phase 17 fix: 必须同时包含 tool 角色消息——跨 run 上下文延续时，
        # assistant(tool_calls) 与其 tool 结果必须成对出现，否则 OpenAI 兼容
        # API 以 400 "assistant message with 'tool_calls' must be followed by
        # tool message" 拒绝（2026-08-17 Test 4 复现）。
        for m in self.ctx.get_messages():
            if m.get("role") in ("user", "assistant", "tool"):
                messages.append(m)
        # Prompt is already in ctx._messages from execute() — do NOT double-add

        # Phase 8: ALL tools available for LLM function calling
        tools = ALL_TOOL_SCHEMAS
        _reasoning_active = False
        final_content: list[str] = []
        # DeepSeek 思考模式 + 工具调用：携带 tools 的请求在后续所有请求中
        # 必须完整回传 reasoning_content，否则 API 返回 400 / 上下文断裂
        # （模型会丢失之前的思考，表现为此轮复述工具过程、输出混乱）。
        round_reasoning: list[str] = []
        # 三家模型思考模式差异（2026-08-17 调研确认）：
        #  - DeepSeek V3.2+ 与 智谱 GLM-5.2：参数格式一致——thinking.type +
        #    reasoning_effort，思考模式默认开启，流式返回 reasoning_content。
        #    agent/coding 场景 GLM 推荐 clear_thinking=False（Preserved
        #    Thinking：保留历史 reasoning_content 需完整回传——我们的
        #    assistant_msg/ctx 已实现完整回传）。
        #  - 千问 Qwen（阿里云百炼 OpenAI 兼容）：标准 OpenAI 参数集，
        #    无 thinking 参数 → 不传（避免未知字段被拒）。
        _thinking = True if self._supports_thinking() else None
        _effort = "medium" if self._supports_thinking() else None
        _clear_thinking = False if (self._model_id or "").lower().startswith("glm") else None

        round_idx = 0
        while max_rounds <= 0 or round_idx < max_rounds:
            if self._check_interrupt():
                return

            # Phase 16 P3-B2: inject the plan once, right after plan_task
            # returns, so the LLM sees the plan it generated on later rounds.
            if self._pending_plan_guidance:
                messages.append({"role": "system", "content": self._pending_plan_guidance})
                self._pending_plan_guidance = ""

            tool_call_accumulator: dict[int, dict] = {}
            _reasoning_active = False

            try:
                for chunk in self.llm.chat_stream(
                    messages, tools=tools, temperature=0.3, max_tokens=8192,
                    thinking=_thinking, reasoning_effort=_effort,
                    clear_thinking=_clear_thinking,
                ):
                    if self._check_interrupt():
                        return

                    # ── Reasoning ──
                    reasoning = chunk.get("reasoning_delta") or ""
                    if reasoning:
                        _reasoning_active = True
                        reasoning = _normalize_delta_text(reasoning)
                        if reasoning:
                            round_reasoning.append(reasoning)
                            self._emit(reasoning_delta(reasoning))

                    # ── Tool call deltas ──
                    tc_deltas = chunk.get("tool_call_delta")
                    if tc_deltas:
                        for tcd in tc_deltas:
                            idx = tcd.get("index", 0)
                            if idx not in tool_call_accumulator:
                                tool_call_accumulator[idx] = {
                                    "id": "", "name": "", "arguments": ""
                                }
                            acc = tool_call_accumulator[idx]
                            if tcd.get("id"):
                                acc["id"] = tcd["id"]
                            if tcd.get("name"):
                                acc["name"] = tcd["name"]
                            if tcd.get("arguments"):
                                acc["arguments"] += tcd["arguments"]

                    # ── Content ──
                    text = chunk.get("delta") or ""
                    if text:
                        # Normalize broken whitespace (word-by-word + 3+ newlines)
                        # seen in long deepseek tool-calling sessions.
                        text = _normalize_delta_text(text)
                        if not text:
                            continue
                        if _reasoning_active:
                            self._emit(reasoning_closed())
                            _reasoning_active = False
                    self._emit(message_delta(text))
                    final_content.append(text)
                    self._accumulated_message += text
                    self._final_reply += text

            except Exception as e:
                logger.exception("Unified loop LLM error at round %d", round_idx)
                self._emit(message_delta(f"\n\n⚠️ 出错: {e}"))
                self._log_event("llm.error",
                                f"模型调用失败: {str(e)[:200]}",
                                status="error")
                break

            if _reasoning_active:
                self._emit(reasoning_closed())

            # ── No tool calls → LLM is done ──
            if not tool_call_accumulator:
                break

            # Phase 16: activate the plan step container for this round
            # (tools in this round attach to it). One LLM round ≈ one step.
            self._start_step_round(round_idx)

            # ── Build assistant message with tool calls ──
            assistant_msg: dict = {"role": "assistant"}
            if final_content:
                assistant_msg["content"] = "\n".join(final_content)
            # DeepSeek 思考模式工具调用：必须回传本轮 reasoning_content，
            # 否则后续带 tools 的请求报 400 / 模型丢失思考上下文。
            # 其他模型（千问/GLM/OpenAI 兼容）会忽略未知字段，无副作用。
            if round_reasoning:
                assistant_msg["reasoning_content"] = "".join(round_reasoning)
            tool_call_entries: list[dict] = []

            # Phase 1: collect all tool call entries
            for tc in sorted(tool_call_accumulator.values(), key=lambda x: x.get("index", 0) if "index" in x else 0):
                tc_id = tc["id"]
                name = tc["name"]
                args_str = tc.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    args = {}

                tool_call_entries.append({
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args_str},
                })

            # Append assistant message BEFORE tool results (required by OpenAI API)
            assistant_msg["tool_calls"] = tool_call_entries
            messages.append(assistant_msg)
            self._run_had_tool_calls = True
            # 同步到会话上下文：DeepSeek 思考模式工具调用轮次，assistant 消息
            # 必须保留 reasoning_content 供后续带 tools 的请求回传（含跨 run
            # 的会话延续）；千问/GLM 忽略未知字段。tool_calls 亦一并保留。
            try:
                self.ctx.add_assistant_message(
                    content=assistant_msg.get("content") or "",
                    tool_calls=assistant_msg.get("tool_calls"),
                    reasoning_content=assistant_msg.get("reasoning_content"),
                )
            except Exception as _e:  # noqa: BLE001
                logger.warning("Failed to persist assistant tool-call turn: %s", _e)

            # Phase 2: dispatch tools (may block) and feed results
            for tc in sorted(tool_call_accumulator.values(), key=lambda x: x.get("index", 0) if "index" in x else 0):
                tc_id = tc["id"]
                name = tc["name"]
                args_str = tc.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    args = {}

                # ── Phase 8: Dispatch via ToolRegistry ──
                # ask_user and plan_task still handled by AgentCore for UI integration

                if name == "ask_user":
                    result_text = self._execute_ask_user_tool(args, tc_id)
                elif name == "plan_task":
                    result_text = self._execute_plan_task_tool(args)
                else:
                    # Phase 16: lazily activate the step container — plan_task
                    # may have been called earlier in THIS SAME round (plan_steps
                    # now exists but _active_step_id is still empty), so the
                    # first real tool of the round must open the container.
                    if self.plan_steps and not self._active_step_id and self.current_step_idx < len(self.plan_steps):
                        self._start_step_round(round_idx)
                    # Phase 16: semantic title/icon + step attachment for the tool card
                    _title_info = humanize_tool_call(name, args)
                    _step_id = self._active_step_id or ""
                    input_summary = json.dumps(args, ensure_ascii=False)[:300]
                    # Phase 16 P3-①: attribute the tool to its plan step so
                    # the panel's real state includes tool counts.
                    if _step_id:
                        for _s in self.plan_steps:
                            if _s.get("step_id") == _step_id:
                                _s["tool_count"] = _s.get("tool_count", 0) + 1
                                break
                    self._emit(tool_started(
                        tool_id=tc_id, name=name, input_summary=input_summary,
                        title=_title_info["title"], icon=_title_info["icon"],
                        category=_title_info["category"], step_id=_step_id,
                    ))

                    # Phase 8: dispatch via ToolRegistry
                    # Phase 16 P2: start a heartbeat thread so long-running
                    # tools (e.g. run_command with 60s timeout) surface a
                    # live "正在运行 … · Ns" progress to the status bar.
                    _tool_hb_stop = threading.Event()

                    def _tool_heartbeat():
                        _t0 = time.time()
                        while not _tool_hb_stop.wait(1.0):
                            _elapsed = int((time.time() - _t0) * 1000)
                            self._emit(run_progress(
                                current_step=min(self.current_step_idx + 1, len(self.plan_steps)),
                                total_steps=len(self.plan_steps),
                                tool_count=self._total_tool_calls,
                                elapsed_ms=_elapsed,
                                label=f"正在运行 {_title_info.get('title') or name} · {_elapsed // 1000}s",
                            ))

                    _tool_hb = threading.Thread(target=_tool_heartbeat, daemon=True)
                    _tool_hb.start()
                    _t0 = time.time()
                    try:
                        result = self.tool_registry.dispatch(name, args)
                    finally:
                        _tool_hb_stop.set()
                        _tool_hb.join(timeout=1.0)
                    _duration_ms = (time.time() - _t0) * 1000

                    # Phase 18 H0/H1: 写工具检测 + 证据记录 + 阶段切换
                    if name in WRITE_TOOLS:
                        self._has_write_this_run = True
                        if self._stage == "evidence_collect":
                            self._set_stage("execute", "执行",
                                            "检测到写操作，进入执行阶段")
                            if self._evidence_facts:
                                self._emit(evidence_collected(
                                    summary="已采集必要证据，开始执行",
                                    key_facts=self._evidence_facts[:5],
                                    sufficient=True))
                    if (self._stage == "evidence_collect"
                            and name in EVIDENCE_TOOLS
                            and result.get("success")):
                        _o = summarize_output(name, result)
                        self._evidence_facts.append(
                            f"{_title_info.get('title') or name}: {_o}"[:120])

                    if result.get("needs_approval"):
                        # Emit approval request and wait
                        tool_name = result.get("tool", name)
                        reason_str = result.get("reason", f"工具 '{tool_name}' 需要确认")
                        # Phase 16 P1-C: build a semantic approval prompt —
                        # tool title (human verb phrase) + expected effect +
                        # parameter summary, instead of only a raw reason.
                        approval_lines = [
                            f"**{_title_info.get('icon', '🛡️')} 请求执行操作**",
                            f"{_title_info.get('title') or tool_name}",
                        ]
                        effect = args.get("expected_effect") or args.get("reason")
                        if effect:
                            approval_lines.append(f"**预期效果**：{str(effect)[:120]}")
                        approval_lines.append(
                            f"**参数**：`{json.dumps(args, ensure_ascii=False)[:200]}`"
                        )
                        approval_lines.append(f"审批理由：{reason_str}")
                        answer = self._ask_user(
                            question="\n\n".join(approval_lines),
                            input_type="confirm",
                            tool_call_id=tc_id,
                        )
                        if answer is None:
                            self._emit(tool_completed(
                                tool_id=tc_id, name=name, output="用户取消",
                                status="cancelled", duration_ms=_duration_ms,
                                output_summary="用户取消", step_id=_step_id,
                            ))
                            self._finalize_cancelled("user_cancelled_approval")
                            return  # User cancelled
                        if answer.strip().lower() in ("否", "no", "取消", ""):
                            result_text = f"[用户拒绝] 工具 '{tool_name}' 被用户拒绝执行"
                            self._emit(tool_completed(
                                tool_id=tc_id, name=name, output="用户拒绝执行",
                                status="rejected", duration_ms=_duration_ms,
                                output_summary="用户拒绝执行", step_id=_step_id,
                            ))
                        else:
                            # User approved — execute directly bypassing approval
                            fn = self.tool_registry.get(name)
                            if fn:
                                # Phase 16 P2: heartbeat for long approved tools
                                _tool_hb_stop2 = threading.Event()

                                def _hb2():
                                    _t0b = time.time()
                                    while not _tool_hb_stop2.wait(1.0):
                                        _el = int((time.time() - _t0b) * 1000)
                                        self._emit(run_progress(
                                            tool_count=self._total_tool_calls,
                                            elapsed_ms=_el,
                                            label=f"正在运行 {_title_info.get('title') or name} · {_el // 1000}s",
                                        ))

                                _tool_hb2 = threading.Thread(target=_hb2, daemon=True)
                                _tool_hb2.start()
                                try:
                                    raw_result = fn(args or {}, work_dir=self.work_dir)
                                    result_text = json.dumps(raw_result, ensure_ascii=False)
                                    self._emit(tool_completed(
                                        tool_id=tc_id, name=name,
                                        output=str(raw_result)[:300],
                                        status="success" if raw_result.get("success") else "failed",
                                        duration_ms=_duration_ms,
                                        output_summary=summarize_output(name, raw_result),
                                        step_id=_step_id,
                                    ))
                                except Exception as e:
                                    result_text = f"工具执行失败: {e}"
                                    self._emit(tool_completed(
                                        tool_id=tc_id, name=name, output=str(e),
                                        status="failed", duration_ms=_duration_ms,
                                        output_summary=f"失败: {e}", step_id=_step_id,
                                    ))
                                finally:
                                    _tool_hb_stop2.set()
                                    _tool_hb2.join(timeout=1.0)
                            else:
                                result_text = f"未知工具 '{name}'"
                    else:
                        result_text = json.dumps(result, ensure_ascii=False)
                        self._emit(tool_completed(
                            tool_id=tc_id, name=name,
                            output=str(result)[:300],
                            status="success" if result.get("success") else "failed",
                            duration_ms=_duration_ms,
                            output_summary=summarize_output(name, result),
                            step_id=_step_id,
                        ))

                    # Phase 8: persist tool call to SQLite (best-effort)
                    # Align record with the real LLM tool_call_id and result status
                    _tool_status = "completed"
                    if result.get("needs_approval"):
                        _tool_status = "approved"
                    elif not result.get("success"):
                        _tool_status = "failed"
                    self._persist_tool_call(name, args, result_text,
                                            tool_call_id=tc_id, status=_tool_status)

                # Cancelled → stop immediately (emit terminal event so frontend doesn't hang)
                if result_text is None:
                    self._finalize_cancelled("user_cancelled")
                    return

                # Phase 16: track tool counts for progress heartbeat
                self._total_tool_calls += 1
                self._round_tool_count += 1
                self._maybe_emit_progress()

                # Phase 18 H2: verify 阶段内调用验证类工具 → 视为完成验证
                if (self._stage == "verify" and not self._verify_checked
                        and name in EVIDENCE_TOOLS | {"run_command", "compare_excel_sheets"}):
                    self._verify_checked = True
                    self._emit(verification_completed(
                        passed=True,
                        summary=f"已通过验证动作: {_title_info.get('title') or name}",
                        details=str(result.get("message") or "")[:200]))

                # Feed tool result back to LLM (must come after assistant msg)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                })
                # Phase 17 fix: 同步工具结果到会话上下文，与 assistant(tool_calls)
                # 消息配对持久化。否则跨 run 上下文延续时，ctx 中只保留悬空的
                # assistant.tool_calls 而无对应 tool 消息，OpenAI 兼容 API 会以
                # "assistant message with 'tool_calls' must be followed by tool
                # message" 400 拒绝（2026-08-17 全量回归 Test 4 复现）。
                try:
                    self.ctx.add_tool_result(tc_id, name, result_text)
                except Exception as _e:  # noqa: BLE001
                    logger.warning("Failed to sync tool result to ctx: %s", _e)

            # Phase 16: close the step container for this round
            self._finish_step_round()
            final_content = []
            round_reasoning = []   # 本轮 reasoning 已回传进 assistant_msg，清空待下轮
            # 工具轮后重置最终回复（下一轮若为纯文本轮，从零累计）；
            # 若无后续纯文本轮（工具轮即结束），保留空。
            self._final_reply = ""
            round_idx += 1
            # Phase 17 P4: 记录已执行轮次（供 run_progress 观测）
            self._round_count = round_idx

            # Phase 18 H1: 证据阶段 → 执行阶段推进（至少一轮证据采集后）
            if self._stage == "evidence_collect" and round_idx >= 1:
                self._set_stage("execute", "执行", "证据已采集，进入执行阶段")
                self._emit(evidence_collected(
                    summary="已完成证据采集",
                    key_facts=self._evidence_facts[:5],
                    sufficient=True))

            # Phase 18 H1: 复杂任务 → 提醒先 plan_task（软引导，不硬拦截）
            if (needs_plan and not self._plan_reminder_injected
                    and self._total_tool_calls >= 3
                    and not self.plan_steps):
                messages.append({"role": "system", "content":
                    "本任务较复杂：请先调用 plan_task 生成执行计划，"
                    "再按计划逐步执行；执行完成后如有写操作请验证结果。"})
                self._plan_reminder_injected = True

            # Phase 18 H2: 写后强制验证 —— 本轮有写类工具 → 进入 verify 阶段并提示
            if (self._has_write_this_run and not self._verify_injected
                    and not self._verify_checked):
                self._set_stage("verify", "验证",
                                "检测到写操作，进入验证阶段")
                self._emit(verification_started(
                    kind="readback",
                    summary="写入/修改已完成，进行验证"))
                messages.append({"role": "system", "content":
                    "你刚刚执行了写操作（写入/修改/删除/命令）。请进入验证阶段："
                    "回读文件、复核数据或运行检查，确认结果正确后再总结回答。"
                    "如验证失败，请重试或向用户说明。"})
                self._verify_injected = True

        # Persist and finish
        # 工具轮 assistant 消息（含 tool_calls + reasoning）已逐条存入 ctx；
        # 这里只补存「最终纯文本回复」（若存在），避免 content 重复、不破坏
        # OpenAI 消息的 tool_calls→tool 配对结构。
        if self._final_reply.strip():
            self.ctx.add_assistant_message(content=self._final_reply)
        elif (self._accumulated_message.strip() and not self._run_had_tool_calls):
            # 纯文本 run（无工具调用）：_final_reply 即全部内容，兜底
            self.ctx.add_assistant_message(content=self._accumulated_message)
        # Phase 18 H2: run 结束前若有写操作但未验证，补发未验证事件
        if self._has_write_this_run and not self._verify_checked:
            self._emit(verification_completed(
                passed=False,
                summary="存在写操作但未完成验证（模型未执行验证动作）"))
        self._finalize_run()

    def _build_project_data_summary(self) -> str:
        """Build the project data plane schema summary for LLM context.

        Phase 14B (PRD §3.12.6): only lightweight schema metadata enters the
        context (~300 tokens/file); the full data stays in SQLite and is
        queried via query_table / table_stats.  Never injects whole tables.
        """
        if not self.project_id:
            return ""
        try:
            from storage.db import get_db
            from storage.project_data_store import ProjectDataStore
            store = ProjectDataStore(get_db())
            files = store.list_files(self.project_id)
            if not files:
                return ""
            lines = ["[项目数据库数据文件]", "[目录文件 ↔ 数据库文件映射]"]
            for f in files:
                if f.get("status") != "done":
                    continue
                sheets = f.get("sheets") or []
                sheet_desc = []
                for s in sheets:
                    headers = s.get("headers") or []
                    cols = ", ".join(
                        f"{h['name']}:{h['type']}" for h in headers
                    ) or "无字段"
                    sheet_desc.append(
                        f"{s.get('sheet_name')}({s.get('row_count', 0)}行): {cols}"
                    )
                if not sheet_desc:
                    continue
                # Phase 16 P3: explicit dual-identity mapping — the directory
                # file (source_path) and the DB file (file_name) are the SAME
                # dataset. Whichever the user mentions, the LLM must query the
                # database record (file_name) — never the raw Excel.
                lines.append(
                    f"- 目录「{f.get('source_path')}」 ⇄ 库文件「{f.get('file_name')}」"
                    f" ({f.get('total_rows', 0)}行, {f.get('sheet_count', 0)}分表): "
                    + "; ".join(sheet_desc)
                )
            if len(lines) <= 2:
                return ""
            lines.append(
                "[规则] 上表每个目录文件与库文件是同一份数据。无论用户用目录路径"
                "（如 待处理数据/xxx.xls）还是库文件名（如 xxx.xls）提及，"
                "都必须使用 query_table / table_stats / join_tables 在项目数据库中查询，"
                "绝对禁止 read_excel / read_file 读取上表列出的原始 Excel 文件；"
                "未出现在上表中的文件才允许用 read_excel 读取（或先 import_excel_to_db 导入）；"
                "跨表核对使用 join_tables（注意不支持 RIGHT JOIN）；"
                "修改数据使用 update_rows/insert_rows/delete_rows（需用户确认并记录变更日志），"
                "修改完成后调用 export_project_data 回写 Excel。"
            )
            return "\n\n".join(lines)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to build project data summary: %s", e)
            return ""

    def _build_unified_system_prompt(self, task_type: str) -> str:
        """Build a single system prompt that adapts to all task types."""
        base = (
            "你是「通用智能体」，当前模式拥有全部 19 种工具能力"
            "（文件/Excel/数据库/命令/计划）。你是一个面向财务人员的全功能智能助手。"
            "你有以下工具可用：\n\n"
            "### 📋 计划与交互\n"
            "- ask_user: 向用户提问（文本/确认/选项），用于澄清需求或请求审批\n"
            "- plan_task: 为复杂任务生成结构化执行计划\n\n"
            "### 📁 文件操作\n"
            "- read_file: 读取文件内容，支持编码检测和行范围\n"
            "- list_directory: 列出目录内容，支持递归\n"
            "- search_files: 按文件名模式或内容搜索文件\n"
            "- write_file: 写入文件（会自动备份已有文件，需用户确认）\n"
            "- create_directory: 创建目录\n"
            "- delete_path: 删除文件/目录（需用户逐项确认）\n"
            "- move_path: 移动/重命名文件或目录\n"
            "- copy_path: 复制文件或目录\n\n"
            "### 💻 命令执行\n"
            "- run_command: 在工作区执行命令行（PowerShell/cmd/python等，需用户确认）\n\n"
            "### 🐍 Python环境\n"
            "- get_python_version: 获取Python版本\n"
            "- get_python_executable: 获取Python解释器路径\n"
            "- get_installed_packages: 列出已安装的包\n"
            "- configure_python_environment: 安装Python包（需用户确认）\n\n"
            "### 📊 Excel操作\n"
            "- read_excel: 读取Excel文件数据（仅限未导入项目数据库的应急读取）\n"
            "- get_sheet_info: 获取工作表元信息（表名、行列数、表头）\n"
            "- write_excel: 写入Excel文件（需用户确认）\n"
            "- analyze_excel: 分析Excel结构，建议关键字段\n"
            "- compare_excel_sheets: 对比两个工作表差异（财务核对核心工具）\n\n"
            "### 🗄️ 项目数据库（Phase 14）\n"
            "- import_excel_to_db: 将Excel导入项目数据库（对话中提及处理某个Excel时优先调用）\n"
            "- query_table: 库内查询数据表（按字段筛选/排序/限量），结果子集回上下文\n"
            "- table_stats: 库内聚合统计（sum/avg/count/min/max + 分组）\n"
            "- join_tables: 跨表连接核对（inner/left，库内 JOIN；SQLite 不支持 RIGHT JOIN）\n"
            "- update_rows: 按条件更新数据行（cell 级变更日志，需用户确认）\n"
            "- insert_rows: 插入新行（cell 级变更日志，需用户确认）\n"
            "- delete_rows: 按条件删除行（cell 级变更日志，需用户确认）\n"
            "- export_project_data: 物化回写原始Excel（模板重建/精确回写 + 自动备份）\n\n"
            "### ⚠️ 重要原则\n"
            "- 提问要精准：一次只问最关键的问题\n"
            "- 能直接回答就直接回答，不要过度使用工具\n"
            "- 涉及文件写入/删除/命令执行/环境变更时，工具会自动请求用户确认\n"
            "- 所有文件操作限定在工作目录内\n"
            "- 用 Markdown 格式化输出（标题、表格、代码块）\n"
            "- 财务数据对比优先使用 compare_excel_sheets\n"
            "- 项目数据库数据文件映射表（[目录文件 ↔ 数据库文件映射]）中列出的每个文件：\n"
            "  无论用户用目录路径还是文件名提及，都必须用 query_table / table_stats\n"
            "  / join_tables 库内查询（数据不出库），绝对禁止 read_excel / read_file\n"
            "  读取其原始 Excel；只有映射表之外的文件才允许 read_excel\n"
            "\n"
            "### 📖 大文件分块读入协议（长任务）\n"
            "- 文本文件行数 > 400：禁止一次读完，先用 read_file（不带行范围）确认\n"
            "  total_lines，然后按每块 300-400 行分块读取（start_line/end_line）；\n"
            "  每读完一块立即用一段话提炼要点，全部块读完再综合分析，避免上下文堆积。\n"
            "- Excel 文件行数 > 1000 或已导入项目数据库：禁止 read_excel 拉全量，\n"
            "  走 import_excel_to_db → query_table 分页/聚合（table_stats 汇总）；\n"
            "  应急读取未导入文件时用 range_spec 按 A1 区域分块。\n"
            "- 任务执行轮次无上限，直到完成或用户手动停止；数据优先留在数据库，\n"
            "  绝不把整表/整文件内容拉入对话（只带结构 + 结果子集 + 聚合）。\n"
            "- 长任务要点写入工作记忆：每块要点与中间结论写入 workspace/.task_memory/\n"
            "  下（write_file，需用户确认一次），后续轮次可读取，避免压缩后遗忘。\n"
        )
        data_summary = self._build_project_data_summary()
        if data_summary:
            base += "\n\n" + data_summary
        if task_type == "op":
            base += "\n优先调用 plan_task 生成执行计划，然后逐步完成。"
        elif task_type == "design":
            base += "\n通过 ask_user 收集需求后，直接输出完整方案文档。"
        return base

    # ==================================================================
    # Tool executors (called by _run_unified_loop)
    # ==================================================================

    def _execute_ask_user_tool(self, args: dict, tool_call_id: str) -> str | None:
        """Execute the ask_user tool — blocks until user responds.

        Returns user's answer string, or None if cancelled.
        """
        question = args.get("question", "请提供更多信息")
        input_type = args.get("input_type", "text")
        options = args.get("options")
        allow_skip = args.get("allow_skip", False)
        multi_select = args.get("multi_select", False)

        self._emit(reasoning_summary("需求澄清", question))
        answer = self._ask_user(
            question=question,
            input_type=input_type,
            options=options,
            allow_skip=allow_skip,
            multi_select=multi_select,
            tool_call_id=tool_call_id,
        )
        if answer is None:
            return None  # cancelled
        if answer.strip().lower() in ("跳过", "skip", ""):
            return f"[用户跳过] {question}"
        return f"用户回答: {answer}"

    def _execute_plan_task_tool(self, args: dict) -> str:
        """Execute the plan_task tool — emit plan_proposed to task panel.

        Renders steps into the frontend task panel without blocking.
        Returns a confirmation string for the LLM.
        """
        steps = args.get("steps", [])
        if not steps:
            return "错误: 未提供步骤列表"

        normalized = []
        for i, s in enumerate(steps):
            normalized.append({
                "step_id": s.get("step_id", f"step-{i+1}"),
                "title": s.get("title", f"步骤 {i+1}"),
                "description": s.get("description", ""),
                "tools_used": s.get("tools_needed", s.get("tools_used", [])),
                "weight": float(s.get("weight", 100 / len(steps))),
                "expected_output": s.get("expected_output", ""),
                "status": "pending",
            })

        self.plan_steps = normalized
        self.current_step_idx = 0  # Phase 16: restart step tracking from step 1
        self.plan_version += 1
        # Phase 16 P3-B2: inject the plan into the LLM context on next round
        self._pending_plan_guidance = self._build_plan_guidance()

        # Phase 16 P3: persist the plan to DB (single source of truth).
        if self.run_store:
            try:
                db_plan_id = self.run_store.create_plan(
                    run_id=self.run_id,
                    version=self.plan_version,
                    summary=f"共 {len(normalized)} 个步骤",
                    total_estimated_steps=len(normalized),
                    total_weight=sum(s["weight"] for s in normalized),
                )
                for i, s in enumerate(normalized):
                    self.run_store.create_plan_step(db_plan_id, s, sort_order=i)
                self.plan_db_id = db_plan_id
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to persist plan: %s", e)
                self.plan_db_id = ""

        self._emit(plan_proposed(
            steps=normalized,
            version=self.plan_version,
            summary=f"共 {len(normalized)} 个步骤",
            total_weight=sum(s["weight"] for s in normalized),
        ))

        step_list = "\n".join(
            f"  {i+1}. {s['title']} — {s.get('description', '')[:80]}"
            for i, s in enumerate(normalized)
        )
        return f"已生成 {len(normalized)} 个步骤:\n{step_list}"

    # ==================================================================
    # Phase 16: step lifecycle + progress heartbeat
    # ==================================================================

    def _build_plan_guidance(self) -> str:
        """Build a compact plan summary injected into the LLM context.

        Phase 16 P3-B2: after plan_task, the full plan is injected once so
        the LLM "sees" the plan it generated and follows it on later rounds.
        """
        if not getattr(self, "plan_steps", None):
            return ""
        lines = [f"[执行计划] 共 {len(self.plan_steps)} 步（已批准，请按此执行）："]
        for i, s in enumerate(self.plan_steps):
            desc = s.get("description", "") or ""
            lines.append(
                f"  {i+1}. {s.get('title', f'步骤 {i+1}')}"
                + (f" — {desc[:60]}" if desc else "")
            )
        lines.append(
            "请严格按照计划顺序执行每步；如某步不再适用或需要调整，可调用 plan_task 重新规划。"
        )
        return "\n".join(lines)

    def _start_step_round(self, round_idx: int) -> None:
        """Activate the plan step container for this LLM round (if a plan exists).

        Heuristic: one LLM round with tool calls ≈ one execution step. The
        first tool-emitting round after a plan is approved opens the first
        step container; each subsequent round opens the next one. Tools
        emitted during the round carry this step_id so the frontend can
        attach tool cards inside the step body.
        """
        if not self.plan_steps or self.current_step_idx >= len(self.plan_steps):
            return
        step = self.plan_steps[self.current_step_idx]
        self._active_step_id = step.get("step_id", f"step-{self.current_step_idx + 1}")
        self._round_tool_count = 0
        # Phase 16 P3: update the in-memory plan step status to running
        step["status"] = "running"
        self._emit(step_started(
            step_id=self._active_step_id,
            title=step.get("title", f"步骤 {self.current_step_idx + 1}"),
            index=self.current_step_idx,
            total=len(self.plan_steps),
        ))
        self._emit_plan_updated()

    def _finish_step_round(self) -> None:
        """Close the step container opened by _start_step_round."""
        if not self._active_step_id:
            return
        # Phase 16 P3: persist step completion status back to plan_steps.
        if self.run_store and getattr(self, "plan_db_id", ""):
            try:
                self.run_store.update_plan_step_status(
                    plan_id=self.plan_db_id,
                    step_id=self._active_step_id,
                    status="completed",
                    completed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to persist step status: %s", e)
        # Phase 16 P3: mark the in-memory plan step completed
        for s in self.plan_steps:
            if s.get("step_id") == self._active_step_id:
                s["status"] = "completed"
                break
        self._emit(step_completed(
            step_id=self._active_step_id,
            success=True,
            summary=f"{self._round_tool_count} 个操作",
        ))
        # Phase 16 P3: emit plan_updated with real step statuses so the
        # task panel reflects the true execution state (not round heuristics).
        self._emit_plan_updated()
        self._active_step_id = ""
        self._round_tool_count = 0
        if self.plan_steps and self.current_step_idx < len(self.plan_steps):
            self.current_step_idx += 1

    def _emit_plan_updated(self) -> None:
        """Emit plan_updated with the current in-memory plan step statuses.

        Phase 16 P3-①: the frontend task panel renders real execution state
        from this event — each step's status (pending/running/completed) is
        driven by actual tool attribution, not by round heuristics.
        """
        if not self.plan_steps:
            return
        self._emit(plan_updated(
            steps=[
                {
                    "step_id": s.get("step_id"),
                    "title": s.get("title", ""),
                    "status": s.get("status", "pending"),
                    "tool_count": s.get("tool_count", 0),
                }
                for s in self.plan_steps
            ],
            version=self.plan_version,
        ))

    def _maybe_emit_progress(self) -> None:
        """Emit a throttled run_progress heartbeat (≥1s between emissions)."""
        now = time.time()
        if now - self._last_progress_ts < 1.0:
            return
        self._last_progress_ts = now
        elapsed = int((now - self._run_start_ts) * 1000) if self._run_start_ts else 0
        total = len(self.plan_steps)
        # current_step_idx is the 0-based index of the step being worked on,
        # so the 1-based display number is idx+1.
        current = min(self.current_step_idx + 1, total)
        label = f"步骤 {current}/{total}" if total else "执行中"
        self._emit(run_progress(
            current_step=current,
            total_steps=total,
            tool_count=self._total_tool_calls,
            elapsed_ms=elapsed,
            label=label,
            round_idx=getattr(self, "_round_count", 0),
        ))

    def _accumulate_usage(self, chunk: dict) -> None:
        """Add an LLM stream chunk's usage info into the per-run total.

        Phase 16 P1-D: OpenAI-compatible APIs attach usage to the final
        stream chunk. We accumulate input/output/reasoning tokens so the
        run's real token consumption can be persisted to token_usage.
        """
        usage = (chunk or {}).get("usage") or {}
        if not usage:
            return
        self._usage_total["input_tokens"] += int(usage.get("input_tokens") or 0)
        self._usage_total["output_tokens"] += int(usage.get("output_tokens") or 0)
        self._usage_total["reasoning_tokens"] += int(usage.get("reasoning_tokens") or 0)

    def _persist_token_usage(self) -> None:
        """Persist accumulated real token usage to the token_usage table.

        Called once at run finalize. Never blocks the loop.
        """
        total = sum(self._usage_total.values())
        if total <= 0:
            return
        try:
            from storage.db import get_db
            from storage.token_store import TokenStore
            store = TokenStore(get_db())
            store.record(
                project_id=self.project_id,
                agent_id=self._agent_id,
                model_id=self._model_id,
                input_tokens=self._usage_total.get("input_tokens", 0),
                output_tokens=self._usage_total.get("output_tokens", 0),
                reasoning_tokens=self._usage_total.get("reasoning_tokens", 0),
                run_id=self.run_id,
            )
            logger.info("Persisted token usage: in=%d out=%d reasoning=%d run=%s",
                        self._usage_total.get("input_tokens", 0),
                        self._usage_total.get("output_tokens", 0),
                        self._usage_total.get("reasoning_tokens", 0),
                        self.run_id[:8])
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to persist token usage: %s", e)

    def _log_event(self, event_type: str, summary: str,
                   status: str = "success", detail: str | None = None) -> None:
        """Best-effort local_logs write (PRD §3.8 最简化本地日志).

        Never blocks the agent loop — DB failures are swallowed.
        """
        try:
            from storage.db import get_db
            from storage.log_store import LogStore
            LogStore(get_db()).write(
                event_type=event_type,
                project_id=self.project_id,
                event_summary=summary,
                status=status,
                detail=detail,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write local log: %s", e)

    def _persist_tool_call(self, tool_name: str, args: dict, result_text: str,
                           tool_call_id: str = "", status: str = "completed") -> None:
        """Persist a tool call to the tool_calls table (best-effort).

        Phase 8: Records tool name, params summary, status, and result.
        Uses the real LLM tool_call_id when available so records align
        with tool_completed events. Never blocks the agent loop.
        """
        if not self.tool_call_store:
            return
        try:
            tc_id = tool_call_id or f"tc-{uuid.uuid4().hex[:12]}"
            params_summary = json.dumps(args, ensure_ascii=False)[:500]
            self.tool_call_store.create_tool_call(
                tool_call_id=tc_id,
                project_id=self.project_id,
                tool_name=tool_name,
                params_summary=params_summary,
                approval_status="auto",
                status=status,
            )
            self.tool_call_store.update_tool_call(
                tc_id,
                status=status,
                result_summary=(result_text or "")[:500],
            )
        except Exception as e:
            logger.warning("Failed to persist tool call %s: %s", tool_name, e)

    def _finalize_run(self) -> None:
        self._persist_token_usage()  # Phase 16 P1-D: real token accounting
        self._write_task_memory()    # Phase 17 P3: 工作记忆落盘（压缩后仍可找回要点）
        self._emit(run_completed())
        self._update_status(STATUS_COMPLETED, progress=100, progress_message="任务完成")

    def _write_task_memory(self) -> None:
        """Phase 17 P3: 工作记忆落盘到 workspace/.task_memory/{run_id}.json.

        记录本 run 的提示词、已用工具、最终结论要点。即使上下文被压缩，
        后续轮次/新 run 仍可 read_file 找回关键中间结论（分块读入协议的
        配套记忆层）。best-effort，失败仅记日志。
        """
        if not self.work_dir:
            return
        try:
            mem_dir = os.path.join(self.work_dir, ".task_memory")
            os.makedirs(mem_dir, exist_ok=True)
            tools_used = []
            if self.run_store:
                try:
                    # 从 run_events 取本 run 的 tool_completed 轨迹（与 run_id 强关联）
                    rows = self.run_store.db.execute(
                        "SELECT payload_json FROM run_events "
                        "WHERE run_id = ? AND event_type = 'tool_completed' "
                        "ORDER BY seq ASC LIMIT 500",
                        (self.run_id,),
                    ).fetchall()
                    for r in rows:
                        try:
                            p = json.loads(r["payload_json"] or "{}")
                        except Exception:
                            continue
                        tools_used.append({
                            "tool": p.get("name") or "",
                            "status": p.get("status") or "",
                            "result_snippet": str(p.get("output_summary") or "")[:200],
                        })
                except Exception:
                    pass
            mem = {
                "run_id": self.run_id,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "prompt": getattr(self, "_last_prompt", "")[:500],
                "tool_count": getattr(self, "_total_tool_calls", 0),
                "tools_used": tools_used,
                "steps": [
                    {"title": s.get("title", ""), "status": s.get("status", "")}
                    for s in (self.plan_steps or [])
                ],
            }
            mem_path = os.path.join(mem_dir, f"{self.run_id}.json")
            with open(mem_path, "w", encoding="utf-8") as f:
                json.dump(mem, f, ensure_ascii=False, indent=2)
            logger.info("Task memory written: %s", mem_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write task memory: %s", e)

    def _finalize_cancelled(self, reason: str = "user_cancelled") -> None:
        """Finalize a run that was cancelled mid-execution.

        Phase 8 fix: emits run_stopped and marks status so the frontend
        receives a terminal event instead of hanging forever.
        """
        self._persist_token_usage()  # Phase 16 P1-D: even partial usage counts
        self._emit(run_stopped(reason=reason))
        self._update_status(STATUS_STOPPED, progress_message="已取消")

    # ==================================================================
    # User interaction helpers
    # ==================================================================

    def _ask_user(self, question: str, input_type: str = "text",
                  options: list[str] | None = None,
                  tool_call_id: str = "",
                  progress: dict | None = None,
                  allow_skip: bool = False,
                  multi_select: bool = False,
                  answers_so_far: str = "") -> str | None:
        """Block the execution thread and wait for user response.

        Phase 7.3: Added progress, allow_skip, answers_so_far for progressive clarification.
        Emits user_input_required event and blocks on _user_response_event.
        Returns user response text, or None if cancelled.
        """
        interaction_id = f"int-{uuid.uuid4().hex[:8]}"
        tc_id = tool_call_id or f"tc-{uuid.uuid4().hex[:8]}"

        # Phase 10: Use tool_call_id as interaction_id for guaranteed consistency
        # between LLM function-calling and interaction lifecycle.
        if tool_call_id:
            interaction_id = tool_call_id

        # Persist interaction (log errors instead of silently swallowing)
        if self.run_store:
            try:
                self.run_store.create_interaction(
                    interaction_id=interaction_id,
                    run_id=self.run_id,
                    interaction_type=input_type,
                    prompt=question,
                    options=options,
                    tool_call_id=interaction_id,
                )
            except Exception as e:
                logger.error("create_interaction failed (run=%s, int=%s): %s",
                            self.run_id, interaction_id, e)

        self._update_status(STATUS_WAITING, progress_message="等待用户输入")
        self._emit(user_input_required(
            question=question,
            input_type=input_type,
            options=options,
            tool_call_id=tc_id,
            interaction_id=interaction_id,
            progress=progress,
            allow_skip=allow_skip,
            multi_select=multi_select,
            answers_so_far=answers_so_far,
        ))

        # Block until response or stop
        self._user_response_event.clear()
        self._user_response = None

        # Wait with periodic stop check
        while not self._user_response_event.is_set():
            if self.stop_event.is_set():
                # Persist cancelled interaction
                if self.run_store:
                    try:
                        self.run_store.cancel_interaction(interaction_id)
                    except Exception:
                        pass
                return None
            self._user_response_event.wait(timeout=0.5)

        response = self._user_response

        if response and response.get("cancelled"):
            if self.run_store:
                try:
                    self.run_store.cancel_interaction(interaction_id)
                except Exception:
                    pass
            return None

        user_text = (response or {}).get("response", "") if response else ""

        # Persist user response
        if self.run_store and user_text:
            try:
                self.run_store.respond_interaction(interaction_id, user_text)
            except Exception:
                pass

        self._update_status(STATUS_RUNNING)
        return user_text

    def provide_user_response(self, response: str, cancelled: bool = False) -> None:
        """Called by the API layer when the user answers an ask_user prompt."""
        self._user_response = {"response": response, "cancelled": cancelled}
        self._user_response_event.set()

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _emit(self, event: dict) -> None:
        """Emit an AgentEvent through the registered callback."""
        try:
            self.emitter(event)
        except Exception as e:
            logger.error("Event emitter error: %s", e)

    def _check_interrupt(self) -> bool:
        """Check if the run has been interrupted. Emits run_stopped if so."""
        if self.stop_event.is_set():
            self._emit(run_stopped("user_cancelled"))
            self._update_status(STATUS_STOPPED, progress_message="用户终止")
            return True
        return False

    def _update_status(self, status: str, progress: float | None = None,
                       progress_message: str | None = None,
                       error_message: str | None = None) -> None:
        if self.run_store:
            try:
                self.run_store.update_run_status(
                    self.run_id, status,
                    progress=progress,
                    progress_message=progress_message,
                    error_message=error_message,
                )
            except Exception:
                pass
        # Phase 17 fix: 同步到内存 _runs（workspace 层回调），否则
        # /api/workspace/events 与 /status 永远只看到 running。
        if self.status_callback:
            try:
                self.status_callback(status)
            except Exception:
                pass


    # ==================================================================
    # Progress & status helpers
    # ==================================================================

