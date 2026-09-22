"""AgentConfig — structured agent configuration model.

Phase 7.2: Parses agent records from the database into a typed config object
consumed by AgentCore to drive the 7-stage General Agent workflow.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

WorkflowMode = Literal["react", "guided_execution"]
ApprovalLevel = Literal["auto", "confirm", "deny"]


@dataclass
class AgentWorkflow:
    mode: WorkflowMode = "guided_execution"
    # Phase 17: 0 = 无上限（长任务默认），唯一终止 = 用户手动停止；>0 为安全网
    max_iterations: int = 0
    require_clarification_before_execution: bool = True
    require_plan_approval: bool = True
    require_self_audit: bool = True
    context_token_budget: int = 8192


@dataclass
class AgentContextPolicy:
    file_reference: bool = True
    conversation_memory: bool = True
    tool_result_injection: bool = True
    max_context_files: int = 8
    max_history_turns: int = 20


@dataclass
class AgentToolPolicy:
    allowed_tools: list[str] = field(default_factory=list)
    approval_required_tools: list[str] = field(default_factory=list)
    workspace_only: bool = True


@dataclass
class AgentSkill:
    id: str = ""
    path: str = ""


@dataclass
class AgentConfig:
    """Structured configuration for a single agent.

    Constructed from a database row (dict) or raw JSON.
    """
    id: str = ""
    name: str = "通用智能体"
    version: str = "1.0.0"
    role: str = ""
    description: str = ""
    enabled: bool = True
    default_model: str = ""
    system_prompt: str = ""
    workflow: AgentWorkflow = field(default_factory=AgentWorkflow)
    context_policy: AgentContextPolicy = field(default_factory=AgentContextPolicy)
    tool_policy: AgentToolPolicy = field(default_factory=AgentToolPolicy)
    skills: list[AgentSkill] = field(default_factory=list)

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> AgentConfig:
        """Build AgentConfig from a database agents table row.

        JSON fields (dependencies, tools) are parsed from TEXT columns.
        """
        tools_raw = row.get("tools") or "[]"
        try:
            tools = json.loads(tools_raw) if isinstance(tools_raw, str) else tools_raw
        except (json.JSONDecodeError, TypeError):
            tools = []

        skill_path = row.get("skill_path") or ""
        skills = []
        if skill_path:
            skills.append(AgentSkill(id=row.get("id", ""), path=skill_path))

        return cls(
            id=row.get("id") or "",
            name=row.get("name") or "通用智能体",
            version=row.get("version") or "1.0.0",
            role=row.get("description") or "",
            description=row.get("description") or "",
            enabled=bool(row.get("enabled", 1)),
            default_model=row.get("default_model") or "",
            system_prompt=row.get("system_prompt") or "",
            workflow=AgentWorkflow(
                mode="guided_execution",
                max_iterations=0,  # Phase 17: 0 = 无上限
                require_clarification_before_execution=True,
                require_plan_approval=True,
                require_self_audit=True,
                context_token_budget=8192,
            ),
            context_policy=AgentContextPolicy(
                file_reference=True,
                conversation_memory=True,
                tool_result_injection=True,
                max_context_files=8,
                max_history_turns=20,
            ),
            tool_policy=AgentToolPolicy(
                allowed_tools=tools,
                approval_required_tools=[
                    "write_file", "delete_path", "move_path",
                    "run_command", "python.configure_environment",
                    "python.install_packages", "excel.agent_tools",
                ],
                workspace_only=True,
            ),
            skills=skills,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "role": self.role,
            "description": self.description,
            "enabled": self.enabled,
            "default_model": self.default_model,
            "system_prompt": self.system_prompt,
            "workflow": {
                "mode": self.workflow.mode,
                "max_iterations": self.workflow.max_iterations,
                "require_clarification_before_execution": self.workflow.require_clarification_before_execution,
                "require_plan_approval": self.workflow.require_plan_approval,
                "require_self_audit": self.workflow.require_self_audit,
                "context_token_budget": self.workflow.context_token_budget,
            },
            "context_policy": {
                "file_reference": self.context_policy.file_reference,
                "conversation_memory": self.context_policy.conversation_memory,
                "tool_result_injection": self.context_policy.tool_result_injection,
                "max_context_files": self.context_policy.max_context_files,
                "max_history_turns": self.context_policy.max_history_turns,
            },
            "tool_policy": {
                "allowed_tools": self.tool_policy.allowed_tools,
                "approval_required_tools": self.tool_policy.approval_required_tools,
                "workspace_only": self.tool_policy.workspace_only,
            },
            "skills": [{"id": s.id, "path": s.path} for s in self.skills],
        }
