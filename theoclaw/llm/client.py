"""API clients for the agent loop and single calls.

A provider with `api: anthropic` gets the Anthropic SDK client (Claude, or any
Anthropic-compatible endpoint). A provider with `api: litellm` (Qwen on DashScope,
DeepSeek, ...) gets a LiteLLMClient with the same messages.create(), so the agent loop
runs unchanged on either.
"""

from __future__ import annotations

import os

from .config import Provider, load_llm_config, resolve, role as get_role
from .env import load_env


def api_key(provider: Provider) -> str | None:
    load_env()
    return os.environ.get(provider.api_key_env) if provider.api_key_env else None


def make_client(model: str | None = None, *, role: str = "agent", provider: Provider | None = None,
                params: dict | None = None, max_retries: int = 4, timeout: float = 600):
    """A client for the provider of `model` (default: the role's provider). params are the
    model's provider-specific request parameters (Role.params)."""
    cfg = load_llm_config()
    if provider is None:
        if model:
            provider = resolve(model)[0]
            params = params if params is not None else dict((cfg.models.get(resolve(model)[1]) or {}).get("params") or {})
        else:
            r = get_role(role)
            provider, params = r.provider, r.params if params is None else params
    key = api_key(provider)
    if key is None and provider.name != "anthropic" and provider.api_key_env:
        # Only the first-party Anthropic API falls back to an `ant auth login` profile.
        raise SystemExit(f"no API key for provider {provider.name}: set {provider.api_key_env} in .env or the environment")
    if provider.api == "litellm":
        from .litellm_client import LiteLLMClient
        return LiteLLMClient(provider, key, params, timeout=timeout, max_retries=max_retries)
    import anthropic
    kwargs: dict = {"max_retries": max_retries, "timeout": timeout}
    if key:
        kwargs["api_key"] = key
    if provider.endpoint:
        kwargs["base_url"] = provider.endpoint
    return anthropic.Anthropic(**kwargs)


def token_counter(model: str | None = None):
    """(TokenCounter, None), or (None, why not). Exact counts need the Anthropic
    count_tokens endpoint; other providers have no free equivalent, so commands that
    count tokens fall back to characters, and real token use comes from each run's usage."""
    from ..common.tokens import TokenCounter
    r = get_role("tokenizer", model=model)
    if r.model in ("none", ""):
        return None, "tokenizer role is none in config/llm.yaml; characters only. Real token use is in each run's usage."
    if r.provider.api != "anthropic":
        return None, (f"no free token counting for {r.provider.name}/{r.model} (tokenizer role in config/llm.yaml); "
                      f"characters only. Real token use is in each run's usage.")
    return TokenCounter(make_client(provider=r.provider), r.model), None
