"""agent/approval — 审批路由模块（微服务化架构，阶段 G）。

对外唯一入口：ApprovalRouter（router.check → auto/confirm/deny）。

分层解耦（微服务化思想）：
  - 引擎（SmolAgentEngine）只调用 check() 问「走哪条路」，不感知策略细节
  - 工具标记集中在 tool_metadata.py（新增工具 = 加一行）
  - 模式策略集中在 policies.py（新增模式 = 加一个 Policy 实例）
  - 路径越界检测是纯函数（workspace_boundary.py），与策略解耦

路由规则（标记识别 → 路由）：
  - 识别到 outside_capable 标记（run_command）→ 人工模式必确认
  - 识别到 risk=data_change 标记（update_rows 等）→ 人工模式必确认
  - 识别到 sandboxed 标记（文件工具）且路径越界 → 人工模式确认
  - 无标记工具 → 默认 auto（不弹确认）
  - 全自动模式：除黑名单外全部放行
  - 黑名单（危险命令）：两种模式恒 deny（安全底线）

注意：旧文件 agent/approval.py（ApprovalManager）已移入本包 approval_legacy.py，
并在此 re-export 以兼容 legacy 后备轨（core.py / tool_registry.py）的
`from agent.approval import ApprovalManager` 引用。新代码一律使用 ApprovalRouter。
"""
from .router import ApprovalRouter
from .tool_metadata import TOOL_METADATA, ToolMeta

# ── Legacy 兼容层（DEPRECATED，仅供 core.py / tool_registry.py 后备轨使用）──
from .approval_legacy import ApprovalLevel, ApprovalManager, TOOL_CATEGORY_MAP

__all__ = ["ApprovalRouter", "TOOL_METADATA", "ToolMeta",
           "ApprovalManager", "ApprovalLevel", "TOOL_CATEGORY_MAP"]
