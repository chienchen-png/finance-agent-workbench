"""ContextManager -- partitioned context management with budget control.

Phase 12: Implements semantic partitioning (similar to VS Code Copilot):
  - SYSTEM: Immutable system prompt (never compressed)
  - INSTRUCTIONS: Tool schemas + agent guidance (locked, small budget)
  - USER_CONTEXT: Attached file references (capped ratio)
  - MESSAGES: Conversation history (largest partition, sliding window)
  - TOOL_RESULTS: Recent tool outputs (capped ratio, FIFO eviction)
"""

from __future__ import annotations

import logging
from typing import Any

from agent.agent_config import AgentConfig
from tools.context_compressor import (
    estimate_tokens,
)

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_WINDOW = 8192
RESPONSE_RESERVE_RATIO = 0.15

PARTITION_BUDGET = {
    "system":        0.05,
    "instructions":  0.08,
    "user_context":  0.07,
    "messages":      0.75,
    "tool_results":  0.05,
}

LOCKED_PARTITIONS = {"system", "instructions"}


class _Partition:
    __slots__ = ("name", "items", "max_ratio", "_token_estimate")

    def __init__(self, name: str, max_ratio: float) -> None:
        self.name = name
        self.items: list[dict] = []
        self.max_ratio = max_ratio
        self._token_estimate = 0

    def add(self, item: dict) -> None:
        self.items.append(item)
        self._token_estimate += estimate_tokens(str(item.get("content", "")))

    def clear(self) -> int:
        removed = len(self.items)
        self.items.clear()
        self._token_estimate = 0
        return removed

    @property
    def tokens(self) -> int:
        return self._token_estimate

    def recount(self) -> None:
        self._token_estimate = sum(
            estimate_tokens(str(i.get("content", ""))) for i in self.items
        )


