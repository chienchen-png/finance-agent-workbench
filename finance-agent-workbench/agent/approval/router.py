"""ApprovalRouter — 路由引擎：按工具标记 + 模式决策 auto/confirm/deny。

唯一审批入口。引擎只依赖本类，不感知策略细节（policies.py）、
标记注册表（tool_metadata.py）或路径边界检测（workspace_boundary.py）。
"""
from __future__ import annotations

from .policies import ApprovalLevel, get_policy
from .tool_metadata import TOOL_METADATA
from .workspace_boundary import path_escapes_workspace


class ApprovalRouter:
    """按标记 + 模式识别路由。

    路由规则：
      1. run_command 命中黑名单 → deny（两种模式恒拦）
      2. 全自动模式 → 除黑名单外全部 auto
      3. 人工模式 → 按标记：
         - outside_capable（run_command）→ confirm（每次必确认）
         - risk=data_change（update_rows 等）→ confirm
         - sandboxed 且路径越界 → confirm
         - 其余（无标记/界内）→ auto
    """

    def __init__(self, work_mode: str = "manual") -> None:
        self.work_mode = work_mode
        self.policy = get_policy(work_mode)

    def check(self, tool_name: str, params: dict | None = None,
              work_dir: str = "") -> ApprovalLevel:
        """决定一次工具调用是否需要用户确认。

        Args:
            tool_name: 工具名。
            params: 工具调用参数（用于路径边界/命令黑名单检查）。
            work_dir: 项目工作目录。

        Returns:
            "auto" | "confirm" | "deny"
        """
        params = params or {}

        # ① 黑名单 → deny（两种模式都不例外，安全底线）
        if tool_name == "run_command":
            from tools.command_tools import _check_blacklist
            cmd = params.get("command") or ""
            if _check_blacklist(cmd):
                return "deny"

        # ② 全自动：除黑名单外全部放行
        if self.work_mode == "auto":
            return "auto"

        # ③ 人工审批：按标记识别路由
        meta = TOOL_METADATA.get(tool_name)
        if meta is None:
            return "auto"  # 无标记 → 默认自动
        if meta.outside_capable:
            return "confirm"  # run_command 每次必确认
        if meta.risk == "data_change":
            return "confirm"  # 数据修改必确认
        if meta.sandboxed and path_escapes_workspace(params, work_dir):
            return "confirm"  # 沙箱工具越界 → 确认
        return "auto"
