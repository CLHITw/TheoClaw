"""config/llm.yaml: roles, providers and models (with prices).

A role names a model; the model's entry in `models` names its provider (or the
default provider) and any provider-specific request parameters. `--model` on the
command line replaces a role's model, and a LiteLLM-style id such as
dashscope/qwen3.8-flash also names its provider.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..common.paths import llm_config_path
from .env import load_env

ROLES = ("agent", "kb_query", "compile", "judge", "tokenizer")
APIS = ("anthropic", "litellm")


@dataclass(frozen=True)
class Provider:
    name: str
    api: str = "anthropic"
    api_key_env: str | None = None
    base_url: str | None = None
    base_url_env: str | None = None   # read the endpoint from this variable (e.g. in .env)
    litellm_prefix: str | None = None

    @property
    def prefix(self) -> str:
        return self.litellm_prefix or self.name

    @property
    def endpoint(self) -> str | None:
        """base_url, else the variable named by base_url_env, else None (the provider's default)."""
        if self.base_url:
            return self.base_url
        if self.base_url_env:
            return os.environ.get(self.base_url_env) or None
        return None


@dataclass(frozen=True)
class Role:
    name: str
    model: str
    provider: Provider
    effort: str | None = None
    max_tokens: int = 16000
    params: dict = field(default_factory=dict)  # provider-specific request parameters (models table)

    @property
    def litellm_model(self) -> str:
        return f"{self.provider.prefix}/{self.model}"

    def describe(self) -> dict:
        """What a run records about the model it used (no keys)."""
        return {"role": self.name, "model": self.model, "provider": self.provider.name, "api": self.provider.api,
                "endpoint": self.provider.endpoint, "effort": self.effort, "max_tokens": self.max_tokens,
                "params": self.params}


@dataclass(frozen=True)
class LLMConfig:
    path: Path
    sha: str
    default_provider: str
    providers: dict
    models: dict
    roles: dict


@lru_cache(maxsize=8)
def _load(path: str) -> LLMConfig:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"LLM settings not found: {p}")
    text = p.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    providers = {}
    for name, spec in (raw.get("providers") or {}).items():
        spec = spec or {}
        if spec.get("api", "anthropic") not in APIS:
            raise SystemExit(f"{p}: provider {name}: api must be one of {APIS}")
        providers[name] = Provider(name=name, api=spec.get("api", "anthropic"), api_key_env=spec.get("api_key_env"),
                                   base_url=spec.get("base_url"), base_url_env=spec.get("base_url_env"),
                                   litellm_prefix=spec.get("litellm_prefix"))
    default = raw.get("default_provider") or "anthropic"
    if default not in providers:
        providers.setdefault("anthropic", Provider("anthropic", api_key_env="ANTHROPIC_API_KEY",
                                                   litellm_prefix="anthropic"))
        if default not in providers:
            raise SystemExit(f"{p}: default_provider {default!r} is not under providers")
    models = {name: dict(spec or {}) for name, spec in (raw.get("models") or {}).items()}
    for name, spec in models.items():
        if spec.get("provider", default) not in providers:
            raise SystemExit(f"{p}: model {name}: provider {spec.get('provider')!r} is not under providers")
    roles = {name: dict(spec or {}) for name, spec in (raw.get("roles") or {}).items()}
    missing = [r for r in ROLES if r not in roles or not roles[r].get("model")]
    if missing:
        raise SystemExit(f"{p}: roles without a model: {missing}")
    for name, spec in roles.items():
        if spec.get("provider") and spec["provider"] not in providers:
            raise SystemExit(f"{p}: role {name}: provider {spec['provider']!r} is not under providers")
    return LLMConfig(p, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], default, providers, models, roles)


def load_llm_config(path: Path | str | None = None) -> LLMConfig:
    """The LLM settings. Loading them also reads .env into the environment (once)."""
    load_env()
    return _load(str(Path(path) if path else llm_config_path()))


def resolve(model: str, cfg: LLMConfig | None = None) -> tuple[Provider, str]:
    """The provider that serves a model id, and the bare model name."""
    cfg = cfg or load_llm_config()
    if "/" in model:
        prefix, name = model.split("/", 1)
        for prov in cfg.providers.values():
            if prov.prefix == prefix or prov.name == prefix:
                return prov, name
        # A LiteLLM provider not in the file: LiteLLM finds its key under its own variable name.
        return Provider(prefix, api="litellm", litellm_prefix=prefix), name
    spec = cfg.models.get(model) or {}
    return cfg.providers[spec.get("provider", cfg.default_provider)], model


def role(name: str, *, model: str | None = None, effort: str | None = None, cfg: LLMConfig | None = None) -> Role:
    """A role's settings, with optional overrides from the command line or an experiment arm.
    effort: None keeps the role's setting; "none" omits the parameter."""
    cfg = cfg or load_llm_config()
    if name not in cfg.roles:
        raise SystemExit(f"unknown LLM role {name!r}; roles in {cfg.path.name}: {sorted(cfg.roles)}")
    spec = cfg.roles[name]
    if model:
        provider, bare = resolve(model, cfg)
    else:
        provider, bare = resolve(str(spec["model"]), cfg)
        if spec.get("provider"):
            provider = cfg.providers[spec["provider"]]
    eff = spec.get("effort") if effort is None else effort
    eff = None if eff in (None, "none", False) else str(eff)
    params = dict((cfg.models.get(bare) or {}).get("params") or {})
    return Role(name, bare, provider, eff, int(spec.get("max_tokens", 16000)), params)


def supports_effort(model: str, cfg: LLMConfig | None = None) -> bool:
    """Whether to send the Anthropic effort parameter: not for LiteLLM providers (their
    thinking settings go in the model's params), nor for models marked `effort: false`."""
    cfg = cfg or load_llm_config()
    provider, bare = resolve(model, cfg)
    if provider.api != "anthropic":
        return False
    return (cfg.models.get(bare) or {}).get("effort", True) is not False


def litellm_id(model: str, cfg: LLMConfig | None = None) -> str:
    """provider-prefix/model, the form OpenKB and LiteLLM expect."""
    provider, bare = resolve(model, cfg)
    return f"{provider.prefix}/{bare}"
