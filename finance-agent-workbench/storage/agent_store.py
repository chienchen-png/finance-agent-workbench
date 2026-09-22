"""Agent Store — CRUD for the agents table.

Phase 7.4: Provides agent configuration persistence.
Includes ensure_default_agent() to seed the database with the General Agent.
"""

from __future__ import annotations

import json
import sqlite3

from storage._utils import row_to_dict


class AgentStore:
    """CRUD for the agents table."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def get_all_enabled(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM agents WHERE enabled=1 ORDER BY name"
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_by_id(self, agent_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM agents WHERE id=?", (agent_id,)
        ).fetchone()
        return row_to_dict(row) if row else None

    def create(self, agent_id: str, name: str, system_prompt: str = "",
               tools: list[str] | None = None, skill_path: str = "",
               description: str = "", version: str = "1.0.0") -> dict:
        tools_json = json.dumps(tools or [], ensure_ascii=False)
        self.db.execute(
            """INSERT INTO agents (id, name, version, description, system_prompt, tools, skill_path, enabled)
               VALUES (?,?,?,?,?,?,?,1)""",
            (agent_id, name, version, description, system_prompt, tools_json, skill_path),
        )
        self.db.commit()
        return self.get_by_id(agent_id) or {}

    # ------------------------------------------------------------------
    # Default agent seeding
    # ------------------------------------------------------------------

    def ensure_default_agent(self) -> dict:
        """Ensure the General Agent exists in the database. Returns the agent row.

        2026-08-19：新增存量同步——若已存在但 version 落后于 LATEST_AGENT_VERSION，
        自动升级 description/tools/system_prompt（幂等，smol 引擎运行时能力不受影响，
        同步的是「智能体配置页」展示数据 + legacy 后备轨依赖）。
        """
        existing = self.get_by_id("general-agent")
        if existing:
            if existing.get("version") != LATEST_AGENT_VERSION:
                self._upgrade_default_agent(existing)
                existing = self.get_by_id("general-agent")
            return existing

        return self.create(
            agent_id="general-agent",
            name="通用智能体",
            description=LATEST_AGENT_DESCRIPTION,
            version=LATEST_AGENT_VERSION,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            tools=LATEST_AGENT_TOOLS,
            # 智能体优化 3.0（阶段 E）：skill_path 指向 .github/agents 下的
            # L0 常驻 agent.md（旧 skills/general_finance/main.skill.md 已归档）。
            skill_path=".github/agents/general-agent.agent.md",
        )

    def _upgrade_default_agent(self, existing: dict) -> None:
        """把存量 general-agent 记录升级到最新（version/description/tools/system_prompt）。"""
        self.db.execute(
            """UPDATE agents SET version=?, description=?, system_prompt=?, tools=?
               WHERE id='general-agent'""",
            (LATEST_AGENT_VERSION, LATEST_AGENT_DESCRIPTION,
             DEFAULT_SYSTEM_PROMPT, json.dumps(LATEST_AGENT_TOOLS, ensure_ascii=False)),
        )
        self.db.commit()


# ------------------------------------------------------------------
# 最新智能体定义（2026-08-19 3.2.0：新增 financial-modeling skill 全套能力）
# ------------------------------------------------------------------
LATEST_AGENT_VERSION = "3.2.0"
LATEST_AGENT_DESCRIPTION = (
    "面向财务人员的全功能智能助手。支持 Excel 数据核对（reconcile_variables 五级分级）、"
    "库内查询/统计/跨表连接、受控数据修改与精确写回、ask_user 三模式交互、"
    "命令行优先的文件操作（G5）、data-reconcile 核对方法论、"
    "financial-modeling 财务建模分析（32 模型/16 图表模板/公式讲解/L1 工具 + L2 代码执行）。"
)
# 39 个工具 = smol_tools.TOOL_CLASSES（30）+ ask_user + 8 个财务建模新工具（6 L1 +
# run_python_code + read_skill_resource），与 agent.md tools 白名单一致
LATEST_AGENT_TOOLS = [
    "read_file", "list_directory", "search_files", "write_file",
    "create_directory", "delete_path", "move_path", "copy_path",
    "run_command",
    "get_python_version", "get_python_executable", "get_installed_packages",
    "configure_python_environment",
    "get_sheet_info", "read_excel", "write_excel", "analyze_excel",
    "compare_excel_sheets",
    "import_excel_to_db", "query_table", "table_stats", "join_tables",
    "update_rows", "insert_rows", "delete_rows", "export_project_data",
    "list_data_files", "get_table_index",
    "reconcile_variables", "read_skill", "ask_user",
    # 财务建模（financial-modeling skill，3.2.0）
    "financial_metrics", "regression_analysis", "correlation_matrix",
    "time_series_analysis", "sensitivity_analysis", "generate_chart",
    "run_python_code", "read_skill_resource",
]

DEFAULT_SYSTEM_PROMPT = """你是一个面向财务人员的全功能智能助手（Finance Agent）。

## 核心能力
- 数据文件导入与库内查询（import_excel_to_db / query_table / table_stats / join_tables）
- 数据核对与差异分级（reconcile_variables：多级匹配 + OK/A1/A2/B/C 五级分级）
- 数据修改与精确写回（update_rows / insert_rows / delete_rows / export_project_data）
- 向用户提问确认（ask_user：text / confirm / select 三模式）
- 命令行优先的文件系统操作（run_command：列目录 / 批量 / 搜索 / 项目外访问）
- Skill 方法论按需加载（read_skill：data-reconcile 核对流程 / financial-modeling 建模流程）
- 财务建模分析（financial_metrics / regression_analysis / correlation_matrix /
  time_series_analysis / sensitivity_analysis / generate_chart；
  L2 代码执行 run_python_code；references 按需读取 read_skill_resource）

## 工作方式
1. 理解需求 → 2. 需要时 ask_user 澄清 → 3. 操作工具执行 → 4. 输出中文结论
（复杂核对任务按 data-reconcile skill 方法论；财务建模按 financial-modeling skill 流程）

## 重要规则
- Excel 数据必须走数据库：先 import_excel_to_db，查询/核对用数据库工具，禁止 run_command 读 Excel
- 两表金额核对用 reconcile_variables 一次完成，禁止手工逐表比对
- 文件系统类操作优先 run_command 一次完成，不写临时脚本
- 写操作（update/delete/write/export）前必须 ask_user 确认，且自动记录变更日志
- 简单任务（问候/常识/纯交互）不输出计划，直接回答
- 最终答案用中文，格式规范

> 注：实际执行提示词由 smol 引擎 FINANCE_PROMPT_TEMPLATES（规则 1-13）+ L0 agent.md 提供，
> 本字段供智能体配置页展示与 legacy 后备轨使用。
"""
