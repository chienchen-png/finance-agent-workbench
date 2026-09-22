"""模式策略表 — 微服务化：加新模式 = 加一个 Policy 实例，零侵入。

两种模式的差异仅在三类操作的处理级别：
  - outside_capable：沙箱外能力（run_command）——人工必确认 / 全自动放行
  - data_change：数据修改（update_rows 等）——人工必确认 / 全自动放行
  - sandbox_escape：沙箱工具越界访问——人工确认 / 全自动放行
  - blacklist：危险命令——恒 deny（两种模式都不例外，安全底线）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ApprovalLevel = Literal["auto", "confirm", "deny"]


@dataclass(frozen=True)
class Policy:
    outside_capable: ApprovalLevel  # 沙箱外能力（命令行）
    data_change: ApprovalLevel      # 数据修改
    sandbox_escape: ApprovalLevel   # 沙箱工具越界
    blacklist: ApprovalLevel        # 危险命令（恒 deny）


MANUAL_POLICY = Policy(
    outside_capable="confirm",
    data_change="confirm",
    sandbox_escape="confirm",
    blacklist="deny",
)

AUTO_POLICY = Policy(
    outside_capable="auto",
    data_change="auto",
    sandbox_escape="auto",
    blacklist="deny",
)


def get_policy(work_mode: str) -> Policy:
    """按工作模式取策略。未知模式回退人工审批（安全默认）。"""
    return AUTO_POLICY if work_mode == "auto" else MANUAL_POLICY
