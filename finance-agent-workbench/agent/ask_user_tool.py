"""ask_user_tool — AskUserTool：向用户提问的 smolagents 工具。

智能体优化 3.0（阶段 A1）：为 smol 引擎补 ask_user 交互能力。
legacy AgentCore 已有 _ask_user/provide_user_response（core.py:1505），
smol 引擎此前缺失 —— 本工具 + smol_engine 的 _ask_user 对齐实现补齐链路。

三种模式（对齐方案 5.2 AskUserDialog）：
- text    自由文本输入
- confirm 是/否确认
- select  选项单选

事件契约：发射 user_input_required（含 interaction_id/question/input_type/options），
前端 AskUserDialog 弹出后用户回答 → /api/interactions/<id>/respond →
engine.provide_user_response() 唤醒阻塞 → 本工具返回答案字符串。
"""

from __future__ import annotations

from typing import Any

from smolagents import Tool

from agent import agent_events as ev

# 阻塞等待轮询间隔（秒）——与 legacy core 一致，便于响应 stop 事件
_WAIT_TIMEOUT = 0.5


class AskUserTool(Tool):
    """向用户提问（text/confirm/select），阻塞等待用户响应。

    通过 engine 的 _ask_user 实现事件发射 + 阻塞；engine 需暴露
    ask_user(question, input_type, options) 方法。
    """

    name = "ask_user"
    description = (
        "向用户提问。input_type=text 自由输入；confirm 是/否；"
        "select 选项单选。用于澄清需求、确认匹配原则、请求审批。"
    )
    inputs = {
        "question": {"type": "string", "description": "问题内容"},
        "input_type": {
            "type": "string",
            "description": "text/confirm/select，默认 text",
            "nullable": True,
        },
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "select 模式选项列表",
            "nullable": True,
        },
        "multi_select": {
            "type": "boolean",
            "description": "select 模式是否允许多选（返回逗号分隔），默认 false",
            "nullable": True,
        },
        "allow_skip": {
            "type": "boolean",
            "description": "是否允许用户跳过此问题，默认 false",
            "nullable": True,
        },
    }
    output_type = "string"

    def __init__(self, engine: Any = None, work_dir: str = "",
                 project_id: str = ""):
        """engine：SmolAgentEngine 实例（提供 ask_user 阻塞方法）。"""
        super().__init__()
        self._engine = engine
        self._work_dir = work_dir
        self._project_id = project_id

    def forward(self, question: str, input_type: str = "text",
                options: list[str] | None = None,
                multi_select: bool = False,
                allow_skip: bool = False) -> str:
        """阻塞等待用户回答，返回答案字符串；用户取消返回 'USER_CANCELLED'。"""
        # 引擎未注入时（防御：单测/脱离引擎场景）直接返回提示
        if self._engine is None or not hasattr(self._engine, "ask_user"):
            return "错误：ask_user 工具未绑定引擎（engine.ask_user 不可用）"

        answer = self._engine.ask_user(
            question=question,
            input_type=input_type or "text",
            options=options or [],
            multi_select=bool(multi_select),
            allow_skip=bool(allow_skip),
        )
        # 用户取消（None）→ 返回哨兵值，AI 应据此调整策略（如跳过该问题）
        return answer if answer is not None else "USER_CANCELLED"
