"""The agent loop, written by hand on purpose: no framework hides the control flow.

messages -> messages.create(tools=...) -> if stop_reason == "tool_use": run every
tool_use block, send all tool_results back in ONE user message -> repeat.

Every model call and every tool call is recorded in a trace, because what is not
recorded cannot be graded or debugged.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..common import zh
from ..common.tooling import Handler, ToolError
from ..llm import ProviderAPIError, anthropic_usage, supports_effort
from .prompt import SYSTEM_PROMPT
from .quotes import fill_placeholders, scrub_internal
from .tools import TOOL_DEFS


def effective_effort(model: str, effort: str | None) -> str | None:
    """The effort to send: none for models marked `effort: false` in config/llm.yaml (they reject it)."""
    if effort in (None, "none") or not supports_effort(model):
        return None
    return effort


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict
    output: str
    is_error: bool
    latency_s: float
    exception: str | None = None  # set when a handler crashed (a harness bug, not an agent failure)


@dataclass
class Step:
    index: int
    latency_s: float
    stop_reason: str | None
    usage: dict
    content: list[dict]
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class AgentRun:
    model: str
    prompt: str
    final_text: str = ""
    outcome: str = "completed"  # completed | max_steps | max_tokens | refusal | api_error
    stop_reason: str | None = None
    steps: list[Step] = field(default_factory=list)
    faults: list[dict] = field(default_factory=list)
    latency_s: float = 0.0
    error: str | None = None
    # The answer is shown in 繁體: Simplified characters the model wrote are converted, and
    # its own text is kept here so reports can still count how often it slipped.
    simplified_fixed: list[str] = field(default_factory=list)
    model_text: str | None = None  # the model's answer before placeholders and conversion, when it changed

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [c for s in self.steps for c in s.tool_calls]

    def usage_total(self) -> dict:
        total: dict[str, int] = {}
        for s in self.steps:
            for k, v in s.usage.items():
                total[k] = total.get(k, 0) + (v or 0)
        return total

    def to_dict(self) -> dict:
        d = asdict(self)
        d["usage_total"] = self.usage_total()
        return d


def _block_dict(block: Any) -> dict:
    d = block.model_dump(mode="json", exclude_none=True) if hasattr(block, "model_dump") else dict(block)
    d.pop("signature", None)  # opaque and large; not useful in a trace
    return d


def _is_api_error(e: Exception) -> bool:
    if isinstance(e, ProviderAPIError):  # Qwen, DeepSeek and other LiteLLM providers
        return True
    try:
        import anthropic
    except ImportError:
        return False
    return isinstance(e, anthropic.APIError)


def _execute(block: Any, handlers: dict[str, Handler]) -> ToolCall:
    start = time.perf_counter()
    inp = dict(block.input or {})
    exception = None
    handler = handlers.get(block.name)
    if handler is None:
        output, is_error = f"未知的工具：{block.name}", True
    else:
        try:
            output, is_error = handler(inp), False
        except ToolError as e:
            output, is_error = str(e), True
        except Exception as e:  # a bug in our own tool code
            output, is_error = "工具內部錯誤", True
            exception = f"{type(e).__name__}: {e}"
    return ToolCall(id=block.id, name=block.name, input=inp, output=output, is_error=is_error,
                    latency_s=time.perf_counter() - start, exception=exception)


def run_agent(
    client: Any,
    prompt: str,
    *,
    model: str,
    handlers: dict[str, Handler],
    injector: Any = None,  # an object with .wrap(handlers) and .log (evals.faults.FaultInjector)
    system: str = SYSTEM_PROMPT,
    tools: list[dict] | None = None,
    effort: str | None = "medium",
    max_tokens: int = 16000,
    max_steps: int = 12,
    fix_simplified: bool = True,
    fill_quotes: bool = True,
) -> AgentRun:
    run = AgentRun(model=model, prompt=prompt)
    if injector is not None:
        handlers = injector.wrap(handlers)
    messages: list[dict] = [{"role": "user", "content": prompt}]
    effort = effective_effort(model, effort)
    extra: dict = {"output_config": {"effort": effort}} if effort else {}
    t_run = time.perf_counter()
    try:
        for index in range(max_steps):
            t0 = time.perf_counter()
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools if tools is not None else TOOL_DEFS,
                messages=messages,
                cache_control={"type": "ephemeral"},  # system + tools are identical on every call
                **extra,
            )
            step = Step(index=index, latency_s=time.perf_counter() - t0,
                        stop_reason=response.stop_reason, usage=anthropic_usage(response.usage),
                        content=[_block_dict(b) for b in response.content])
            run.steps.append(step)
            run.stop_reason = response.stop_reason
            # Append the assistant turn unchanged (thinking blocks must be passed back as-is).
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    call = _execute(block, handlers)
                    step.tool_calls.append(call)
                    result: dict = {"type": "tool_result", "tool_use_id": call.id}
                    if call.output:
                        result["content"] = call.output
                    if call.is_error:
                        result["is_error"] = True
                    results.append(result)
                messages.append({"role": "user", "content": results})  # all results in one message
                continue
            if response.stop_reason == "pause_turn":
                continue

            model_text = run.final_text = "".join(b.text for b in response.content if b.type == "text")
            if fix_simplified:  # first, so a placeholder written with a Simplified 經 is still found
                fixed, run.simplified_fixed = zh.fix_simplified(run.final_text)
                if run.simplified_fixed:
                    run.final_text = fixed
            if fill_quotes:
                run.final_text, fills = fill_placeholders(run.final_text, handlers)
                step.tool_calls.extend(fills)
                run.final_text, _ = scrub_internal(run.final_text)
            if run.final_text != model_text:
                run.model_text = model_text
            if response.stop_reason in ("max_tokens", "refusal"):
                run.outcome = response.stop_reason
            break
        else:
            run.outcome = "max_steps"
    except Exception as e:
        if not _is_api_error(e):
            raise  # a bug in this harness should stop the batch, not hide as a failed run
        # API errors that survived the SDK's own retries are recorded, not raised.
        run.outcome, run.error = "api_error", f"{type(e).__name__}: {e}"
    run.latency_s = time.perf_counter() - t_run
    if injector is not None:
        run.faults = list(injector.log)
    return run
