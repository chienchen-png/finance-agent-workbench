"""smol_engine — SmolAgentEngine：smolagents 引擎封装。

阶段 1（引擎层替换）：提供与 AgentCore.execute() 兼容的接口，
供 routes/workspace.py 的 engine=smol 分支调用。整合：
- FinanceModel（复用 LLMClient）
- build_smol_tools（28 工具）
- SmolBridge（事件翻译 → 24 种 AgentEvent）
- ToolCallingAgent（smolagents ReAct 循环）
- 审批钩子（approval.py 复用）

设计约束：
1. execute() 签名对齐 AgentCore（run_id/prompt/agent_id/model_id/context_files）
2. 事件通过 emitter 发射（与 legacy 相同契约）
3. 工具执行前做审批检查（复用 ApprovalManager）
4. 文本/思考流式通过 FinanceModel 回调 → bridge → emitter
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable

from agent.approval import ApprovalRouter, TOOL_METADATA
from agent.approval.workspace_boundary import path_escapes_workspace
from agent.llm_client import LLMClient
from agent.smol_bridge import SmolBridge
from agent.smol_model import FinanceModel
from agent.smol_tools import build_smol_tools
from agent.tool_titles import humanize_tool_call, summarize_output

from smolagents import ToolCallingAgent
from smolagents.agents import (
    FinalAnswerPromptTemplate,
    ManagedAgentPromptTemplate,
    PlanningPromptTemplate,
    PromptTemplates,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# P13 方案 1：财务专家角色 + 轻量 planning 的自定义提示词模板
# （替代 smolagents 默认 toolcalling_agent.yaml 的 system_prompt
#   与 planning.initial_plan —— 后者强制 "thorough reasoning"，
#   是思考过程冗长、重复的根源）
# ─────────────────────────────────────────────────────────────
FINANCE_PROMPT_TEMPLATES = PromptTemplates(
    system_prompt=(
        "你是一名资深的财务数据核对专家（Finance Agent Workbench）。\n"
        "你会使用工具调用完成财务数据核对、查询、修改与写回任务。\n"
        "思考时请使用英文，并以 'We need...' 开头，直接进入行动规划，"
        "不要复述用户的任务内容。最终答案必须用中文输出。\n"
        "规则：\n"
        "1. 仅在需要外部信息/数据时才调用工具，不要为了调用而调用。\n"
        "2. 调用工具时使用正确的参数（值，而非变量名）。\n"
        "3. 不要重复执行已做过且参数相同的工具调用。\n"
        "4. 对于简单任务（问候、常识问答、无数据处理需求），"
        "直接使用 final_answer 工具返回答案，无需输出规划。\n"
        "5. 完成任务后必须调用 final_answer 工具提交最终答案，"
        "这是完成任务并结束对话的唯一方式；不要在思考中起草完整答案，"
        "直接在 final_answer 工具的参数中给出最终答案。\n"
        "6. Excel 数据必须走数据库：用户通过 @file: 或路径提及 Excel 数据文件（.xls/.xlsx）时，"
        "先 import_excel_to_db 导入项目数据库（若尚未导入），之后所有查询/统计/跨表核对必须用 "
        "query_table / table_stats / join_tables 等数据库工具；"
        "禁止用 run_command 编写 Python 脚本读取 Excel（仅当导入工具失败时才允许用 read_excel 应急读取）。\n"
        "   但【文件系统类操作】优先用 run_command 一次完成，禁止为简单文件操作编写临时脚本："
        "列目录/查文件属性/批量复制移动/跨目录搜索/项目外文件访问/环境探查等，"
        "一条命令即可（如 dir /b、findstr /s /i、copy、where python）。"
        "仅当逻辑复杂到命令无法表达时才允许编写临时脚本（且脚本须放在项目工作目录内）。\n"
        "7. 最终答案必须是规范的中文核对报告（含核对结论、差异明细、原因分类、"
        "修改方案）；严禁在最终答案中输出工具调用结构文本"
        "（如 \"Calling tools:\" 或函数调用 JSON 片段）。\n"
        "8. 高效查询：能用一次 query_table / table_stats（group_by 聚合）"
        "批量拿到数据的，不要逐人/逐项多次重复查询；先看数据结构再决定最小查询集，"
        "避免不必要的工具调用轮次（步骤上限有限，每轮都要花在刀刃上）。\n"
        "9. 核对流程遵循「聚焦变量、先总后分」：先识别用户要核对的变量" 
        "（如「销售回款提成金额」）在两表的对应列，"
        "用 table_stats 按匹配键（如销售人员/合同编号）对【该变量】做聚合对比，"
        "定位差异点后再对差异项做 query_table 下钻明细；"
        "只查目标变量列和必要分组列，禁止全量拉取无关数据，"
        "禁止逐人/逐单重复查询无差异数据。\n"
        "10. 数据收集完成后必须立即调用 final_answer 输出完整的中文核对报告"
        "（含核对结论、差异明细、原因分类、修改填充方案）；"
        "禁止在收集完数据后继续做无意义查询或反复确认，直接进入收尾。\n"
        "    ⚠ 例外（financial-modeling skill）：若已按 financial-modeling skill 流程执行"
        "（read_skill financial-modeling 后），「步骤 3 主题多选确认」「步骤 5 复杂度分级 L1/L2/L3"
        "与配色方案确认」是 skill 规定的【必问步骤】，必须用 ask_user 弹窗询问用户，"
        "禁止因效率考虑跳过；此类 ask_user 交互不计入工具调用次数限制，"
        "用户确认后再执行分析与图表生成。\n"
        "11. 【思考节俭，核心规则】思考要短、直接、推进，禁止原地打转：\n"
        "    - 不要复述任务、不要自我对话、不要反复揣测『用户到底想要什么』；\n"
        "    - 不要探索与任务无关的路径（数据库文件存储位置、配置文件、内部实现细节）；\n"
        "    - 想清楚『下一步该调用哪个工具、传什么参数』就直接调用，一次只推进一个必要步骤；\n"
        "    - 不确定时先看该工具的 description，按描述执行，而不是反复推理猜测；\n"
        "    - 思考通常 1-3 句即可，把精力花在正确的工具调用上，而非长篇推理。\n"
        "12. 【单变量核对标准做法，务必照做】核对某个金额变量（如「销售回款提成金额」）"
        "在两表是否一致时，必须用 reconcile_variables 一次完成"
        "（match_keys 匹配键层级 + amount_col 金额列映射 + tolerance 容差），"
        "工具内部自动完成匹配+分级（A1/A2/B/C/OK），返回 summary 和差异明细（含 reason）。\n"
        "    - 禁止手工用 query_table/table_stats 逐表比对金额"
        "（仅当 reconcile_variables 调用失败才降级：各用 1 次 table_stats 聚合对比，"
        "只对差异项 query_table 下钻）；\n"
        "    - 禁止在 reconcile 后再下钻查差异明细——summary 已含全部信息，直接基于它输出报告；\n"
        "    - 全程工具调用 ≤ 6 次，完成后立即 final_answer 输出报告；"
        "严禁逐人/逐单重复查询全量数据。\n"
        "13. 【命令行使用矩阵，任务合适时优先】run_command 是文件系统/批量的首选工具：\n"
        "    - 用 run_command：列目录（dir）、查文件（findstr /s /i 关键词）、批量复制/移动（copy/move）、"
        "      文件属性（大小/时间/行数）、环境探查（where python）、项目外文件访问（C:\\ 等绝对路径）；\n"
        "    - 禁止用 run_command：读取 Excel 数据（必须导入数据库后用 query_table 等）、两表金额核对"
        "      （必须用 reconcile_variables）、修改数据（必须用 update_rows + export_project_data）；\n"
        "    - 人工审批模式下每次 run_command 都会弹窗请求确认（沙箱外能力），按确认后继续。\n"
        "Now Begin!\n"
        # 智能体优化 3.0（阶段 C 修复）：注入工具清单 + 自定义指令。
        # 此前自定义 system_prompt 缺 {{tools}} 注入块 → smolagents 从不在
        # 提示词里列出可用工具 → 模型不知道 list_data_files/get_table_index
        # 等新工具存在（表现为"查询数据库文件"时乱逛目录/猜测）。
        "你只可以使用以下工具（调用格式见上方说明）：\n"
        "{%- for tool in tools.values() %}\n"
        "- {{ tool.to_tool_calling_prompt() }}\n"
        "{%- endfor %}\n"
        "{%- if custom_instructions %}\n"
        "{{custom_instructions}}\n"
        "{%- endif %}"
    ),
    planning=PlanningPromptTemplate(
        initial_plan=(
            "你是一名资深的财务数据核对专家。下面是你需要解决的任务：\n"
            "```\n"
            "{{task}}\n"
            "```\n"
            "本阶段为规划阶段：请制定一个简洁的高层计划（1-3 步），"
            "写完最后一步后写 '<end_plan>' 标签结束规划阶段；"
            "执行阶段将按计划实际调用工具（文件系统/Excel/项目数据库查询统计/"
            "跨表连接/数据修改与写回等）完成任务。\n"
            "规划要求：\n"
            "1. 直接列出步骤，不解释、不复述任务原文、不写背景；\n"
            "2. 思考时不要预演/草拟你将输出的计划内容——想清楚直接输出最终计划；\n"
            "3. 计划必须克制：能 1 步完成的不要写 3 步，每步只写『做什么』不写『怎么做细节』。\n"
            "（核对类任务优先走项目数据库：import_excel_to_db 导入 → "
            "query_table/table_stats/join_tables 查询核对。）\n"
            "写完计划最后一步后写 '<end_plan>' 标签并停止。"
        ),
        # P17 死循环修复：此前留空导致 planning 更新时模型在空提示下
        # 反复复读规划模板、不输出工具调用 → 步骤空转死循环。
        # 现在补齐指引：明确要求更新计划后立即继续执行工具。
        update_plan_pre_messages=(
            "你已经完成了一部分工作，现在需要更新执行计划。\n"
            "请只输出简短的下一步计划（2-3 行），不要复述已完成内容，"
            "不要输出 Facts survey，不要长篇思考。\n"
            "写完计划最后一行后写 '<end_plan>' 标签结束规划更新，"
            "然后立即继续调用工具执行下一步。"
        ),
        update_plan_post_messages=(
            "任务：{{task}}\n剩余步骤：{{remaining_steps}}\n"
            "记住：规划更新不是终点，写 '<end_plan>' 后必须继续调用工具"
            "（query_table/table_stats/join_tables 等）完成任务，"
            "数据收集完毕立即用 final_answer 输出中文核对报告。"
        ),
    ),
    managed_agent=ManagedAgentPromptTemplate(task="", report=""),  # 保留空
    final_answer=FinalAnswerPromptTemplate(pre_messages="", post_messages=""),  # 保留空
)

# ─────────────────────────────────────────────────────────────
# P13 方案 2：简单任务判定（问候/寒暄 → 跳过 planning step）
# 智能体优化 3.0（阶段 A2，铁律 000）：任务难易分级 → 决定是否规划
#   简单任务（问候 / 纯交互提问 / 常识问答）→ planning_interval=None，无规划阶段
#   复杂任务（涉及文件/Excel/数据库/项目操作）→ 保留规划
# ─────────────────────────────────────────────────────────────
SIMPLE_TASK_PATTERN = re.compile(
    r"^(你好|hi|hello|谢谢|感谢|再见|拜拜|你是谁|你能做什么|"
    r"你叫什么|在吗|在不在|早上好|下午好|晚上好)\s*[!！。.？?]*$",
    re.IGNORECASE,
)

# 复杂任务触发词：命中任一 → 判定为复杂任务（保留规划）。
# 覆盖：数据文件/Excel、导入导出、核对/查询/统计、数据库、项目数据操作。
# 注：常规问候/常识问答/纯交互提问不含这些词 → 自然判为简单。
COMPLEX_TASK_PATTERN = re.compile(
    r"@file:|\.xls[x]?|\.csv|导入|导出|上传|下载|文件|目录|"
    r"核对|对账|对不上|差异|比对|分级|查询|统计|数据库|"
    r"join|连接|合并|汇总|金额|变量|指标|容差|匹配|填充|修正|"
    r"回写|更新|修改|删除|插入|报表|销售|客户|合同|提成|回款|"
    r"项目数据|数据表|工作表|sheet|列|字段|行数|导入到数据库|"
    r"分析|计算|求和|平均|环比|同比|差异率|总计",
    re.IGNORECASE,
)


def _is_simple_task(prompt: str) -> bool:
    """任务难易分级（铁律 000）→ 决定是否跳过 planning。

    简单任务：问候/寒暄（原有）+ 纯交互提问（ask_user）+ 常识问答
    （不含文件/数据/项目操作相关触发词）。
    复杂任务：命中 COMPLEX_TASK_PATTERN 任一触发词。
    """
    text = prompt.strip()
    # ① 问候/寒暄（原有）
    if SIMPLE_TASK_PATTERN.match(text):
        return True
    # ② 纯交互提问：明确要求使用 ask_user 提问/确认，且不涉及数据文件操作
    if "ask_user" in text and not COMPLEX_TASK_PATTERN.search(text):
        return True
    # ③ 常识问答：不涉及任何文件/数据/项目操作 → 简单
    if not COMPLEX_TASK_PATTERN.search(text):
        return True
    # 其余（命中复杂触发词）→ 复杂任务，保留规划
    return False


def classify_task_mode(prompt: str) -> str:
    """返回任务模式："simple"（无规划）或 "complex"（含规划）。
    供 run_created 事件透出到前端（任务模式指示器，A2-4）。"""
    return "simple" if _is_simple_task(prompt) else "complex"


class SmolAgentEngine:
    """smolagents 引擎封装（与 AgentCore 接口对齐）。"""

    def __init__(
        self,
        llm_client: LLMClient,
        emitter: Callable[[dict], None],
        stop_event: threading.Event | None = None,
        work_dir: str = "",
        project_id: str = "",
        model_id: str = "",
        max_steps: int = 12,
        # P17 死循环修复：planning_interval 置 None → 只保留 step 1 首次规划，
        # 后续步骤永不触发空模板的规划更新（此前 8 → 第 9/17/25/33/41 步
        # 反复触发 planning 更新 → 模型复读规划不调工具 → 步骤空转）。
        planning_interval: int | None = None,
        # 阶段 G：工作模式（manual=人工审批 / auto=全自动），驱动审批路由与沙箱
        work_mode: str = "manual",
        thinking: bool = True,
        clear_thinking: bool = True,
        reasoning_effort: str = "medium",
        run_store: Any = None,  # RunStore（阶段 7.7 补：run 持久化）
        conversation_id: str = "",  # P17：关联对话（前端历史显示完整 user prompt）
        user_message_id: str = "",  # P17：关联用户消息（前端历史显示完整 user prompt）
    ):
        self.llm_client = llm_client
        self.emitter = emitter
        self.stop_event = stop_event or threading.Event()
        self.work_dir = work_dir
        self.project_id = project_id
        self.model_id = model_id
        self.max_steps = max_steps
        self.planning_interval = planning_interval
        self.work_mode = work_mode
        # 阶段 G：审批路由引擎（微服务化模块 agent/approval/）
        # manual=人工审批（沙箱外/数据修改/命令行必确认）；auto=全自动（除黑名单外放行）
        self.approval = ApprovalRouter(work_mode=work_mode)
        # 全自动模式下文件工具解除沙箱（allow_outside=True → _resolve_path 跳过边界检查）
        self.allow_outside = (work_mode == "auto")
        self.thinking = thinking
        self.clear_thinking = clear_thinking
        self.reasoning_effort = reasoning_effort
        self.run_store = run_store
        self.conversation_id = conversation_id  # P17
        self.user_message_id = user_message_id  # P17

        # 阶段 7.7 补：上下文消息收集（供 _sync_context_to_db 持久化）
        self.messages: list[dict] = []
        self.ctx = None  # 兼容占位（_sync_context_to_db 等引用 core.ctx）
        self._agent: ToolCallingAgent | None = None

        # 智能体优化 3.0（阶段 A1）：用户交互阻塞状态
        # 对齐 legacy core.py:256 的实现——_ask_user 阻塞等待 provide_user_response
        self._user_response_event = threading.Event()
        self._user_response: dict | None = None
        self._user_interaction_id: str = ""

        # G6 审计修复：并行工具调用串行锁。
        # smolagents 在模型一次输出多个 tool_calls 时用 ThreadPoolExecutor +
        # copy_context() 并行执行 → 所有线程共享同一 SQLite 连接（g.db）→
        # 并发 execute 抛 sqlite3 错误 → as_completed 中断 → 只剩第一个工具结果。
        # 此锁强制工具排队串行执行（等价 max_tool_threads=1 的确定性，且不丢结果）。
        self._tool_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 执行入口（对齐 AgentCore.execute）
    # ------------------------------------------------------------------

    def execute(self, run_id: str, prompt: str, agent_id: str, model_id: str,
                context_files: list | None = None) -> None:
        """执行一次任务（阻塞直到完成或停止）。"""
        from agent.agent_events import reasoning_closed, run_failed, run_created

        # 阶段 7.7 补：持久化 run 记录（此前 smol 模式 history/上下文全丢）
        # P17：关联 conversation_id / user_message_id，前端历史才能显示
        # 完整 user prompt（此前为空 → 回退 run.title 80 字截断 → 变量名丢失）
        if self.run_store:
            try:
                self.run_store.create_run(
                    run_id=run_id,
                    project_id=self.project_id,
                    conversation_id=self.conversation_id,
                    user_message_id=self.user_message_id,
                    agent_id=agent_id,
                    model_id=model_id,
                    title=prompt[:80],
                )
            except Exception as e:
                logger.warning("Failed to persist smol run: %s", e)

        # 收集上下文消息（user 提示 + 最终答案）
        self.messages = [{"role": "user", "content": prompt}]
        # 智能体优化 3.0（阶段 A1）：设置 run_id 供 ask_user 持久化 interaction
        self.run_id = run_id

        self.emitter(run_created(
            run_id=run_id, agent=agent_id, model=model_id,
            context_file_count=len(context_files or []), title=prompt[:50],
            # 智能体优化 3.0（阶段 A2，铁律 000）：任务模式透出前端
            task_mode=classify_task_mode(prompt),
        ))

        # 事件桥接
        bridge = SmolBridge(
            emit=self.emitter,
            humanize=humanize_tool_call,
            summarize=summarize_output,
        )

        # 模型适配器（流式回调 → bridge）
        model = FinanceModel(
            llm=self.llm_client,
            model_id=model_id or self.llm_client.model,
            thinking=self.thinking,
            clear_thinking=self.clear_thinking,
            reasoning_effort=self.reasoning_effort,
            on_text_delta=bridge.on_text_delta,
            on_reasoning=bridge.on_reasoning_delta,
        )

        # 工具（审批包装）
        # 智能体优化 3.0（阶段 A1）：注入 AskUserTool（绑定 engine，供阻塞提问）
        from agent.ask_user_tool import AskUserTool
        # 阶段 G：全自动模式注入 allow_outside=True → 文件工具可访问沙箱外
        smol_tools = build_smol_tools(
            work_dir=self.work_dir, project_id=self.project_id,
            allow_outside=self.allow_outside)
        smol_tools.append(AskUserTool(
            engine=self, work_dir=self.work_dir, project_id=self.project_id))
        tools = self._wrap_tools_for_approval(smol_tools, bridge)

        # 数据平面摘要注入（复用 AgentCore._build_project_data_summary 逻辑）
        # 关键：让模型用 query_table 而不是 read_excel 读已导入的数据
        instructions = self._build_project_data_instructions(prompt)

        # 智能体优化 3.0（阶段 B3）：L0 注入 agent.md + skill 索引。
        # agent.md（角色/工具原则/skill 清单）常驻；SKILL.md 正文按需 read_skill 读。
        # 剥离 frontmatter（--- 包裹的元数据），只注入正文。
        try:
            from agent.skill_loader import (build_skill_index, read_agent_md,
                                            validate_agent_tools)
            agent_md = read_agent_md()
            if agent_md:
                import re as _re
                agent_md = _re.sub(
                    r"^---\s*\n.*?\n---\s*\n?", "", agent_md, count=1, flags=_re.DOTALL
                ).strip()
            skill_index = build_skill_index()
            l0_parts = []
            if agent_md:
                l0_parts.append(agent_md)
            if skill_index:
                l0_parts.append(skill_index)
            if instructions:
                l0_parts.append(instructions)
            if l0_parts:
                instructions = "\n\n".join(l0_parts)

            # 铁律 0：agent.md tools 白名单 vs 已注册工具（能力描述校验，不影响调用）
            from agent.smol_tools import TOOL_CLASSES as _TOOL_CLASSES
            missing = validate_agent_tools(
                None, [t.name for t in _TOOL_CLASSES]
            )
            if missing:
                logger.warning(
                    "agent.md tools 白名单未覆盖（L0 描述遗漏，工具仍可调用）: %s",
                    ", ".join(missing),
                )
        except Exception as _e:  # noqa: BLE001
            logger.warning("L0 agent.md/skill 索引注入失败: %s", _e)

        # P13 方案 2：简单任务（问候/寒暄）跳过 planning step →
        # 不再输出 Facts survey，思考只剩英文 reasoning + 直接 final_answer
        # P17 死循环修复：非简单任务 planning_interval 用超大值（max_steps+1），
        # 使 smolagents 仅在 step 1 触发「首次规划」（有完整 initial_plan 模板），
        # 后续步骤 (step-1) % interval 永不为 0 → 永不触发空模板的规划更新。
        if _is_simple_task(prompt):
            use_planning = None
        else:
            use_planning = self.max_steps + 1  # 只保留 step1 首次规划

        # 引擎
        self._agent = ToolCallingAgent(
            tools=tools,
            model=model,
            prompt_templates=FINANCE_PROMPT_TEMPLATES,  # P13 方案 1：财务专家 + 轻量 planning
            max_steps=self.max_steps,
            planning_interval=use_planning,  # P17：非简单任务只跑首次规划
            stream_outputs=True,
            verbosity_level=0,
            max_tool_threads=1,  # 串行：审批/日志确定性
            instructions=instructions,
        )

        try:
            step_iter = self._agent.run(prompt, stream=True)
            for step in step_iter:
                if self.stop_event.is_set():
                    break
                # 只消费结构化步骤（文本流已由回调透出）
                if type(step).__name__ in ("ActionStep", "FinalAnswerStep"):
                    bridge.on_step(step)
            bridge.on_done()
        except Exception as e:  # noqa: BLE001
            bridge.on_error(f"{type(e).__name__}: {e}")
            self.emitter(run_failed(str(e)[:300]))
        finally:
            self.emitter(reasoning_closed())

    # ------------------------------------------------------------------
    # 用户交互（智能体优化 3.0 阶段 A1：对齐 AgentCore._ask_user）
    # ------------------------------------------------------------------

    def ask_user(self, question: str, input_type: str = "text",
                 options: list[str] | None = None,
                 multi_select: bool = False,
                 allow_skip: bool = False) -> str | None:
        """阻塞执行线程等待用户响应（AskUserTool.forward 调用）。

        对齐 legacy core.py:1505 的实现：
        1. 生成 interaction_id 并持久化 interaction（若 run_store 可用）
        2. 发射 user_input_required 事件（前端 AskUserDialog 弹出）
        3. 阻塞等待 provide_user_response 唤醒（或 stop 中断）
        4. 返回用户答案文本；取消/中断返回 None

        智能体优化 3.0（内联弹窗增强）：
        - multi_select=True：前端 select 支持多选（逗号分隔返回）
        - allow_skip=True：前端显示"跳过"按钮
        """
        from uuid import uuid4
        from agent.agent_events import user_input_required

        interaction_id = f"int-{uuid4().hex[:8]}"
        self._user_interaction_id = interaction_id

        # 持久化 interaction（best-effort）
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
            except Exception as e:  # noqa: BLE001
                logger.warning("create_interaction failed (run=%s): %s",
                               self.run_id, e)

        # 发射事件 → 前端内联弹窗
        self.emitter(user_input_required(
            question=question,
            input_type=input_type,
            options=options,
            interaction_id=interaction_id,
            tool_call_id=interaction_id,
            multi_select=multi_select,
            allow_skip=allow_skip,
        ))

        # 阻塞等待（带 stop 轮询）
        self._user_response_event.clear()
        self._user_response = None
        while not self._user_response_event.is_set():
            if self.stop_event.is_set():
                if self.run_store:
                    try:
                        self.run_store.cancel_interaction(interaction_id)
                    except Exception:  # noqa: BLE001
                        pass
                return None
            self._user_response_event.wait(timeout=0.5)

        response = self._user_response
        if response and response.get("cancelled"):
            if self.run_store:
                try:
                    self.run_store.cancel_interaction(interaction_id)
                except Exception:  # noqa: BLE001
                    pass
            return None

        user_text = (response or {}).get("response", "") if response else ""
        if self.run_store and user_text:
            try:
                self.run_store.respond_interaction(interaction_id, user_text)
            except Exception:  # noqa: BLE001
                pass
        return user_text

    def provide_user_response(self, response: str, cancelled: bool = False) -> None:
        """由 /api/interactions/<id>/respond 调用，唤醒阻塞的 ask_user。"""
        self._user_response = {"response": response, "cancelled": cancelled}
        self._user_response_event.set()

    @property
    def run_id(self) -> str:
        """当前 run_id（legacy core 兼容属性；smol 引擎在 execute 时设置）。"""
        return getattr(self, "_run_id", "")

    @run_id.setter
    def run_id(self, value: str) -> None:
        self._run_id = value

    # ------------------------------------------------------------------
    # 审批包装
    # ------------------------------------------------------------------

    def _wrap_tools_for_approval(self, tools: list, bridge: SmolBridge) -> list:
        """包装工具：执行前按审批路由（auto/confirm/deny）决策。

        阶段 G：从 classify()（只看类别）升级为 check()（标记+模式+路径边界）：
          - deny    → 直接返回错误（黑名单危险命令）
          - confirm → ask_user 阻塞弹窗确认（人工审批：沙箱外/数据修改/命令行）
          - auto    → 原样执行
        确认交互复用 AskUserDialog 的 confirm 模式（批准返回空串，拒绝返回 None）。
        """
        wrapped = []
        for t in tools:
            original_forward = t.forward

            def make_forward(tool, forward):
                def guarded(*args, **kwargs):
                    # G6 审计修复：串行锁——模型一次并行输出多个 tool_calls 时，
                    # smolagents 用 ThreadPoolExecutor 并发执行，共享 SQLite 连接
                    # 会并发冲突（只完成第一个工具）。加锁排队串行执行，全部完成。
                    with self._tool_lock:
                        return self._guarded_execute(tool, forward, args, kwargs)
                return guarded

            t.forward = make_forward(t, original_forward)
            wrapped.append(t)
        return wrapped

    def _guarded_execute(self, tool, forward, args, kwargs):
        """工具执行（已持 _tool_lock）：审批路由 + 执行。拆出以便锁覆盖全流程。"""
        level = self.approval.check(tool.name, kwargs, self.work_dir)
        if level == "deny":
            return (f"错误：工具 {tool.name} 被审批策略拒绝（deny）。"
                    f"如需使用请联系管理员调整审批配置。")
        if level == "confirm":
            # 阻塞弹窗询问（AskUserDialog confirm 模式）
            question = f"是否执行 {tool.name}？"
            param_str = ""
            if kwargs:
                try:
                    import json as _json
                    param_str = _json.dumps(
                        kwargs, ensure_ascii=False, default=str)[:500]
                except Exception:  # noqa: BLE001
                    param_str = str(kwargs)[:500]
            if param_str:
                question += f"\n参数：{param_str}"
            answer = self.ask_user(question, input_type="confirm")
            if answer is None:
                return (f"已拒绝执行 {tool.name}（用户未批准）。"
                        f"请换一种无需越界/修改的方式完成任务，或询问用户。")
            # 审计修复（G6）：批准后若是沙箱工具且本次调用越界，
            # 按调用粒度临时解除沙箱（用户已明确授权这次越界访问，
            # 工具层不应再拦截）——执行完立即恢复，不影响后续审批。
            meta = TOOL_METADATA.get(tool.name)
            if (meta and meta.sandboxed
                    and path_escapes_workspace(kwargs, self.work_dir)):
                prev = getattr(tool, "_allow_outside", False)
                tool._allow_outside = True
                try:
                    return forward(*args, **kwargs)
                finally:
                    tool._allow_outside = prev
        # confirm（已批准）/ auto 原样执行
        return forward(*args, **kwargs)

    # ------------------------------------------------------------------
    # 数据平面摘要注入（阶段 3 关键调优）
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_target_variables(prompt: str) -> list[str]:
        """从用户任务文本中提取「」/『』/引号包裹的目标变量名。

        P17 变量聚焦：用户任务通常写明要核对的变量
        （如「销售回款提成金额」），AI 必须先聚焦该变量在两表的对应列，
        禁止全量探索无关数据。提取到后注入 instructions 强制聚焦。
        """
        import re as _re
        names: list[str] = []
        for pat in (r"「([^」]+)」", r"『([^』]+)』", r"\"([^\"]+)\"", r"'([^']+)'"):
            for m in _re.finditer(pat, prompt or ""):
                cand = m.group(1).strip()
                # 跳过文件路径（@file:/@folder: 或含扩展名）
                if cand.startswith("@file") or cand.startswith("@folder") or cand.startswith("待处理数据"):
                    continue
                if any(x in cand.lower() for x in (".xls", ".xlsx", ".csv", "/", "\\")):
                    continue
                # 只保留像变量/字段名的（含"金额/数/值/比例/回款/提成/变量/字段/销售"等财务特征词）
                if any(k in cand for k in ("金额", "数", "值", "比例", "回款", "提成", "变量", "字段", "销售")):
                    if cand not in names:
                        names.append(cand)
        return names[:3]  # 最多 3 个

    def _build_project_data_instructions(self, prompt: str) -> str:
        """构建 L0 极简数据文件清单 + 工具使用规则，注入 system prompt。

        智能体优化 3.0（阶段 C，省算力）：不再全量注入每张表的字段
        （N 表 × 300 token 常驻），只注入「文件名 + 分表数」概览（~80 token），
        字段明细一律按需：
          - 全清单（含行数等）→ list_data_files 工具
          - 单表字段索引 → get_table_index(file, sheet) 工具（~100 token）

        保留「项目数据库优先 + 修改安全」常驻规则（铁律 00：无游离工作流）。

        P17 变量聚焦：从用户任务提取「」内的目标变量名，
        强制 AI 只查该变量对应列 + 先聚合后明细，杜绝全量探索。
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
            lines = ["[项目数据库数据文件]"]
            for f in files:
                if f.get("status") != "done":
                    continue
                sheets = f.get("sheets") or []
                lines.append(
                    f"- {f.get('file_name')}（{f.get('sheet_count', 0)} 分表，"
                    f"{f.get('total_rows', 0)} 行）"
                    if sheets else
                    f"- {f.get('file_name')}（无分表）"
                )
            if len(lines) <= 1:
                return ""
            lines.append(
                "[规则] 以上是项目数据库中已导入的数据文件。"
                "看完整清单（含分表行数）用 list_data_files；"
                "看单表字段索引（定位匹配键/金额列）用 get_table_index(file, sheet)，"
                "不要凭猜测用 query_table 反复试字段。"
                "无论用户用目录路径（如 待处理数据/xxx.xls）还是库文件名提及，"
                "都必须使用 query_table / table_stats / join_tables 在项目数据库中查询，"
                "绝对禁止 read_excel / read_file 读取已导入的原始 Excel 文件；"
                "未导入的文件才允许用 read_excel 读取（或先 import_excel_to_db 导入）；"
                "跨表核对使用 join_tables（注意不支持 RIGHT JOIN）；"
                "修改数据使用 update_rows/insert_rows/delete_rows（需用户确认并记录变更日志），"
                "修改完成后调用 export_project_data 回写 Excel。"
            )
            # P17 变量聚焦：提取用户「」内的目标变量名，强制只查该变量
            targets = self._extract_target_variables(prompt)
            if targets:
                lines.append(
                    "[本次任务聚焦] 用户要核对的变量是：" + "、".join(targets) + "。\n"
                    "必须严格遵守：\n"
                    "1. 先在两表表头中定位该变量对应的列名（可能表述略不同，"
                    "如「销售回款提成金额」对应「兑现销售提成金额_2025年一季度」），"
                    "用 query_table 只选该列 + 关键分组列（销售人员/合同编号），"
                    "严禁查询/返回无关的全量列与全量行。\n"
                    "2. 先用 table_stats 按销售人员（或其他匹配键）对该变量聚合"
                    "（sum），做两表总账对比，只对差异项下钻 query_table 明细，"
                    "禁止逐人/逐单全量拉取。\n"
                    "3. 全流程工具调用控制在 8 次以内；数据对比完成立即 final_answer。"
                )
            return "\n\n".join(lines)
        except Exception:  # noqa: BLE001
            return ""

    # ------------------------------------------------------------------
    # 兼容接口（供外部引用）
    # ------------------------------------------------------------------

    @property
    def tool_registry(self) -> Any:
        """兼容占位：smol 引擎无 ToolRegistry，返回 None（调用方需判空）。"""
        return None

    def stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
