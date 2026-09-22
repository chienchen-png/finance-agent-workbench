"""smol_bridge — smolagents 事件 → 24 种 AgentEvent 桥接。

阶段 1（引擎层替换）：smolagents 引擎执行时产出标准事件流
（run(stream=True) 逐 step yield），本模块将其翻译为现有前端
消费的 24 种 AgentEvent（agent/agent_events.py），使旧前端无需改动。

smolagents 流式事件类型：
- ActionStep（step_number/tool_calls/observations/model_output/is_final_answer）
- FinalAnswerStep（output）
- ChatMessageStreamDelta（文本增量——已由 FinanceModel.on_text_delta 直接透出，
  这里不重复处理）

事件映射对照（函数与变量总文档 1.4）：
- reasoning_delta  → 模型思考流式（FinanceModel.on_reasoning 透出）
- message_delta    → 正文流式（FinanceModel.on_text_delta 透出）
- tool_started     → ActionStep.tool_calls
- tool_completed   → ActionStep.observations
- run_completed    → FinalAnswerStep
- step_started/completed → 步骤轮次（当前简化：单轮）
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from agent import agent_events as ev

# 智能体优化 3.0（阶段 A2，铁律 000）：thinking 尾部缓冲窗口。
# 保留最近 N 字符延迟透出，命中预演标记时可回溯剔除标记及其前缀，
# 避免残留 "<end_plan"、"## 1. Fact" 等半截痕迹（≥最长标记长度）。
REASONING_PENDING_WIN = 40


class SmolBridge:
    """把 smolagents 事件流翻译为现有 AgentEvent。

    用法：
        bridge = SmolBridge(emit=my_emitter)
        bridge.on_reasoning_delta(text)   # FinanceModel 回调挂这里
        bridge.on_text_delta(text)
        bridge.on_step(step)              # 主循环里每个 ActionStep/FinalAnswerStep
        bridge.on_done(output)
    """

    def __init__(
        self,
        emit: Callable[[dict], None],
        step_round_label: str = "执行",
        humanize: Callable[[str, dict | None], dict] | None = None,
        summarize: Callable[[str, Any], str] | None = None,
    ):
        self.emit = emit
        self.step_round_label = step_round_label
        self.humanize = humanize  # tool_titles.humanize_tool_call
        self.summarize = summarize  # tool_titles.summarize_output
        self._step_count = 0
        self._tool_seq = 0
        self._active_tool_name = ""
        # Phase 17 P12：工具耗时（tool_id → 开始时间戳）
        self._tool_times: dict[str, float] = {}
        # Phase 17 P12.2：本轮文本缓冲——on_text_delta 不再即时 emit，
        # 先缓冲，on_step 时按步骤类型路由：
        #   工具轮 → 规划/思考文本进 reasoning（思考块）
        #   final 轮 → 最终答案进 message（正文）
        # 修复：DeepSeek 在工具调用前独立 chunk 输出的规划文本
        # （Facts survey/Plan 等）不再污染正文。
        self._text_buffer: list[str] = []
        # P13 收尾：run_completed 幂等——同一 run 只发一次（
        # is_final_answer ActionStep / FinalAnswerStep / on_done 三处
        # 都可能触发，此前会发 2-3 次）。
        self._run_completed = False
        # P13 收尾：final 正文只发一次——同一轮回答若先被解析为
        # is_final_answer ActionStep（content 文本），后又被封装成
        # FinalAnswerStep.output（同一份答案），两分支都路由会双份正文。
        # 约定：is_final_answer 分支已输出正文 → FinalAnswerStep 跳过。
        self._final_text_emitted = False
        # 智能体优化 3.0：规划阶段 thinking 预演去重——
        # DeepSeek 思考末尾会"预演"即将正式输出的计划（出现 "## 1. Facts survey"
        # 等标题），与 PlanningStep 的正式计划渲染重复。检测到标记后丢弃后续
        # thinking（仅限规划阶段；进入执行阶段（ActionStep）后恢复透出）。
        # A2-3 增强：改用「尾部缓冲」——保留最近 REASONING_PENDING_WIN 字符
        # 延迟透出，命中预演标记时可回溯剔除标记及其前缀（不再残留
        # "<end_plan"、"## 1. Fact" 这类半截痕迹）。
        self._plan_output_started = False
        self._reasoning_accum = ""
        self._reasoning_pending = ""  # 已收到但延迟透出的尾部
        self._reasoning_emitted = 0   # 已透出字符数（accum 内偏移）
        # 2026-08-20：估计总步数——smolagents 是动态规划，无法预知总步数。
        # 从首次 PlanningStep 的计划文本（编号行）解析「估计总步数」供前端
        # 显示「第 N/约M 步」；解析不到则为 0（前端显示不确定进度，不误导）。
        self._estimated_total = 0

    # ------------------------------------------------------------------
    # 文本流（FinanceModel 回调）
    # ------------------------------------------------------------------

    def on_reasoning_delta(self, text: str) -> None:
        # 智能体优化 3.0：规划阶段 thinking 预演去重。
        # DeepSeek 思考（reasoning_content）在规划阶段会先做真实推理，
        # 然后末尾"预演"即将正式输出的计划（"可以写：## 1. Facts survey..."
        # → "## 1. Facts survey\n### 1.1..."，或新版提示词下的
        # "1. 使用 xxx 工具" → "<end_plan>" 草稿）。预演部分与 PlanningStep 的
        # 正式计划渲染完全重复，这里检测到预演标记后丢弃后续 thinking。
        #
        # A2-3 尾部缓冲：把新文本先累积进 _reasoning_accum（全量检测用），
        # 同时保留最近 REASONING_PENDING_WIN 字符不立即透出。命中预演标记时，
        # 标记及其之前尚未透出的尾部全部剔除——不留半截痕迹。
        if self._plan_output_started:
            return  # 已命中预演标记，后续 thinking 为预演，丢弃
        self._reasoning_accum += text
        self._reasoning_pending += text
        # 命中预演标记（A2-3 兜底，两种格式都覆盖）：
        #   ① 正式计划标题（markdown 语法 ## 1. Facts survey / ## 2. Plan，
        #      含中英文变体，适配旧版强制结构化提示词）
        #   ② <end_plan> 标签（新版轻量提示词下模型在 thinking 里草拟
        #      计划并以 <end_plan> 收尾预演——正式输出必然含该标签，
        #      出现在 thinking 中即预演开始）
        m = re.search(
            r"(?:##\s*[12][.．、]\s*(?:Facts|Plan|事实|计划|Facts\s+survey))"
            r"|(?:<end_plan>)",
            self._reasoning_accum,
        )
        if m:
            # 只透出标记之前的真实思考（扣除已透出部分）
            cut = m.start()  # 标记起点（accum 内偏移）
            to_emit = self._reasoning_accum[self._reasoning_emitted:cut]
            if to_emit:
                self.emit(ev.reasoning_delta(to_emit))
            self._plan_output_started = True
            return
        # 未命中：把缓冲尾部中"超出保留窗口"的部分透出（窗口内延迟保留）
        win = REASONING_PENDING_WIN
        if len(self._reasoning_pending) > win:
            emit_part = self._reasoning_pending[:-win]
            self._reasoning_pending = self._reasoning_pending[-win:]
            self._reasoning_emitted += len(emit_part)
            if emit_part:
                self.emit(ev.reasoning_delta(emit_part))

    def on_reasoning_closed(self) -> None:
        # 思考收尾：把缓冲尾部的正常思考内容全部透出（防止窗口内内容丢失）
        if not self._plan_output_started and self._reasoning_pending:
            self._reasoning_emitted += len(self._reasoning_pending)
            self.emit(ev.reasoning_delta(self._reasoning_pending))
            self._reasoning_pending = ""
        self.emit(ev.reasoning_closed())

    def on_text_delta(self, text: str) -> None:
        # P12.2：缓冲，不即时 emit（路由决策在 on_step，那时才知道
        # 本轮是否工具轮 / 是否 final 轮）
        self._text_buffer.append(text)

    def _flush_text(self, to_reasoning: bool) -> None:
        """P12.2：把缓冲的轮次文本路由到思考块或正文（分块模拟流式）。

        P12.6：复用 _emit_text（带 time.sleep 真流式）。
        """
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()
        self._emit_text(text, to_reasoning)

    @staticmethod
    def _split_plan(text: str) -> tuple[str, str]:
        """P12.4：把「Facts survey / Plan 规划部分」与「最终答案」分离。

        无工具调用的纯写作任务里，模型会一次性输出
        "Facts survey + Plan + <end_plan> + 最终答案" 全文。
        smolagents 将其解析为 final_answer 调用 → 整个缓冲文本被当正文。
        这里以 <end_plan>（或 Plan 章节）为界：
          - 之前 → 规划（进思考块）
          - 之后 → 最终答案（进正文）
        返回 (plan, answer)。
        """
        if not text:
            return "", ""
        # 优先 <end_plan> 标记（smolagents planning 的标准结尾）
        marker = "<end_plan>"
        idx = text.find(marker)
        if idx >= 0:
            return text[:idx].strip(), text[idx + len(marker):].strip()
        # 兜底：## 2. Plan 章节开始处（含 Plan 标题到末尾都算规划，
        # 因为答案通常在其后由 final_answer 单独给出——这里保守处理）
        for key in ("## 2. Plan", "## 2 Plan", "2. Plan"):
            idx = text.find(key)
            if idx >= 0:
                return text[:idx].strip(), text[idx:].strip()
        return "", text.strip()

    def _emit_text(self, text: str, to_reasoning: bool) -> None:
        """分块发射文本到思考块或正文。

        P12.6：加 time.sleep 实现【真流式】——块随时间到达 DB，
        前端 400ms 轮询逐步拿到增量 → react-markdown 每次增量重渲染
        → 打字机效果（此前瞬时循环 emit，前端一次拿走整块，无流式）。
        """
        if not text:
            return
        step = 48 if to_reasoning else 16
        import time as _time
        for i in range(0, len(text), step):
            if to_reasoning:
                self.emit(ev.reasoning_delta(text[i:i + step]))
            else:
                self.emit(ev.message_delta(text[i:i + step]))
            # 真流式：每块间隔 ~40ms（约 25 块/s；配合前端 400ms 轮询
            # 每次拿到 ~10 块，视觉流畅且不明显拖慢整体速度）
            _time.sleep(0.04)

    # ------------------------------------------------------------------
    # 步骤流（run(stream=True) 的 step 事件）
    # ------------------------------------------------------------------

    def on_step(self, step: Any) -> None:
        """处理一个 smolagents 步骤（PlanningStep / ActionStep / FinalAnswerStep）。"""
        cls_name = type(step).__name__

        # 2026-08-20：PlanningStep = 首次规划 → 解析计划文本估计总步数。
        # 计划通常是编号列表（"1. xxx\n2. xxx\n3. xxx"），数编号行即可。
        # 注意：plan 是「高层步骤」，实际工具轮次可能更多——仅作「约 M 步」
        # 的软提示，前端不把它当硬性 100%。
        if cls_name == "PlanningStep":
            plan_text = str(getattr(step, "plan", "") or "")
            numbered = [
                ln for ln in plan_text.splitlines()
                if re.match(r"^\s*\d+[.、)．]", ln.strip())
            ]
            if numbered:
                self._estimated_total = len(numbered)
            # 规划步不进 step 计数、不发 step_started（否则前端多一个假步骤）
            return

        # 智能体优化 3.0：ActionStep = 执行阶段开始 → 恢复 thinking 透出
        # （规划阶段的预演截断仅在规划期生效，执行期思考正常显示）。
        # 同时 flush 尾部缓冲：正常思考若被工具轮打断，窗口内未透出内容
        # 补透出；若已命中预演标记则缓冲已废弃（_reasoning_pending 为空）。
        if cls_name == "ActionStep":
            if not self._plan_output_started and self._reasoning_pending:
                self._reasoning_emitted += len(self._reasoning_pending)
                self.emit(ev.reasoning_delta(self._reasoning_pending))
            self._reasoning_pending = ""
            self._plan_output_started = False
            self._reasoning_accum = ""

        if cls_name == "FinalAnswerStep":
            # P12.2：残余文本（防御）→ 思考；最终答案用 step.output（精炼版）
            # P12.4：output 可能含规划部分 → 分离后分别路由
            self._flush_text(to_reasoning=True)
            output = str(getattr(step, "output", "") or "")
            plan, answer = self._split_plan(output)
            # P13：若同一轮回答已由 is_final_answer 分支输出过正文，
            # 跳过（防双份）；否则规划进思考块、答案进正文
            if not self._final_text_emitted:
                self._emit_text(plan, to_reasoning=True)
                # 最终答案作为正文流式输出（分块模拟流式）
                self._emit_text(answer, to_reasoning=False)
            self._emit_completed()
            return

        # Phase 17 P12：ActionStep 且 is_final_answer → 答案直接作为正文，
        # 不再解析为 final_answer 工具调用（修复 final-answer 工具卡问题）。
        # P12.2：正文优先取缓冲文本（模型 content 流式增量）；
        # 缓冲为空时回退 model_output（防御：纯文本轮无增量透出时兜底）。
        # P12.4：缓冲含 Facts survey/Plan → 规划进思考块，答案进正文。
        if getattr(step, "is_final_answer", False):
            # G6 审计修复：优先取 final_answer 工具的 answer 参数（模型明确
            # 提交的最终答案）。此前优先 _text_buffer，但模型在 final_answer 轮
            # 常先流式输出过渡句（如 "Let me write the final report"），
            # 导致完整报告被丢弃、只显示过渡句。
            final_answer_text = self._extract_final_answer(step)
            if final_answer_text:
                self._text_buffer.clear()
                plan, answer = self._split_plan(final_answer_text)
                self._emit_text(plan, to_reasoning=True)
                if answer:
                    self._emit_text(answer, to_reasoning=False)
                    self._final_text_emitted = True
                self._emit_completed()
                return
            if self._text_buffer:
                buffered = "".join(self._text_buffer)
                self._text_buffer.clear()
                # 2026-08-23：兜底清洗——缓冲可能是原始 "Calling tools:" 文本
                # （文本式工具调用），剥离包装 + 字面 \n 还原，避免原始 JSON 进正文
                cleaned = self._strip_tool_call_wrapper(buffered)
                plan, answer = self._split_plan(cleaned)
                self._emit_text(plan, to_reasoning=True)
                if answer:
                    self._emit_text(answer, to_reasoning=False)
                    self._final_text_emitted = True
            else:
                output = str(getattr(step, "model_output", "") or "")
                if output:
                    cleaned = self._strip_tool_call_wrapper(output)
                    plan, answer = self._split_plan(cleaned)
                    self._emit_text(plan, to_reasoning=True)
                    if answer:
                        self._emit_text(answer, to_reasoning=False)
                        self._final_text_emitted = True
            self._emit_completed()
            return

        # ActionStep 工具轮
        tcs = getattr(step, "tool_calls", None)
        tool_ids: list[str] = []
        if tcs:
            # P12.2：工具轮文本（模型在调用工具前输出的规划/思考）→ 思考块
            self._flush_text(to_reasoning=True)
            for tc in tcs:
                tool_name = getattr(tc, "name", "")
                # Phase 17 P12：过滤内置 final_answer 工具（防御性，
                # 不依赖 is_final_answer，避免纯文本输出被解析成工具卡）
                if tool_name == "final_answer":
                    continue
                self._tool_seq += 1
                args = tc.arguments or {}
                tool_id = f"smol-{self._tool_seq}"
                tool_ids.append(tool_id)
                self._active_tool_name = tool_name  # 供 tool_completed 使用

                # 人类可读标题（复用 tool_titles）
                title, icon, category = self._tool_meta(tool_name, args)
                # 记录工具开始时间（耗时计算）
                import time as _time
                self._tool_times[tool_id] = _time.perf_counter()
                self.emit(ev.tool_started(
                    tool_id=tool_id, name=tool_name,
                    input_summary=self._fmt_args(args),
                    title=title, icon=icon, category=category,
                    step_id=str(self._step_count),
                ))

        obs = getattr(step, "observations", None)
        if obs and tool_ids:
            # smolagents ActionStep.observations 是 str | None（非 list）！
            # 直接 for 遍历会把 JSON 字符串按【字符】拆开发射 tool_completed。
            # 修复：统一转为单元素列表。
            if isinstance(obs, str):
                obs = [obs]
            # G6 审计修复：tool_completed 数量对齐 tool_call 数量。
            # 此前只发一个 completed（用最后一个 tool_seq/active_tool_name），
            # 并行多工具调用时前端工具卡显示错乱。observations 是拼接串无法
            # 精确拆分，此处按工具数补齐 completed（内容取拼接全文的摘要）。
            all_text = "\n".join(o if isinstance(o, str) else str(o) for o in obs)
            n_done = len(tool_ids)
            for i in range(n_done):
                tool_id = tool_ids[i]
                import time as _time
                start = self._tool_times.pop(tool_id, None)
                duration_ms = round((_time.perf_counter() - start) * 1000, 1) \
                    if start is not None else 0.0
                # 2026-08-20：reconcile_variables 输出完整 JSON（差异表数据源）——
                # 提高截断上限至 15000（与工具 forward 的 [:15000] 对齐），
                # 避免 JSON 被截断导致前端无法解析差异明细。
                cap = 15000 if self._active_tool_name == "reconcile_variables" else 3000
                self.emit(ev.tool_completed(
                    tool_id=tool_id,
                    name=self._active_tool_name or "tool",
                    output=all_text[:cap],
                    status="completed",
                    duration_ms=duration_ms,
                    output_summary=self._summarize(all_text),
                    step_id=str(self._step_count),
                ))
        elif obs:
            if isinstance(obs, str):
                obs = [obs]
            for o in obs:
                text = o if isinstance(o, str) else str(o)
                tool_id = f"smol-{self._tool_seq}"
                import time as _time
                start = self._tool_times.pop(tool_id, None)
                duration_ms = round((_time.perf_counter() - start) * 1000, 1) \
                    if start is not None else 0.0
                # 同上：reconcile_variables 完整输出（差异表数据源）
                cap = 15000 if self._active_tool_name == "reconcile_variables" else 3000
                self.emit(ev.tool_completed(
                    tool_id=tool_id,
                    name=self._active_tool_name or "tool",
                    output=str(text)[:cap],
                    status="completed",
                    duration_ms=duration_ms,
                    output_summary=self._summarize(text),
                    step_id=str(self._step_count),
                ))
        else:
            # P12.2：无工具调用的普通 ActionStep（防御，正常不会出现）——
            # 若模型在无工具轮输出了文本，视为思考过程而非正文
            self._flush_text(to_reasoning=True)

        # 步骤完成（当前简化：每步一个 step 事件）
        self._step_count += 1
        self.emit(ev.step_started(
            step_id=str(self._step_count - 1),
            title=self.step_round_label,
            index=self._step_count,
            # 2026-08-20：不再用当前步数当 total（造成「第 N/N 步」假象）。
            # smolagents 动态规划无法预知总步数：有计划解析出估计值就用「约 M」，
            # 否则 total=0 → 前端显示不确定进度（不误导「还剩几步」）。
            total=self._estimated_total,
        ))
        self.emit(ev.step_completed(
            step_id=str(self._step_count - 1),
            success=True,
            summary=self.step_round_label,
        ))

    # ------------------------------------------------------------------
    # 收尾
    # ------------------------------------------------------------------

    def _extract_final_answer(self, step: Any) -> str:
        """从 step 的模型输出中提取 final_answer 的 answer 参数。

        G6 审计修复：模型在 final_answer 轮常先流式输出过渡句（如
        "Let me write the final report"），完整报告在 final_answer 工具参数里。
        此前 bridge 优先用流式缓冲文本，导致报告被丢弃只显示过渡句。
        这里优先取 final_answer 工具参数作为最终答案。

        2026-08-23 修复（文本式工具调用 markdown 不渲染）：
        smolagents 的 ActionStep.model_output 是【content 字符串】
        （smolagents/memory.py: model_output: str | list | None），tool_calls
        在 model_output_message（ChatMessage）里。此前访问
        step.model_output.tool_calls 永远为空 → 回退 _text_buffer 把原始
        "Calling tools:\\n[...]" 文本当正文（字面 \\n 无法触发 markdown 解析）。
        现在按序尝试：
          ① model_output_message.tool_calls（标准/文本式解析后的结构化调用）
          ② model_output（可能是 dict 结构，或字符串 → 文本式工具调用解析）
        """
        try:
            # ① model_output_message：ChatMessage 对象（含 tool_calls）
            mo = getattr(step, "model_output_message", None)
            if mo is not None:
                ans = self._answer_from_tool_calls(getattr(mo, "tool_calls", None))
                if ans:
                    return ans
            # ② model_output：字符串（content）或 dict
            mo2 = getattr(step, "model_output", None)
            if isinstance(mo2, dict):
                ans = self._answer_from_tool_calls(mo2.get("tool_calls"))
                if ans:
                    return ans
            elif isinstance(mo2, str) and mo2.strip():
                ans = self._answer_from_text(mo2)
                if ans:
                    return ans
        except Exception:  # noqa: BLE001
            pass
        return ""

    @staticmethod
    def _answer_from_tool_calls(tcs) -> str:
        """从 tool_calls 列表提取 final_answer 的 answer 参数（结构化路径）。"""
        if not tcs:
            return ""
        for tc in tcs:
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", "") if fn is not None else getattr(tc, "name", "")
            if name != "final_answer":
                continue
            args = getattr(fn, "arguments", None) if fn is not None else getattr(tc, "arguments", None)
            if isinstance(args, str):
                try:
                    import json as _json
                    args = _json.loads(args)
                except Exception:  # noqa: BLE001
                    return args.strip()
            if isinstance(args, dict):
                ans = args.get("answer")
                if ans is None:
                    ans = args.get("final_answer")
                return str(ans).strip() if ans else ""
            return str(args or "").strip()
        return ""

    @staticmethod
    def _answer_from_text(text: str) -> str:
        """从模型原始文本式工具调用（"Calling tools:\\n[{...}]"）解析 final_answer answer。

        文本式调用路径（模型把工具调用写在 content 里）：smolagents 解析出的
        arguments 是真实 dict，但模型输出的原始文本里换行以字面 '\\n' 转义
        形式存在（模型按 JSON 转义输出）。这里提取顶层块并做单引号→双引号
        容错后 json.loads，把字面 '\\n' 还原为真实换行。
        """
        if not text or "final_answer" not in text:
            return ""
        try:
            import json as _json
            from agent.smol_model import _extract_top_block, _py_dict_to_json
            fixed = _py_dict_to_json(text)
            blob = _extract_top_block(fixed)
            data = _json.loads(blob, strict=False)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                fn = item.get("function") if isinstance(item.get("function"), dict) else item
                name = fn.get("name") or item.get("name") or ""
                if name != "final_answer":
                    continue
                args = fn.get("arguments", item.get("arguments", {}))
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except Exception:  # noqa: BLE001
                        args = {"answer": args}
                if isinstance(args, dict):
                    ans = args.get("answer") or args.get("final_answer")
                    if ans:
                        return str(ans).strip()
                return str(args or "").strip()
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _strip_tool_call_wrapper(self, text: str) -> str:
        """兜底清洗：剥离文本式工具调用包装，字面 \\n 还原为真实换行。

        防御层：_extract_final_answer 失效时，确保原始 "Calling tools:"
        JSON 不会进入正文。
        """
        if not text:
            return text
        # ① 若整体是 final_answer 文本式调用 → 提取 answer
        ans = self._answer_from_text(text)
        if ans:
            return ans
        # ② 剥离 "Calling tools:" 前缀
        idx = text.find("Calling tools:")
        if idx >= 0:
            text = text[idx + len("Calling tools:"):].lstrip()
        # ③ 字面 \n / \t → 真实换行/制表（模型按 JSON 转义输出时的残留）
        text = text.replace("\\n", "\n").replace("\\t", "\t")
        return text.strip()

    def _emit_completed(self) -> None:
        """P13：run_completed 幂等——多个收尾路径只发一次。"""
        if self._run_completed:
            return
        self._run_completed = True
        self.emit(ev.run_completed())

    def on_done(self) -> None:
        self._emit_completed()

    def on_error(self, message: str) -> None:
        self.emit(ev.run_failed(message[:300]))

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _tool_meta(self, name: str, args: dict) -> tuple[str, str, str]:
        """复用 tool_titles.humanize_tool_call 提取 title/icon/category。"""
        if self.humanize:
            try:
                meta = self.humanize(name, args)
                return (meta.get("title", name), meta.get("icon", "🔧"),
                        meta.get("category", "工具"))
            except Exception:
                pass
        return name, "🔧", "工具"

    def _fmt_args(self, args: dict) -> str:
        try:
            s = json.dumps(args, ensure_ascii=False)
            return s if len(s) <= 200 else s[:200] + "..."
        except Exception:
            return str(args)[:200]

    def _summarize(self, result_text: str) -> str:
        if self.summarize:
            try:
                return self.summarize("", result_text)[:120]
            except Exception:
                pass
        return result_text[:120]
