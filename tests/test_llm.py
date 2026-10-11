"""The LLM settings (config/llm.yaml), clients and single completions, without API calls."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

from theoclaw.common.paths import TASKS_DIR
from theoclaw.common.pricing import price_for
from theoclaw.agent.loop import run_agent
from theoclaw.agent.tools import build_tool_set
from theoclaw.llm import (LiteLLMClient, Provider, complete, litellm_id, load_env, load_llm_config, make_client, resolve,
                          role, supports_effort, token_counter)
from theoclaw.llm.__main__ import main as llm_main

CUSTOM = """
default_provider: anthropic
providers:
  anthropic: {api: anthropic, api_key_env: ANTHROPIC_API_KEY, litellm_prefix: anthropic}
  proxy: {api: anthropic, api_key_env: THEO_TEST_PROXY_KEY, base_url: "https://proxy.example.test"}
  deepseek: {api: litellm, api_key_env: THEO_TEST_DEEPSEEK_KEY, base_url_env: THEO_TEST_DEEPSEEK_BASE, litellm_prefix: deepseek}
models:
  claude-opus-5-5: {input: 4.0, output: 20.0, cache_read: 0.2, cache_write: 5.0}
  proxy-model: {provider: proxy}
  deepseek-chat: {provider: deepseek, input: 0.5, output: 1.0, cache_read: 0.1, cache_write: 0.5,
                  params: {extra_body: {thinking: {type: enabled}}}}
roles:
  agent: {model: proxy-model, effort: medium}
  kb_query: {model: claude-opus-5-5}
  compile: {model: deepseek-chat}
  judge: {model: deepseek-chat, max_tokens: 500}
  tokenizer: {model: claude-opus-5-5}
