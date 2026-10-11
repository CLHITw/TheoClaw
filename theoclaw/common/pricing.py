"""Token prices (the models table in config/llm.yaml) and the cost of one usage record.

Usage records use the Anthropic field names. ``input_tokens`` is only the uncached
part of the prompt; the whole prompt is input + cache write + cache read.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .paths import llm_config_path

PRICE_KEYS = ("input", "output", "cache_read", "cache_write")
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


@lru_cache(maxsize=8)
def _prices(path: str) -> dict[str, dict]:
    models = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("models") or {}
    return {name: {k: float(spec[k]) for k in PRICE_KEYS}
            for name, spec in models.items() if spec and all(k in spec for k in PRICE_KEYS)}


def load_prices(path: Path | str | None = None) -> dict[str, dict]:
    """Models that have all four prices in the LLM settings."""
    return _prices(str(path or llm_config_path()))


def price_for(model: str) -> dict | None:
    """Prices for a model id; a LiteLLM id such as dashscope/qwen3.8-flash also matches."""
    prices = load_prices()
    for key in (model, model.split("/", 1)[-1]):
        if key in prices:
            return prices[key]
    return None


def cost(usage: dict, model: str) -> float | None:
    p = price_for(model)
    if p is None:
        return None
    return (usage.get("input_tokens", 0) * p["input"] + usage.get("output_tokens", 0) * p["output"]
            + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
            + usage.get("cache_creation_input_tokens", 0) * p["cache_write"]) / 1e6


def prompt_tokens(usage: dict) -> int:
    """The whole prompt, cached or not."""
    return (usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0))


def add_usage(total: dict, usage: dict) -> dict:
    for k in USAGE_KEYS:
        total[k] = total.get(k, 0) + int(usage.get(k, 0) or 0)
    return total
