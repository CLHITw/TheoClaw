"""Usage records in the Anthropic field names, from either SDK.

``input_tokens`` is only the uncached part of the prompt; the whole prompt is
input + cache write + cache read (common.pricing.prompt_tokens).
"""

from __future__ import annotations

from typing import Any

from ..common.pricing import USAGE_KEYS


def get_field(obj, name):
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def anthropic_usage(usage: Any) -> dict:
    return {k: int(get_field(usage, k) or 0) for k in USAGE_KEYS}


def normalize_litellm_usage(usage) -> dict:
    """LiteLLM usage -> Anthropic field names. For Anthropic models LiteLLM's
    prompt_tokens already includes cache writes and cache reads; input_tokens here is
    the uncached rest, as in the Anthropic API."""
    prompt = int(get_field(usage, "prompt_tokens") or 0)
    write = int(get_field(usage, "cache_creation_input_tokens") or 0)
    read = get_field(usage, "cache_read_input_tokens")
    if read is None:
        read = get_field(get_field(usage, "prompt_tokens_details"), "cached_tokens")
    read = int(read or 0)
    return {"input_tokens": max(0, prompt - write - read), "output_tokens": int(get_field(usage, "completion_tokens") or 0),
            "cache_creation_input_tokens": write, "cache_read_input_tokens": read}
