import json

import pytest

from theoclaw.agent import __main__ as agent_cli
from theoclaw.agent.loop import effective_effort
from theoclaw.agent.prompt import SYSTEM_PROMPT, system_prompt
from theoclaw.common.pricing import cost, price_for, prompt_tokens


def test_prompt_rules_follow_tool_groups():
    assert SYSTEM_PROMPT == system_prompt(["scripture", "wesley"])
    assert "lookup_verse" in SYSTEM_PROMPT and "6. " in SYSTEM_PROMPT
    kb_only = system_prompt(["kb"])
    assert "lookup_verse" not in kb_only and "sources/" in kb_only
    assert "衛斯理的看法" not in system_prompt(["scripture"])


def test_prices_match_litellm_ids():
    assert price_for("anthropic/claude-sonnet-5-5") == price_for("claude-sonnet-5-5")
    assert price_for("gpt-unknown") is None
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 1_000_000}
    assert cost(usage, "claude-opus-5-5") == pytest.approx(4.0 + 2.0 + 0.2 + 5.0)
    assert prompt_tokens(usage) == 3_000_000


def test_effort_dropped_for_models_without_it():
    assert effective_effort("claude-haiku-4-5", "medium") is None
    assert effective_effort("claude-opus-5-5", "medium") == "medium"
    assert effective_effort("claude-opus-5-5", "none") is None


def test_ask_log_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_cli, "ASK_LOG", tmp_path / "ask")
    agent_cli.log_answer({"task_id": "ask-1", "run_index": 0})
    agent_cli.log_answer({"task_id": "ask-2", "run_index": 0})
    assert json.loads((tmp_path / "ask" / "config.json").read_text())["kind"] == "ask-log"
    assert len((tmp_path / "ask" / "traces.jsonl").read_text().splitlines()) == 2


def test_prompt_keeps_to_faith_and_puts_safety_first_without_local_numbers():
    import re
    prompt = system_prompt(["scripture", "wesley"])
    assert "只回答與信仰" in prompt and "寫程式" in prompt
    assert "緊急服務" in prompt and "不要寫出任何電話號碼" in prompt and "不要叫人停藥" in prompt
    from theoclaw.agent.prompt import SAFETY
    assert SAFETY in prompt and not re.search(r"\d", SAFETY)  # users are everywhere: no hotline number