class ContextManager:
    """Partitioned context manager -- semantic budget control per partition."""

    def __init__(self, agent_config: AgentConfig | None = None,
                 context_window: int = DEFAULT_CONTEXT_WINDOW,
                 work_dir: str = "") -> None:
        self.config = agent_config
        self.context_window = context_window
        self.work_dir = work_dir
        self._messages: list[dict] = []
        self._tool_results: list[dict] = []
        self._partitions = {
            name: _Partition(name, ratio)
            for name, ratio in PARTITION_BUDGET.items()
        }

    @property
    def response_reserve(self) -> int:
        return int(self.context_window * RESPONSE_RESERVE_RATIO)

    @property
    def effective_budget(self) -> int:
        return max(0, self.context_window - self.response_reserve)

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def reset(self, initial_user_message: str = "") -> None:
        self._messages = []
        self._tool_results = []
        for p in self._partitions.values():
            p.clear()
        if self.config:
            sp = self.config.system_prompt or self._default_system_prompt()
        else:
            sp = ""
        if sp:
            sys_msg = {"role": "system", "content": sp}
            self._messages.append(sys_msg)
            # Phase 8 fix: also add to system partition for token counting
            self._partitions["system"].add(sys_msg)
        if initial_user_message:
            user_msg = {"role": "user", "content": initial_user_message}
            self._messages.append(user_msg)
            self._partitions["messages"].add(user_msg)

    def add_user_message(self, content: str) -> None:
        msg = {"role": "user", "content": content}
        self._messages.append(msg)
        # Phase 8 fix: keep partitions in sync so token counting + compression work
        self._partitions["messages"].add(msg)

    def clear_messages(self, keep_system: bool = True) -> int:
        removed = len(self._messages)
        sys_msg = None
        if keep_system and self._messages and self._messages[0].get("role") == "system":
            sys_msg = self._messages[0]
            self._messages = [sys_msg]
            removed -= 1
        else:
            self._messages = []
        for p in self._partitions.values():
            p.clear()
        # Phase 12 fix: re-add system prompt to system partition
        if sys_msg:
            self._partitions["system"].add(sys_msg)
        logger.info("clear_messages: removed %d messages, %d remain", removed, len(self._messages))
        return removed

    def add_assistant_message(self, content: str | None = None,
                              tool_calls: list[dict] | None = None,
                              reasoning_content: str | None = None) -> None:
        msg: dict[str, Any] = {"role": "assistant"}
        if content:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = tool_calls
        # DeepSeek 思考模式工具调用：assistant 消息必须保留 reasoning_content，
        # 后续带 tools 的请求需完整回传，否则 400 / 上下文断裂。
        # 其他模型（千问/GLM/OpenAI 兼容）忽略未知字段，无副作用。
        if reasoning_content:
            msg["reasoning_content"] = reasoning_content
        self._messages.append(msg)
        # Phase 8 fix: keep partitions in sync so token counting + compression work
        self._partitions["messages"].add(msg)

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: str) -> None:
        msg = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }
        self._messages.append(msg)
        # Phase 8 fix: keep partitions in sync
        self._partitions["tool_results"].add(msg)
        self._tool_results.append({
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "result_snippet": result[:500],
        })

    # ------------------------------------------------------------------
    # Budget & compression (Phase 12: partition-aware)
    # ------------------------------------------------------------------

    @property
    def current_tokens(self) -> int:
        return sum(p.tokens for p in self._partitions.values())

    @property
    def usage_pct(self) -> float:
        if self.context_window <= 0:
            return 0.0
        return (self.current_tokens / self.context_window) * 100

    def _partition_budget(self, name: str) -> int:
        return int(self.effective_budget * PARTITION_BUDGET.get(name, 0.1))

    def needs_compression(self) -> bool:
        return self.current_tokens > int(self.effective_budget * 0.85)

    def compress(self) -> str | None:
        """Phase 17 fix: 压缩升级 —— 保持顺序的轮次段压缩。

        直接在 _messages 上按「轮次段」移除最旧内容，保证：
        - 消息相对顺序不变（旧实现 pop(0) + append 把摘要排到末尾，破坏顺序）
        - assistant(tool_calls) 与后续 tool 消息绑定为同一段不可拆分，
          否则 OpenAI 兼容 API 以 400 "tool_calls must be followed by
          tool message" 拒绝（2026-08-17 全量回归 Test 4 复现）
        - system 消息始终保留
        """
        if not self.needs_compression():
            return None
        budget = (self._partition_budget("messages")
                  + self._partition_budget("tool_results"))

        system_msg = None
        segments: list[list[dict]] = []
        for m in self._messages:
            role = m.get("role", "")
            if role == "system":
                system_msg = m
                continue
            if role in ("user", "assistant") and not m.get("tool_calls"):
                segments.append([m])
            elif segments:
                segments[-1].append(m)
            else:
                segments.append([m])

        def _seg_tokens(seg: list[dict]) -> int:
            return sum(estimate_tokens(str(m.get("content", "")))
                       for m in seg)

        seg_tokens = [_seg_tokens(s) for s in segments]
        total = sum(seg_tokens)
        # 从最旧段开始移除，直到估算达标或只剩最近一段
        while len(segments) > 1 and total > budget:
            total -= seg_tokens.pop(0)
            segments.pop(0)

        new_messages: list[dict] = [system_msg] if system_msg else []
        for seg in segments:
            new_messages.extend(seg)
        self._messages = new_messages

        self._sync_to_partitions()
        logger.info("Context compressed: ~%d tokens (segment-aware, order preserved)",
                    self.current_tokens)
        return None

    def _sync_to_partitions(self) -> None:
        for p in self._partitions.values():
            p.clear()
        for m in self._messages:
            role = m.get("role", "")
            content = str(m.get("content", ""))
            if role == "system" and "工具" not in content:
                self._partitions["system"].add(m)
            elif role == "system":
                self._partitions["instructions"].add(m)
            elif role == "tool":
                self._partitions["tool_results"].add(m)
            elif role in ("user", "assistant"):
                self._partitions["messages"].add(m)
            else:
                self._partitions["messages"].add(m)

    # ------------------------------------------------------------------
    # Build final message list for LLM call
    # ------------------------------------------------------------------

    def get_messages(self) -> list[dict]:
        # Phase 17 fix: compress() 直接在 _messages 上按轮次段压缩并保持顺序，
        # 直接返回即可 —— 不再走分区重建（旧实现会破坏 assistant↔tool 配对顺序）。
        self.compress()
        return self._messages

    def get_stats(self) -> dict:
        # Phase 12 fix: sync partitions from _messages before reading
        self._sync_to_partitions()
        window = self.context_window
        total = self.current_tokens
        partitions = {}
        for name, p in self._partitions.items():
            partitions[name] = {
                "tokens": p.tokens,
                "budget": self._partition_budget(name),
                "ratio": PARTITION_BUDGET[name],
                "items": len(p.items),
                "locked": name in LOCKED_PARTITIONS,
            }
        return {
            "current_tokens": total,
            "context_window": window,
            "response_reserve": self.response_reserve,
            "effective_budget": self.effective_budget,
            "usage_pct": round(self.usage_pct, 1),
            "message_count": len(self._partitions["messages"].items),
            "context_files_count": 0,
            "tool_result_count": len(self._tool_results),
            "partitions": partitions,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _default_system_prompt(self) -> str:
        return "你是一个面向财务人员的全功能智能助手。可以自由使用工具完成任务，也可直接在对话中回答。所有文件操作限定在工作目录内。用 Markdown 格式回复。"