"""


@pytest.fixture
def custom(tmp_path, monkeypatch):
    path = tmp_path / "llm.yaml"
    path.write_text(CUSTOM, encoding="utf-8")
    monkeypatch.setenv("THEOCLAW_LLM_CONFIG", str(path))
    return path


def test_default_settings():
    cfg = load_llm_config()
    assert set(cfg.roles) >= {"agent", "kb_query", "compile", "judge", "tokenizer"}
    agent = role("agent")
    assert (agent.model, agent.provider.name, agent.provider.api) == ("deepseek-flash", "deepseek", "litellm")
    assert agent.params == {"extra_body": {"thinking": {"type": "enabled"}}}
    assert role("compile").litellm_model == "dashscope/qwen3.8-max"
    assert role("judge").provider.name != agent.provider.name  # another vendor than the agent
    assert not supports_effort("qwen3.8-max")  # LiteLLM providers never get the Anthropic effort parameter
    assert not supports_effort("claude-haiku-4-5") and supports_effort("claude-opus-5-5")
    assert price_for("qwen3.8-max")["output"] == 4.951 and price_for("deepseek/deepseek-flash")["cache_read"] == 0.006
    assert token_counter()[0] is None  # no free count_tokens outside Anthropic


def test_overrides_and_litellm_ids():
    r = role("agent", model="anthropic/claude-haiku-4-5", effort="none")
    assert (r.model, r.provider.name, r.effort) == ("claude-haiku-4-5", "anthropic", None)
    assert role("agent", effort="low").effort == "low"
    assert litellm_id("claude-sonnet-5-5") == "anthropic/claude-sonnet-5-5"
    prov, name = resolve("someservice/some-model")  # a LiteLLM provider not in the file
    assert (prov.api, prov.prefix, name) == ("litellm", "someservice", "some-model")
    assert resolve("unknown-model-9")[0].name == load_llm_config().default_provider


def test_custom_file_providers_and_clients(custom, monkeypatch):
    assert role("judge").provider.name == "deepseek" and role("judge").max_tokens == 500
    assert role("compile").litellm_model == "deepseek/deepseek-chat"
    assert price_for("deepseek-chat")["input"] == 0.5
    monkeypatch.delenv("THEO_TEST_PROXY_KEY", raising=False)
    with pytest.raises(SystemExit, match="THEO_TEST_PROXY_KEY"):
        make_client(role="agent")  # a non-Anthropic endpoint needs its key
    monkeypatch.setenv("THEO_TEST_PROXY_KEY", "test-key")
    client = make_client(role="agent")
    assert "proxy.example.test" in str(client.base_url) and client.api_key == "test-key"
    monkeypatch.setenv("THEO_TEST_DEEPSEEK_KEY", "ds-key")
    monkeypatch.setenv("THEO_TEST_DEEPSEEK_BASE", "https://deepseek.example.test")
    judge = make_client(role="judge")  # a LiteLLM provider gets the translating client
    assert isinstance(judge, LiteLLMClient) and judge.api_key == "ds-key"
    assert judge.provider.endpoint == "https://deepseek.example.test"
    assert judge.params == {"extra_body": {"thinking": {"type": "enabled"}}}


def test_load_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# keys\nTHEO_TEST_A=one\nexport THEO_TEST_B=\"two\"\nTHEO_TEST_C=from-file\nTHEO_TEST_EMPTY=\n",
                   encoding="utf-8")
    monkeypatch.setenv("THEO_TEST_C", "from-shell")
    try:
        assert sorted(load_env(env)) == ["THEO_TEST_A", "THEO_TEST_B"]
        assert os.environ["THEO_TEST_A"] == "one" and os.environ["THEO_TEST_B"] == "two"
        assert os.environ["THEO_TEST_C"] == "from-shell"  # the shell wins
        assert load_env(env) == []  # read once
    finally:
        for k in ("THEO_TEST_A", "THEO_TEST_B"):
            os.environ.pop(k, None)


class FakeAnthropic:
    def __init__(self):
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=0,
                                cache_read_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="通過")], stop_reason="end_turn", usage=usage)


def test_complete_with_the_anthropic_sdk():
    fake = FakeAnthropic()
    c = complete("請評分", role="judge", model="claude-opus-5-5", effort="high", system="你是裁判", client=fake)
    assert c.text == "通過" and c.provider == "anthropic" and c.model == "claude-opus-5-5"
    assert fake.kwargs["output_config"] == {"effort": "high"} and fake.kwargs["system"] == "你是裁判"
    assert c.cost_usd == pytest.approx((1000 * 4 + 100 * 20) / 1e6)
    complete("請評分", role="judge", model="claude-haiku-4-5", effort="high", client=fake)
    assert "output_config" not in fake.kwargs  # Haiku 4.5 rejects effort


def test_complete_through_litellm(custom, monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        usage = {"prompt_tokens": 200, "completion_tokens": 20}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="不通過"), finish_reason="stop")],
                               usage=usage)

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    monkeypatch.setenv("THEO_TEST_DEEPSEEK_KEY", "ds-key")
    c = complete("請評分", role="judge", system="你是裁判")
    assert c.text == "不通過" and c.provider == "deepseek"
    assert calls[0]["model"] == "deepseek/deepseek-chat" and calls[0]["api_key"] == "ds-key"
    assert calls[0]["messages"][0] == {"role": "system", "content": "你是裁判"} and calls[0]["max_tokens"] == 500
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}  # the model's params
    assert c.usage["input_tokens"] == 200 and c.cost_usd == pytest.approx((200 * 0.5 + 20 * 1.0) / 1e6)


def test_show_prints_settings_without_keys(capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-never-be-printed")
    llm_main(["show"])
    out = capsys.readouterr().out
    assert "qwen3.8-flash" in out and "dashscope/qwen3.8-max" in out
    assert "sk-should-never-be-printed" not in out


def test_eval_runs_record_the_llm_settings(tmp_path):
    from theoclaw.evals.runner import run_tasks
    run_dir = run_tasks(TASKS_DIR / "tasks.example.yaml", model="fake-honest", n=1, workers=1, out_root=tmp_path)
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    assert config["llm"]["provider"] == "fake" and config["llm"]["model"] == "fake-honest"


def _openai_reply(message: dict, finish: str) -> dict:
    return {"id": "r", "choices": [{"message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 30, "prompt_tokens_details": {"cached_tokens": 100}}}


def test_agent_loop_through_the_litellm_client():
    """Qwen/DeepSeek path: tools, tool results and reasoning are translated both ways."""
    requests = []
    replies = [
        _openai_reply({"role": "assistant", "content": None, "reasoning_content": "先查經文。",
                       "tool_calls": [{"id": "call_1", "type": "function", "function": {
                           "name": "lookup_verse", "arguments": json.dumps({"reference": "約翰福音 3:16", "version": "cuv"})}},
                                      {"id": "call_2", "type": "function", "function": {
                           "name": "lookup_verse", "arguments": "{not json"}}]}, "tool_calls"),
        _openai_reply({"role": "assistant", "content": "神愛世人（約翰福音 3:16）"}, "stop"),
    ]

    def completion(**kwargs):
        requests.append(json.loads(json.dumps(kwargs, ensure_ascii=False)))
        return replies.pop(0)

    ts = build_tool_set("scripture,wesley")
    provider = Provider("deepseek", api="litellm", litellm_prefix="deepseek", base_url="https://example.test/v1")
    client = LiteLLMClient(provider, "k", {"extra_body": {"thinking": {"type": "enabled"}}}, completion=completion)
    run = run_agent(client, "約翰福音 3:16 說什麼？", model="deepseek-flash", handlers=ts.handlers, tools=ts.defs,
                    system=ts.system, effort="medium")
    assert run.outcome == "completed" and run.final_text == "神愛世人（約翰福音 3:16）"
    assert [(c.name, c.is_error) for c in run.tool_calls] == [("lookup_verse", False), ("lookup_verse", True)]
    assert run.steps[0].content[0] == {"type": "thinking", "thinking": "先查經文。"}
    assert run.usage_total()["cache_read_input_tokens"] == 200 and run.usage_total()["input_tokens"] == 400

    first, second = requests
    assert first["model"] == "deepseek/deepseek-flash" and first["api_base"] == "https://example.test/v1"
    assert first["messages"][0]["role"] == "system" and first["tools"][0]["type"] == "function"
    assert first["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "output_config" not in first and "cache_control" not in first
    assistant = second["messages"][2]
    assert assistant["reasoning_content"] == "先查經文。" and assistant["content"] is None  # DeepSeek needs it back
    assert [m["role"] for m in second["messages"][3:]] == ["tool", "tool"]
    assert second["messages"][4]["content"].startswith("工具錯誤：")


def test_litellm_errors_are_api_errors():
    LiteLLMError = type("RateLimitError", (Exception,), {"__module__": "litellm.exceptions"})

    def completion(**kwargs):
        raise LiteLLMError("429 too many requests")

    ts = build_tool_set("scripture")
    client = LiteLLMClient(Provider("dashscope", api="litellm"), "k", completion=completion)
    run = run_agent(client, "q", model="qwen3.8-max", handlers=ts.handlers, tools=ts.defs, system=ts.system)
    assert run.outcome == "api_error" and "429" in run.error
