"""Agents API — agent listing and configuration.

Phase 7.4: Provides agent list and detail endpoints for frontend agent picker.
"""

from __future__ import annotations

from flask import Blueprint

from routes._utils import error, success
from storage.db import get_db
from storage.agent_store import AgentStore
from agent.agent_config import AgentConfig

agents_bp = Blueprint("agents_api", __name__, url_prefix="/api/agents")


# ------------------------------------------------------------------
# GET /api/agents
# ------------------------------------------------------------------
@agents_bp.get("")
def list_agents():
    """Return all enabled agents as config dicts."""
    db = get_db()
    store = AgentStore(db)
    try:
        agents = store.get_all_enabled()
        if not agents:
            # Ensure default agent exists
            store.ensure_default_agent()
            agents = store.get_all_enabled()
        configs = [AgentConfig.from_db_row(a).to_dict() for a in agents]
        return success({"agents": configs})
    except Exception as e:
        return error(f"加载智能体列表失败: {e}")


# ------------------------------------------------------------------
# GET /api/agents/<agent_id>
# ------------------------------------------------------------------
@agents_bp.get("/<agent_id>")
def get_agent(agent_id: str):
    """Return a specific agent's full configuration."""
    db = get_db()
    store = AgentStore(db)
    try:
        agent = store.get_by_id(agent_id)
        if not agent:
            return error("智能体不存在", 404)
        config = AgentConfig.from_db_row(agent).to_dict()
        return success({"agent": config})
    except Exception as e:
        return error(f"加载智能体配置失败: {e}")


# ------------------------------------------------------------------
# GET /api/agents/<agent_id>/tools
# ------------------------------------------------------------------
@agents_bp.get("/<agent_id>/tools")
def get_agent_tools(agent_id: str):
    """Return the agent's tool catalog (static, by category).

    阶段 7.8：智能体配置页「工具罗列」静态展示用。
    数据源：agent/smol_tools.py 的 get_tool_catalog()（26 个 Tool 类）。
    仅展示能力，不提供任何修改（智能体配置为只读）。
    """
    try:
        # 智能体存在性校验（复用 get_agent 逻辑）
        db = get_db()
        store = AgentStore(db)
        agent = store.get_by_id(agent_id)
        if not agent:
            return error("智能体不存在", 404)
        from agent.smol_tools import get_tool_catalog
        return success({"agent_id": agent_id, "catalog": get_tool_catalog()})
    except Exception as e:
        return error(f"加载工具清单失败: {e}")
