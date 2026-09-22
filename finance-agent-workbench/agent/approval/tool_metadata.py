"""工具元数据注册表 — 标记决定审批路由路径。

微服务化架构（阶段 G）：每个工具一个元数据条目，标记（sandboxed /
outside_capable / risk）决定路由走向。识别到标记 → 走确认路；无标记 →
默认 auto。

标记语义：
  - sandboxed=True      受工作目录沙箱约束（人工模式越界 → confirm；
                        全自动模式解除沙箱 → 放行）
  - outside_capable=True 可访问沙箱外（run_command；人工模式必 confirm）
  - risk                风险等级：read / write / data_change / command /
                        python_env（data_change 人工模式必 confirm）

新增工具：在此加一行即可，路由自动生效。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolMeta:
    sandboxed: bool = False        # 受工作目录沙箱约束（全自动模式解除）
    outside_capable: bool = False  # 可访问沙箱外（人工模式必确认）
    risk: str = "read"             # 风险等级


TOOL_METADATA: dict[str, ToolMeta] = {
    # ── 文件系统（sandboxed → 全自动解除沙箱）──
    "read_file": ToolMeta(sandboxed=True, risk="read"),
    "list_directory": ToolMeta(sandboxed=True, risk="read"),
    "search_files": ToolMeta(sandboxed=True, risk="read"),
    "write_file": ToolMeta(sandboxed=True, risk="write"),
    "create_directory": ToolMeta(sandboxed=True, risk="write"),
    "delete_path": ToolMeta(sandboxed=True, risk="write"),
    "move_path": ToolMeta(sandboxed=True, risk="write"),
    "copy_path": ToolMeta(sandboxed=True, risk="write"),
    # ── Excel（sandboxed → 全自动解除沙箱）──
    "read_excel": ToolMeta(sandboxed=True, risk="read"),
    "get_sheet_info": ToolMeta(sandboxed=True, risk="read"),
    "write_excel": ToolMeta(sandboxed=True, risk="write"),
    "analyze_excel": ToolMeta(sandboxed=True, risk="read"),
    "compare_excel_sheets": ToolMeta(sandboxed=True, risk="read"),
    # import_excel_to_db 内部经 ProjectDataImporter._resolve_work_path 强制沙箱，
    # 不透传 allow_outside（两种模式均仅在沙箱内导入；项目外文件先复制进项目或走命令行）
    # ── 命令行（outside_capable → 人工模式必确认 / 全自动直行）──
    "run_command": ToolMeta(outside_capable=True, risk="command"),
    "configure_python_environment": ToolMeta(risk="python_env"),
    # ── 数据平面（data_change → 人工模式必确认）──
    "update_rows": ToolMeta(risk="data_change"),
    "insert_rows": ToolMeta(risk="data_change"),
    "delete_rows": ToolMeta(risk="data_change"),
    "export_project_data": ToolMeta(risk="data_change"),
    # 其余工具（query_table/table_stats/join_tables/reconcile_variables/
    # ask_user/plan_task/read_skill/list_data_files/get_table_index/
    # get_python_version 等）无标记 → 默认 auto，不弹确认。
}
