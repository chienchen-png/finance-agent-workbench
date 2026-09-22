"""smol_model — FinanceModel：把现有 LLMClient 包装为 smolagents.Model。

阶段 1（引擎层替换）：复用已验证的 LLMClient（thinking 三家模型适配），
让 smolagents 引擎通过标准 Model 接口调用现有模型配置。

关键点（PoC 已验证，勿破坏）：
1. 流式增量：generate_stream() 逐 chunk yield ChatMessageStreamDelta，
   聚合器 agglomerate_stream_deltas 会自行拼接（工具参数增量不能重复累积）。
2. 文本式工具调用：smolagents 1.26 用 tool-call/tool-response 角色，
   get_clean_message_list + tool_role_conversions 转成 assistant/user
   （"Calling tools:"/"Observation:" 文本），天然绕开 DeepSeek
   reasoning_content 回传的 400 问题。
3. ChatMessageToolCallStreamDelta 必须带 index 字段。
"""

from __future__ import annotations

from typing import Callable

from agent.llm_client import LLMClient

from smolagents.models import (
    ChatMessage,
    ChatMessageStreamDelta,
    ChatMessageToolCallFunction,
    ChatMessageToolCallStreamDelta,
    Model,
    TokenUsage,
    agglomerate_stream_deltas,
    get_clean_message_list,
    get_tool_json_schema,
    tool_role_conversions,
)


def _extract_top_block(s: str) -> str:
    """括号深度匹配提取顶层块（{..} 或 [..]），避开字符串内的嵌套括号。"""
    starts = [i for i, ch in enumerate(s) if ch in "{["]
    if not starts:
        return s
    i = starts[0]
    open_ch = s[i]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    in_str = False
    str_ch = ""
    for j in range(i, len(s)):
        ch = s[j]
        if in_str:
            if ch == str_ch:
                in_str = False
            continue
        if ch in "\"'":
            in_str = True
            str_ch = ch
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return s[i:j + 1]
    return s[i:]


