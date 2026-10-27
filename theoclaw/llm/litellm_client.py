"""The agent loop on any LiteLLM provider (Qwen on DashScope, DeepSeek, ...).

The loop speaks the Anthropic Messages format. This client offers the same
`messages.create(...)` and translates each call to an OpenAI-format chat
completion through LiteLLM, then translates the answer back:

    Anthropic side (the loop)            OpenAI side (LiteLLM)
    system="..."                         {"role": "system"}
    tools=[{name, input_schema}]         tools=[{"type": "function", function: {name, parameters}}]
    assistant: thinking, text, tool_use  assistant: reasoning_content, content, tool_calls
    user: [tool_result, ...]             one {"role": "tool"} message per result
    stop_reason tool_use / end_turn /    finish_reason tool_calls / stop /
                max_tokens / refusal                   length / content_filter

Thinking text is kept and sent back as reasoning_content: DeepSeek's thinking mode
returns a 400 when it is missing from a tool-calling conversation.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .config import Provider
from .usage import get_field, normalize_litellm_usage

STOP_REASONS = {"tool_calls": "tool_use", "function_call": "tool_use", "stop": "end_turn",
                "length": "max_tokens", "content_filter": "refusal"}
ERROR_PREFIX = "工具錯誤："  # OpenAI tool messages have no is_error flag
# Worth another try: busy (429), the provider's own failures (5xx), a dropped connection, a timeout.
# A wrong key or a bad request fails the same way every time, so it is not retried.
RETRYABLE = {"RateLimitError", "InternalServerError", "ServiceUnavailableError", "BadGatewayError",
             "APIConnectionError", "APITimeoutError", "Timeout"}
RETRY_DELAYS = (2, 5, 10)  # seconds before each retry


class ProviderAPIError(Exception):
    """An error from a LiteLLM provider (auth, rate limit, timeout, bad request), recorded
    by the agent loop as an api_error outcome, like anthropic.APIError."""


@dataclass
class Block:
    type: str
    text: str | None = None
    thinking: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None

    def model_dump(self, mode: str | None = None, exclude_none: bool = False) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None} if exclude_none else d


@dataclass
class Response:
    id: str | None
    model: str
    content: list[Block]
    stop_reason: str | None
    usage: dict = field(default_factory=dict)


def _attr(obj: Any, name: str, default=None):
    v = get_field(obj, name)
    return default if v is None else v


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}}
            for t in tools]


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if _attr(b, "type") == "text":
            parts.append(_attr(b, "text", ""))
    return "".join(parts)


def to_openai_messages(system: str | None, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        role, content = m["role"], m["content"]
        if role == "assistant":
            blocks = [content] if isinstance(content, str) else list(content)
            msg: dict = {"role": "assistant", "content": _text_of(content) if not isinstance(content, str) else content}
            thinking = "".join(_attr(b, "thinking", "") for b in blocks if _attr(b, "type") == "thinking")
            if thinking:
                msg["reasoning_content"] = thinking
            calls = [{"id": _attr(b, "id"), "type": "function",
                      "function": {"name": _attr(b, "name"), "arguments": json.dumps(_attr(b, "input", {}), ensure_ascii=False)}}
                     for b in blocks if _attr(b, "type") == "tool_use"]
            if calls:
                msg["tool_calls"] = calls
                msg["content"] = msg["content"] or None  # some providers reject "" next to tool calls
            out.append(msg)
            continue
        if isinstance(content, str):
            out.append({"role": "user", "content": content})
            continue
        texts = []
        for b in content:
            if _attr(b, "type") == "tool_result":
                body = _attr(b, "content", "")
                body = body if isinstance(body, str) else _text_of(body)
                out.append({"role": "tool", "tool_call_id": _attr(b, "tool_use_id"),
                            "content": (ERROR_PREFIX + body) if _attr(b, "is_error") else body})
            elif _attr(b, "type") == "text":
                texts.append(_attr(b, "text", ""))
        if texts:
            out.append({"role": "user", "content": "".join(texts)})
    return out


def from_openai_response(resp: Any, model: str) -> Response:
    choice = _attr(resp, "choices")[0]
    message = _attr(choice, "message")
    blocks: list[Block] = []
    reasoning = _attr(message, "reasoning_content") or _attr(_attr(message, "provider_specific_fields", {}),
                                                           "reasoning_content")
    if reasoning:
        blocks.append(Block("thinking", thinking=reasoning))
    text = _attr(message, "content")
    if text:
        blocks.append(Block("text", text=text))
    calls = _attr(message, "tool_calls") or []
    for call in calls:
        fn = _attr(call, "function")
        raw = _attr(fn, "arguments", "") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except json.JSONDecodeError:
            args = {"_unparsed_arguments": raw}  # the tool handler reports the bad input to the model
        blocks.append(Block("tool_use", id=_attr(call, "id"), name=_attr(fn, "name"), input=args))
    finish = _attr(choice, "finish_reason")
    stop = "tool_use" if calls else STOP_REASONS.get(finish, finish)
    return Response(_attr(resp, "id"), model, blocks, stop, normalize_litellm_usage(_attr(resp, "usage")))


class LiteLLMClient:
    """An object with .messages.create(...) like anthropic.Anthropic, backed by LiteLLM."""

    def __init__(self, provider: Provider, api_key: str | None = None, params: dict | None = None,
                 timeout: float = 600, max_retries: int = 4, completion=None, retry_delays=RETRY_DELAYS):
        self.provider, self.api_key, self.params = provider, api_key, dict(params or {})
        self.timeout, self.max_retries = timeout, max_retries
        self.retry_delays = tuple(retry_delays)[:max_retries]
        self._completion = completion  # injectable for tests
        self.messages = self

    def create(self, *, model: str, max_tokens: int, messages: list[dict], system: str | None = None,
               tools: list[dict] | None = None, tool_choice: dict | None = None, **_ignored) -> Response:
        # Ignored: cache_control (DashScope and DeepSeek cache prompts on their own) and
        # output_config (thinking is set through the model's params in config/llm.yaml).
        completion = self._completion
        if completion is None:
            import litellm  # pip install litellm (also installed with openkb)
            litellm.suppress_debug_info = True  # no "Give Feedback" banners on every error
            completion = litellm.completion
        # Retries are done here: LiteLLM passes max_retries on to the HTTP client for some providers
        # only (a DeepSeek 429 or 500 was tried once), and its num_retries needs the tenacity package.
        kwargs: dict = {"model": f"{self.provider.prefix}/{model}", "messages": to_openai_messages(system, messages),
                        "max_tokens": max_tokens, "timeout": self.timeout, "max_retries": 0}
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
            if tool_choice and tool_choice.get("type") == "none":  # the last step: answer, no more tool calls
                kwargs["tool_choice"] = "none"
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.provider.endpoint:
            kwargs["api_base"] = self.provider.endpoint
        kwargs.update(self.params)
        for attempt in range(len(self.retry_delays) + 1):
            try:
                resp = completion(**kwargs)
                break
            except Exception as e:
                if not (type(e).__module__.startswith("litellm") or type(e).__module__.startswith("openai")):
                    raise
                if type(e).__name__ not in RETRYABLE or attempt == len(self.retry_delays):
                    raise ProviderAPIError(f"{type(e).__name__}: {e}") from e
                time.sleep(self.retry_delays[attempt])
        return from_openai_response(resp, model)
