"""All LLM access in one place: which provider, model and settings each role uses.

Settings live in config/llm.yaml (roles, providers, models with prices); API keys
live in .env or the environment, never in the YAML. Every other module asks this
package for its model and client instead of hard-coding them:

    role("agent")       the assistant that answers questions of faith (ask, evals, experiments)
    role("kb_query")    kb.query ask: answers from a wiki alone
    role("compile")     kb.compile build: OpenKB compiles the wiki through LiteLLM
    role("judge")       the LLM judge (phase 2), through complete(role="judge")
    role("tokenizer")   token counts (the free count_tokens endpoint)

    python -m theoclaw.llm show     the settings, and which keys are set
    python -m theoclaw.llm ping     one tiny call per role, to check models and keys
"""

from .client import api_key, make_client, token_counter
from .complete import Completion, complete
from .config import (ROLES, LLMConfig, Provider, Role, litellm_id, load_llm_config, resolve, role,
                     supports_effort)
from .env import load_env
from .litellm_client import LiteLLMClient, ProviderAPIError
from .usage import anthropic_usage, normalize_litellm_usage

__all__ = ["ROLES", "Completion", "LLMConfig", "Provider", "Role", "anthropic_usage", "api_key", "complete",
           "LiteLLMClient", "ProviderAPIError", "litellm_id", "load_env", "load_llm_config", "make_client", "normalize_litellm_usage", "resolve", "role",
           "supports_effort", "token_counter"]