def _py_dict_to_json(text: str) -> str:
    """把文本中的 Python dict 单引号（'key': value）转成 JSON 双引号。

    深度容错（P6-⑦）：deepseek 偶发把工具调用输出成 Python dict 语法而非合法 JSON。
    分两步：
    1. 用括号深度匹配提取顶层 {..} 或 [..] 块（避开字符串内的嵌套括号），
       尝试 json.loads——成功则直接返回；
    2. 失败则用 ast.literal_eval 解析 Python 字面量（天然支持单引号/嵌套/列表），
       再 json.dumps 序列化回合法 JSON。
    3. 若 literal_eval 也失败（文本含变量/未定义名），做保守单引号→双引号替换兜底。
    """
    import json
    import re
    import ast

    blob = _extract_top_block(text)

    # 1) 直接 JSON 解析（本来就合法）
    try:
        json.loads(blob, strict=False)
        return text
    except Exception:
        pass

    # 2) Python 字面量解析（单引号 dict/list）
    try:
        obj = ast.literal_eval(blob)
        return text.replace(blob, json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass

    # 3) 保守单引号→双引号替换兜底
    text = re.sub(r"'([^']{1,64})'(\s*:)", r'"\1"\2', text)
    text = re.sub(r":\s*'([^'\"{}:,]{1,128})'", r': "\1"', text)
    return text


class FinanceModel(Model):
    """smolagents.Model 适配器：包装现有 LLMClient。"""

    def __init__(
        self,
        llm: LLMClient,
        model_id: str,
        thinking: bool = True,
        clear_thinking: bool = True,
        reasoning_effort: str = "medium",
        on_text_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ):
        super().__init__(model_id=model_id)
        self.llm = llm
        self.model_id = model_id
        self.thinking = thinking
        self.clear_thinking = clear_thinking
        self.reasoning_effort = reasoning_effort
        self.on_text_delta = on_text_delta
        self.on_reasoning = on_reasoning

    # --- OpenAI dict 转换（复用官方 get_clean_message_list）---
    def _to_openai_messages(self, messages):
        return get_clean_message_list(
            messages,
            role_conversions=tool_role_conversions,
            convert_images_to_image_urls=False,
            flatten_messages_as_text=True,
        )

    # --- 工具 schema（复用官方 get_tool_json_schema）---
    def _tools_schema(self, tools_to_call_from):
        if not tools_to_call_from:
            return None
        return [get_tool_json_schema(t) for t in tools_to_call_from]

    # --- 流式生成 ---
    def generate_stream(self, messages, stop_sequences=None, response_format=None,
                        tools_to_call_from=None, **kwargs):
        openai_msgs = self._to_openai_messages(messages)
        tools = self._tools_schema(tools_to_call_from)

        final_usage = None

        for chunk in self.llm.chat_stream(
            openai_msgs, tools=tools, thinking=self.thinking,
            reasoning_effort=self.reasoning_effort,
            clear_thinking=self.clear_thinking,
        ):
            delta = chunk.get("delta") or ""
            rd = chunk.get("reasoning_delta") or ""
            tcd = chunk.get("tool_call_delta")
            usage = chunk.get("usage")

            if rd and self.on_reasoning:
                self.on_reasoning(rd)

            # Phase 17 P12.2：所有文本增量一律透出到 on_text_delta（bridge 缓冲），
            # 不再做 chunk 级抑制——工具轮/正文的区分由 bridge 在 on_step
            # 按步骤类型（工具轮→思考、final 轮→正文）统一路由。
            # （原 P12 的 is_tool_turn=bool(tcd) 只能抑制与工具调用同 chunk 的
            # 文本，管不住工具调用之前独立 chunk 的规划文本。）
            if delta:
                if self.on_text_delta:
                    self.on_text_delta(delta)
                yield ChatMessageStreamDelta(content=delta, tool_calls=None,
                                             token_usage=None)

            if tcd:
                # 注意：此处 yield 的是【增量】，smolagents 聚合器自行累积拼接
                deltas = []
                for tc in tcd:
                    idx = tc.get("index", 0)
                    deltas.append(ChatMessageToolCallStreamDelta(
                        index=idx, id=tc.get("id") or "", type="function",
                        function=ChatMessageToolCallFunction(
                            name=tc.get("name") or "",
                            arguments=tc.get("arguments") or "")))
                yield ChatMessageStreamDelta(content="", tool_calls=deltas,
                                             token_usage=None)

            if usage:
                final_usage = TokenUsage(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0))

        yield ChatMessageStreamDelta(content="", tool_calls=None,
                                     token_usage=final_usage)

    # --- 非流式生成（聚合）---
    def generate(self, messages, stop_sequences=None, response_format=None,
                 tools_to_call_from=None, **kwargs):
        deltas = list(self.generate_stream(
            messages, stop_sequences, response_format, tools_to_call_from, **kwargs))
        return agglomerate_stream_deltas(deltas)

    # --- 工具调用解析容错（P6-⑦ 修复）---
    # deepseek 等模型偶发把工具调用输出成 Python dict 语法（单引号 'key': value）
    # 而非合法 JSON（"key": value）——smolagents 默认 json.loads(strict=False)
    # 无法解析单引号 → AgentParsingError → 循环重试/文本乱码。
    # 覆写 parse_tool_calls：解析前把「顶层单引号 dict/list」转成合法 JSON，
    # 并支持多工具调用数组 [ {...}, {...} ] 拆解为多个 tool_call。
    def parse_tool_calls(self, message):
        import json as _json
        from smolagents.models import parse_json_if_needed, get_tool_call_from_text

        message.role = "assistant"
        if not message.tool_calls and message.content:
            text = message.content
            fixed = _py_dict_to_json(text)
            if fixed != text:
                text = fixed
            # 提取顶层块（dict 或 list，括号深度匹配）
            from agent.smol_model import _extract_top_block
            blob = _extract_top_block(text)
            calls = []
            try:
                data = _json.loads(blob, strict=False)
                # 多工具调用数组：[{...}, {...}]
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            calls.append(self._build_call(item))
                # 单工具调用 dict：{...}
                elif isinstance(data, dict) and "function" in data or ("name" in data and "arguments" in data):
                    calls.append(self._build_call(data))
            except Exception:
                calls = []
            if calls:
                message.tool_calls = calls
            else:
                # 兜底：smolagents 默认提取第一个 {..}
                message.tool_calls = [
                    get_tool_call_from_text(text, self.tool_name_key, self.tool_arguments_key)
                ]
        for tc in message.tool_calls or []:
            try:
                args = tc.function.arguments
                # arguments 可能是字符串形式的 Python dict（单引号）——先做容错转换
                if isinstance(args, str) and args.strip().startswith(("{", "[")):
                    args = _py_dict_to_json(args)
                tc.function.arguments = parse_json_if_needed(args)
            except Exception:
                # 兜底：原样尝试
                tc.function.arguments = parse_json_if_needed(tc.function.arguments)
        return message

    def _build_call(self, item: dict):
        """从 dict 构建 ChatMessageToolCall（支持 {name, arguments} 或 {function:{...}}）。"""
        from smolagents.models import ChatMessageToolCall, ChatMessageToolCallFunction

        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        name = fn.get("name") or item.get("name") or ""
        arguments = fn.get("arguments", item.get("arguments", {}))
        return ChatMessageToolCall(
            id=str(item.get("id") or f"call_{abs(hash((name, str(arguments))[:8]))}"),
            type="function",
            function=ChatMessageToolCallFunction(name=name, arguments=arguments),
        )
