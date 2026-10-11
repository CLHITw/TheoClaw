"""One text-in, text-out model call without tools, for the LLM judge and other
single calls. Works with both kinds of provider through the same client interface:
the Anthropic SDK, or LiteLLMClient for Qwen, DeepSeek and other LiteLLM providers.

    from theoclaw.llm import complete
    c = complete("…評分標準與答案…", role="judge", system="…")
    c.text, c.usage, c.cost_usd
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..common.pricing import cost
from .client import make_client
from .config import role as get_role, supports_effort
from .usage import anthropic_usage


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    stop_reason: str | None
    usage: dict
    cost_usd: float | None
    latency_s: float


def complete(prompt: str, *, role: str = "judge", model: str | None = None, system: str | None = None,
             effort: str | None = None, max_tokens: int | None = None, client=None) -> Completion:
    r = get_role(role, model=model, effort=effort)
    client = client or make_client(provider=r.provider, params=r.params)  # Anthropic SDK or LiteLLMClient
    kwargs: dict = {"model": r.model, "max_tokens": max_tokens or r.max_tokens,
                    "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    if r.effort and supports_effort(r.model):
        kwargs["output_config"] = {"effort": r.effort}
    t0 = time.perf_counter()
    resp = client.messages.create(**kwargs)
    text = "".join(b.text for b in resp.content if b.type == "text")
    usage = anthropic_usage(resp.usage)
    return Completion(text, r.model, r.provider.name, resp.stop_reason, usage, cost(usage, r.model),
                      time.perf_counter() - t0)
