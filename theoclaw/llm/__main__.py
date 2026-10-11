"""Command line for the LLM settings.

    python -m theoclaw.llm show                 roles, providers, models and prices; which keys are set
    python -m theoclaw.llm ping                 one tiny call per role (costs a fraction of a cent)
    python -m theoclaw.llm ping agent compile   only these roles
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from ..common.pricing import price_for
from .client import api_key
from .config import ROLES, load_llm_config, role


def cmd_show() -> None:
    cfg = load_llm_config()
    print(f"{cfg.path} (sha {cfg.sha})\n")
    print(f"{'role':10} {'model':22} {'provider':10} {'api':9} {'effort':7} {'max_tokens':>10}  price")
    for name in cfg.roles:
        r = role(name, cfg=cfg)
        price = "yes" if price_for(r.model) else ("–" if r.model == "none" else "– (no cost in reports)")
        print(f"{name:10} {r.model:22} {r.provider.name:10} {r.provider.api:9} {r.effort or '–':7} "
              f"{r.max_tokens:>10}  {price}")
    print(f"\n{'provider':10} {'api':9} {'key variable':20} {'key set':8} endpoint")
    for p in cfg.providers.values():
        env = p.api_key_env or "–"
        is_set = "yes" if api_key(p) else ("no" if p.api_key_env else "–")
        where = p.endpoint or "(provider default)"
        if p.base_url_env and not p.base_url:
            where += f"  [from {p.base_url_env}]" if p.endpoint else f"  [{p.base_url_env} not set]"
        print(f"{p.name:10} {p.api:9} {env:20} {is_set:8} {where}")
    print(f"\ncompile model for OpenKB: {role('compile', cfg=cfg).litellm_model}")
    if os.environ.get("THEOCLAW_LLM_CONFIG"):
        print(f"(chosen by THEOCLAW_LLM_CONFIG={os.environ['THEOCLAW_LLM_CONFIG']})")


def _ping_compile() -> str:
    r = role("compile")
    if r.provider.api_key_env and not api_key(r.provider):
        raise SystemExit(f"no API key for provider {r.provider.name}: set {r.provider.api_key_env} in .env or the environment")
    try:
        import litellm
    except ImportError as e:  # litellm itself, or one of its dependencies
        raise SystemExit(f"cannot import litellm ({e}); run pip install -r requirements.txt")
    litellm.suppress_debug_info = True
    t0 = time.perf_counter()
    resp = litellm.completion(model=r.litellm_model, messages=[{"role": "user", "content": "回覆一個字：好"}],
                              max_tokens=256)
    return f"ok via LiteLLM {r.litellm_model}, {time.perf_counter() - t0:.1f}s, {resp.usage.completion_tokens} output tokens"


def _ping_tokenizer() -> str:
    from .client import token_counter
    counter, why_not = token_counter()
    if counter is None:
        return f"skipped: {why_not}"
    n = counter.count("約翰福音 3:16")
    return f"ok, {counter.model}: 「約翰福音 3:16」 = {n} tokens (count_tokens is free)"


def _ping_chat(name: str) -> str:
    from .complete import complete
    c = complete("回覆一個字：好", role=name, effort="low", max_tokens=256)
    cost = f", ${c.cost_usd:.5f}" if c.cost_usd is not None else ""
    return (f"ok, {c.model} via {c.provider}, {c.latency_s:.1f}s, stop {c.stop_reason}, "
            f"{c.usage['output_tokens']} output tokens{cost}")


def cmd_ping(roles: list[str]) -> None:
    load_llm_config()
    failed = 0
    for name in roles or list(ROLES):
        try:
            if name == "compile":
                msg = _ping_compile()
            elif name == "tokenizer":
                msg = _ping_tokenizer()
            else:
                msg = _ping_chat(name)
        except SystemExit as e:
            msg, failed = f"FAILED: {e}", failed + 1
        except Exception as e:
            msg, failed = f"FAILED: {type(e).__name__}: {e}", failed + 1
        print(f"{name:10} {msg}")
    if failed:
        raise SystemExit(1)


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="theoclaw.llm", description="the LLM settings in config/llm.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="roles, providers, models; which API keys are set (never their values)")
    p = sub.add_parser("ping", help="one tiny model call per role, to check the models and keys work")
    p.add_argument("roles", nargs="*", metavar="ROLE", help=f"default: all ({', '.join(ROLES)})")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        cmd_show()
    else:
        unknown = [r for r in args.roles if r not in ROLES]
        if unknown:
            raise SystemExit(f"unknown roles {unknown}; roles: {list(ROLES)}")
        cmd_ping(args.roles)


if __name__ == "__main__":
    main()
