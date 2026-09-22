#!/usr/bin/env python3
"""ApprovalManager — permission check for tool execution (LEGACY).

⚠️ DEPRECATED（阶段 G）：新代码请使用 agent/approval/ 包的 ApprovalRouter
（标记驱动 + 模式策略 + 路径边界，微服务化）。本文件仅为 legacy 后备轨
（core.py / tool_registry.py）保留的兼容实现，功能冻结不再演进。

Phase 8: Provides tool risk classification and approval policy decisions.
Used by AgentCore before executing any tool.

Permission levels:
  - auto: Execute immediately (read, search, todo, python_info)
  - confirm: Must get user approval before execution (write, delete, command, python_env)
  - deny: Always blocked (outside workspace, network)
"""

from __future__ import annotations

from typing import Literal

ApprovalLevel = Literal["auto", "confirm", "deny"]

# Tool → category mapping (Phase 8: aligned with ToolRegistry real tool names)
TOOL_CATEGORY_MAP: dict[str, str] = {
    # Read/search (🟢 auto)
    "read_file": "read",
    "list_directory": "read",
    "search_files": "search",
    "read_excel": "read",
    "get_sheet_info": "read",
    "analyze_excel": "read",
    "compare_excel_sheets": "read",
    # Project data plane (Phase 14B, 🟢 read-only in-DB queries)
    "import_excel_to_db": "read",
    "query_table": "read",
    "table_stats": "read",
    # Project data plane join (Phase 14D, 🟢 read-only)
    "join_tables": "read",
    # Project data plane changes (Phase 14C, 🟡 confirm per PRD §3.12.6)
    "update_rows": "project_data_change",
    "insert_rows": "project_data_change",
    "delete_rows": "project_data_change",
    "export_project_data": "project_data_change",
    # Plan/interaction (🟢 auto)
    "ask_user": "todo",
    "plan_task": "todo",
    # Python info (🟢 auto)
    "get_python_version": "python_info",
    "get_python_executable": "python_info",
    "get_installed_packages": "python_info",
    # Write/modify (🟡 confirm)
    "write_file": "write_workspace",
    "create_directory": "write_workspace",
    "move_path": "write_workspace",
    "copy_path": "write_workspace",
    "write_excel": "write_workspace",
    # Delete (🟡 confirm)
    "delete_path": "delete_path",
    # Command (🟡 confirm)
    "run_command": "run_command",
    # Python env change (🟡 confirm)
    "configure_python_environment": "python_environment_change",
}


class ApprovalManager:
    """Decides whether a tool call needs user approval.

    Policy (Phase 9: workspace-first, maximum autonomy):
      - All tools operating INSIDE the project workspace run automatically
        (auto) — no user confirmation required.
      - Only operations that attempt to touch paths OUTSIDE the workspace
        are denied (deny) by the boundary check in check().
      - deny is reserved for out-of-workspace access and the command
        blacklist in command_tools.py.
    """

    def __init__(self, policy: dict[str, ApprovalLevel] | None = None) -> None:
        self.policy = policy or {
            "read": "auto",
            "search": "auto",
            "todo": "auto",
            "python_info": "auto",
            "write_workspace": "auto",
            "delete_path": "auto",
            "run_command": "auto",
            "python_environment_change": "auto",
            "project_data_change": "confirm",  # Phase 14C: data mutation
            "outside_workspace": "deny",
        }

    def classify(self, tool_name: str) -> str:
        """Map a tool name to its risk category."""
        return TOOL_CATEGORY_MAP.get(tool_name, "write_workspace")

    def check(self, tool_name: str, params: dict | None = None,
              work_dir: str = "") -> ApprovalLevel:
        """Determine the permission level for a tool call.

        Args:
            tool_name: Name of the tool being called.
            params: Tool parameters (used to check path boundaries).
            work_dir: Project work directory for path validation.

        Returns:
            "auto" | "confirm" | "deny"
        """
        params = params or {}

        # Workspace boundary check for path-based tools.
        # Phase 9: inside-workspace paths run automatically; paths that
        # escape the workspace require explicit user confirmation.
        # Covers: path, file_path, target, source, destination, file1, file2
        path_keys = ("path", "file_path", "target", "source", "destination",
                     "file1", "file2", "input", "output")
        if work_dir:
            import os
            for key in path_keys:
                p = params.get(key) or ""
                if not p:
                    continue
                try:
                    abs_path = os.path.abspath(os.path.join(work_dir, p))
                    abs_work = os.path.abspath(work_dir)
                    if not abs_path.startswith(abs_work + os.sep) and abs_path != abs_work:
                        # Outside workspace → user confirmation required
                        return "confirm"
                except (ValueError, OSError):
                    return "confirm"

        category = self.classify(tool_name)
        return self.policy.get(category, "auto")
