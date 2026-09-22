"""LLMClient — OpenAI-compatible API wrapper with streaming support.

Phase 7.2: Provides chat completion and tool-calling for the AgentCore.
Supports optional API key and base URL from the models/provider configuration.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
DEFAULT_TIMEOUT = 300  # seconds (Phase 17: 120→300, 本地模型长推理不超时)
DEFAULT_MAX_TOKENS = 4096


class LLMClient:
    """Lightweight OpenAI-compatible chat completion client.

    Uses only stdlib (urllib) to avoid external HTTP dependencies.
    Supports streaming via `chat_stream()` generator.
    """

    def __init__(self, api_url: str, api_key: str = "",
                 model: str = "", timeout: int = DEFAULT_TIMEOUT) -> None:
        if api_url.endswith("/"):
            api_url = api_url[:-1]
        # Ensure the URL ends with /chat/completions or we'll append it
        if not api_url.endswith("/chat/completions"):
            if api_url.endswith("/v1"):
                api_url += "/chat/completions"
            else:
                api_url += "/v1/chat/completions" if "/v1" not in api_url else "/chat/completions"
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Streaming chat (generator)
    # ------------------------------------------------------------------

    def chat_stream(self, messages: list[dict], tools: list[dict] | None = None,
                    temperature: float = 0.1, max_tokens: int = DEFAULT_MAX_TOKENS,
                    model: str | None = None,
                    thinking: bool | None = None,
                    reasoning_effort: str | None = None,
                    clear_thinking: bool | None = None):
        """Generator that yields delta dicts from a streaming chat completion.

        Each yield: {"delta": str, "reasoning_delta": str | None, "tool_call_delta": dict | None, "finish_reason": str | None}
        """
        body = self._build_body(messages, tools, temperature, max_tokens, model,
                                stream=True, thinking=thinking,
                                reasoning_effort=reasoning_effort,
                                clear_thinking=clear_thinking)
        response = self._post(body, stream=True)
        for chunk in self._iter_sse_chunks(response):
            yield self._parse_stream_chunk(chunk)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_body(self, messages: list[dict], tools: list[dict] | None,
                    temperature: float, max_tokens: int, model: str | None,
                    stream: bool,
                    thinking: bool | None = None,
                    reasoning_effort: str | None = None,
                    clear_thinking: bool | None = None) -> dict:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        # 思考模式参数（三家模型差异兼容）：
        #  - DeepSeek V3.2+：OpenAI 格式用 reasoning_effort；thinking 需放
        #    extra_body 顶层（部分 SDK 映射为 thinking 参数）。
        #  - 智谱 GLM-5.2（z.ai）：参数格式与 DeepSeek 一致——thinking.type +
        #    reasoning_effort；agent/coding 场景推荐 clear_thinking=False
        #    （Preserved Thinking，保留历史 reasoning_content 需完整回传）。
        #  - 千问 Qwen（阿里云百炼 OpenAI 兼容）：标准 OpenAI 参数集，
        #    无 thinking/clear_thinking → 不传（避免未知字段被拒）。
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if thinking is not None:
            think_obj: dict[str, Any] = {"type": "enabled" if thinking else "disabled"}
            if clear_thinking is not None:
                think_obj["clear_thinking"] = clear_thinking
            body["thinking"] = think_obj
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _post(self, body: dict, stream: bool = False) -> Any:
        """POST with retries on transient connection errors.

        Phase 17 P14: 长任务 run 中任何一次 LLM 网络闪断（URLError /
        ConnectionError / Timeout）都会导致整个 run 失败。对连接类错误
        自动重试（指数退避），HTTP 4xx/5xx 不重试（服务端明确拒绝）。
        """
        import time as _time
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        max_retries = 3
        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                if stream:
                    return resp  # return the file-like object for SSE iteration
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8")
                except Exception:
                    pass
                logger.error("LLM HTTP %s: %s", e.code, error_body[:500])
                raise RuntimeError(f"LLM API error {e.code}: {error_body[:300]}") from e
            except urllib.error.URLError as e:
                last_err = e
                logger.warning("LLM connection error (attempt %s/%s): %s",
                               attempt + 1, max_retries, e.reason)
            except (ConnectionError, TimeoutError, OSError) as e:  # noqa: BLE001
                last_err = e
                logger.warning("LLM connection error (attempt %s/%s): %s",
                               attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                _time.sleep(2.0 * (attempt + 1))  # 2s / 4s backoff
        raise RuntimeError(f"LLM connection error: {last_err}") from last_err

    def _iter_sse_chunks(self, response) -> Any:
        """Iterate SSE lines from a streaming urllib response."""
        buffer = b""
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                yield line.decode("utf-8", errors="replace")

    def _parse_stream_chunk(self, line: str) -> dict:
        """Parse a single SSE line into a delta dict.

        Returns keys: delta, reasoning_delta, tool_call_delta, finish_reason
        """
        line = line.strip()
        if not line or not line.startswith("data: "):
            return {"delta": "", "reasoning_delta": "", "tool_call_delta": None, "finish_reason": None}
        data_str = line[6:]
        if data_str == "[DONE]":
            return {"delta": "", "reasoning_delta": "", "tool_call_delta": None, "finish_reason": "stop"}
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return {"delta": "", "reasoning_delta": "", "tool_call_delta": None, "finish_reason": None}
        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        finish = choice.get("finish_reason")
        text = delta.get("content", "")
        reasoning = delta.get("reasoning_content", "")  # DeepSeek reasoning tokens
        tc_deltas = delta.get("tool_calls")
        tc_result = None
        if tc_deltas:
            # Accumulate tool call deltas across chunks
            tc_result = [
                {
                    "index": tc.get("index", 0),
                    "id": tc.get("id"),
                    "name": (tc.get("function") or {}).get("name"),
                    "arguments": (tc.get("function") or {}).get("arguments", ""),
                }
                for tc in tc_deltas
            ]
        # Phase 16 P1-D: streaming usage (usually the final chunk carries it)
        usage = data.get("usage")
        usage_out = None
        if usage:
            usage_out = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
            }
        return {
            "delta": text or "",
            "reasoning_delta": reasoning or "",
            "tool_call_delta": tc_result,
            "finish_reason": finish,
            "usage": usage_out,
        }

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> LLMClient:
        """Create an LLMClient from environment variables.

        Reads:
          - LLM_API_URL or OPENAI_BASE_URL: API base URL
          - LLM_API_KEY or OPENAI_API_KEY: API key
          - LLM_MODEL or OPENAI_MODEL: default model name
        """
        import os
        api_url = os.environ.get("LLM_API_URL") or os.environ.get("OPENAI_BASE_URL") or "http://127.0.0.1:11434/v1"
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        model = os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o"
        return cls(api_url=api_url, api_key=api_key, model=model)
