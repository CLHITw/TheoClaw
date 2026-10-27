from dataclasses import dataclass

import httpx
import anthropic
import pytest

from theoclaw.agent.loop import run_agent
from theoclaw.evals.faults import FaultInjector, FaultSpec
from theoclaw.evals.fake import _Block, _Response, _Usage
from theoclaw.agent.tools import make_handlers


@dataclass
class Scripted:
    """Returns pre-written responses and records every request it receives."""
    responses: list
    requests: list

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool_use(id_, name, **inp):
    return _Block("tool_use", id=id_, name=name, input=inp)


def resp(blocks, stop):
    return _Response(blocks, stop, _Usage(input_tokens=100, output_tokens=10, cache_read_input_tokens=50))


def test_parallel_tool_results_go_back_in_one_message(corpus):
    client = Scripted([
        resp([_Block("text", text="查詢中"),
              tool_use("a", "lookup_verse", reference="羅 5:8", version="cuv"),
              tool_use("b", "lookup_verse", reference="羅 5:99", version="cuv"),
              tool_use("c", "no_such_tool")], "tool_use"),
        resp([_Block("text", text="答案")], "end_turn"),
    ], [])
    run = run_agent(client, "問題", model="claude-opus-5-5", handlers=make_handlers(corpus))  # an Anthropic model: effort is sent
    assert run.outcome == "completed" and run.final_text == "答案"
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b", "c"]
    assert "is_error" not in results[0] and results[1]["is_error"] and results[2]["is_error"]
    assert run.usage_total() == {"input_tokens": 200, "output_tokens": 20,
                                 "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100}
    assert client.requests[0]["output_config"] == {"effort": "medium"}


def test_injected_empty_result_omits_content(corpus):
    client = Scripted([
        resp([tool_use("a", "lookup_verse", reference="羅 5:8", version="cuv")], "tool_use"),
        resp([_Block("text", text="查詢失敗")], "end_turn"),
    ], [])
    inj = FaultInjector([FaultSpec("lookup_verse", "empty")], corpus=corpus)
    run = run_agent(client, "q", model="m", handlers=make_handlers(corpus), injector=inj, effort=None)
    result = client.requests[1]["messages"][2]["content"][0]
    assert "content" not in result and "is_error" not in result
    assert run.faults == [{"tool": "lookup_verse", "call": 1, "mode": "empty"}]
    assert "output_config" not in client.requests[0]


def test_max_steps(corpus):
    loop = [resp([tool_use(str(i), "lookup_verse", reference="羅 5:8", version="cuv")], "tool_use") for i in range(3)]
    run = run_agent(Scripted(loop, []), "q", model="m", handlers=make_handlers(corpus), max_steps=3)
    assert run.outcome == "max_steps" and len(run.tool_calls) == 3


def test_refusal_and_api_error_are_recorded(corpus):
    run = run_agent(Scripted([resp([], "refusal")], []), "q", model="m", handlers=make_handlers(corpus))
    assert run.outcome == "refusal"
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    run = run_agent(Scripted([err], []), "q", model="m", handlers=make_handlers(corpus))
    assert run.outcome == "api_error" and "APIConnectionError" in run.error


def test_harness_bug_is_not_hidden(corpus):
    with pytest.raises(ZeroDivisionError):
        run_agent(Scripted([ZeroDivisionError()], []), "q", model="m", handlers=make_handlers(corpus))


def test_handler_crash_is_flagged(corpus):
    def boom(_):
        raise KeyError("bug")
    client = Scripted([resp([tool_use("a", "lookup_verse", reference="x", version="cuv")], "tool_use"),
                       resp([_Block("text", text="x")], "end_turn")], [])
    run = run_agent(client, "q", model="m", handlers={"lookup_verse": boom})
    assert run.tool_calls[0].is_error and "KeyError" in run.tool_calls[0].exception


def test_simplified_characters_in_the_answer_are_converted(corpus):
    from theoclaw.common import zh
    if not zh.available():
        pytest.skip("opencc not installed")
    jue, dang = chr(0x89C9), chr(0x5F53)  # Simplified 覺 and 當, as code points so this file stays 繁體
    client = Scripted([resp([_Block("text", text=f"不隨感{jue}起落，應{dang}如此；神的愛就在此向我們顯明了。")], "end_turn")], [])
    run = run_agent(client, "問題", model="qwen3.8-max", handlers=make_handlers(corpus))
    assert run.final_text == "不隨感覺起落，應當如此；神的愛就在此向我們顯明了。"  # 顯明了 stays as the 和合本 writes it
    assert run.simplified_fixed == sorted([jue, dang]) and jue in run.model_text
    client = Scripted([resp([_Block("text", text=f"感{jue}")], "end_turn")], [])
    raw = run_agent(client, "問題", model="qwen3.8-max", handlers=make_handlers(corpus), fix_simplified=False)
    assert raw.final_text == f"感{jue}" and raw.model_text is None


def test_scripture_placeholders_are_filled_from_the_lookup_tool(corpus):
    text = "經文：〔經文：羅 5:8〕\n\n上下文：〔經文：羅馬書 5:8-9，和合本〕\n〔經文：約翰福音 3:16〕\n〔經文：John 3:16，KJV〕\n〔經文：創世記 9:99〕"
    client = Scripted([resp([_Block("text", text=text)], "end_turn")], [])
    run = run_agent(client, "問題", model="qwen3.8-max", handlers=make_handlers(corpus))
    lines = run.final_text.split("\n")
    assert lines[0] == "經文：「惟有基督在我們還作罪人的時候為我們死，神的愛就在此向我們顯明了。」（羅馬書 5:8，和合本）"
    assert lines[2].startswith("上下文：「惟有基督") and "顯明了。現在我們" in lines[2] and lines[2].endswith("（羅馬書 5:8-9，和合本）")
    assert lines[3].startswith("「神愛世人")  # the verse's own 「, closed only in a later verse, comes off
    assert lines[4] == "“KJV John.3.16” (John 3:16, KJV)"
    assert lines[5] == "〔經文查詢失敗：創世記 9:99〕"
    fills = [c for c in run.tool_calls if c.name == "fill_quote"]
    assert [c.is_error for c in fills] == [False, False, False, False, True]
    assert run.model_text == text


def test_scripture_placeholders_fill_luther(corpus):
    text = "〔經文：Römer 5:8，LUT〕\n〔經文：Römer 5,8，LUT〕"  # German book name; colon or German comma
    client = Scripted([resp([_Block("text", text=text)], "end_turn")], [])
    run = run_agent(client, "Frage", model="qwen3.8-max", handlers=make_handlers(corpus))
    line = ("„Darum preiset Gott seine Liebe gegen uns, daß Christus für uns gestorben ist, "
            "da wir noch Sünder waren.“ (Römer 5,8, Luther 1912)")
    assert run.final_text == f"{line}\n{line}"
    assert run.model_text == text


def test_placeholders_go_through_injected_faults(corpus):
    client = Scripted([resp([_Block("text", text="〔經文：羅馬書 5:8〕")], "end_turn")], [])
    injector = FaultInjector([FaultSpec(tool="lookup_verse", mode="error")])
    run = run_agent(client, "問題", model="qwen3.8-max", handlers=make_handlers(corpus), injector=injector)
    assert run.final_text == "〔經文查詢失敗：羅馬書 5:8〕" and run.faults
    client = Scripted([resp([_Block("text", text="〔經文：羅馬書 5:8〕")], "end_turn")], [])
    raw = run_agent(client, "問題", model="qwen3.8-max", handlers=make_handlers(corpus), fill_quotes=False)
    assert raw.final_text == "〔經文：羅馬書 5:8〕" and raw.model_text is None


def test_filled_quotations_pass_the_graders(corpus):
    from theoclaw.evals.grading import text_seen_in_tools
    client = Scripted([resp([_Block("text", text="〔經文：羅馬書 5:8-9〕")], "end_turn")], [])
    run = run_agent(client, "問題", model="qwen3.8-max", handlers=make_handlers(corpus)).to_dict()
    assert text_seen_in_tools("神的愛就在此向我們顯明了。現在我們既靠", run)


def test_merged_verse_and_square_bracket_placeholder(tmp_path):
    import json
    from theoclaw.common.corpus import Corpus
    cuv = {"Luke.21.29": "耶穌又設比喻；它發芽的時候，自然曉得夏天近了。", "Luke.21.30": "a", "Luke.21.31": "這樣，也該曉得神的國近了。"}
    for name, obj in [("cuv", cuv), ("kjv", {}), ("crossrefs", {}), ("wesley_nt", {})]:
        (tmp_path / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    handlers = make_handlers(Corpus(tmp_path))
    assert "21:30 （本譯本此節無單獨經文" in handlers["lookup_verse"]({"reference": "路 21:29-31", "version": "cuv"})
    client = Scripted([resp([_Block("text", text="【經文：路加福音 21:29-31】")], "end_turn")], [])
    run = run_agent(client, "問題", model="qwen3.8-max", handlers=handlers)
    assert run.final_text == "「耶穌又設比喻；它發芽的時候，自然曉得夏天近了。這樣，也該曉得神的國近了。」（路加福音 21:29-31，和合本）"


def test_simplified_question_gets_a_simplified_answer_with_converted_scripture(corpus):
    from theoclaw.common import zh
    from theoclaw.evals.grading import load_graders
    if not zh.available():
        pytest.skip("opencc not installed")
    to_hans = zh.to_simplified
    question = to_hans("羅馬書 5:8 講甚麼？")  # Simplified, built by conversion so this file stays 繁體
    answer = to_hans("〔經文：羅馬書 5:8〕這節說神的愛，「還作罪人的時候」（羅馬書 5:8）。")
    client = Scripted([resp([_Block("text", text=answer)], "end_turn")], [])
    run = run_agent(client, question, model="qwen3.8-max", handlers=make_handlers(corpus))
    assert run.script == "hans"
    assert run.final_text.startswith(to_hans("「惟有基督在我們還作罪人的時候為我們死")) and to_hans("和合本") in run.final_text
    assert zh.simplified_chars(run.final_text)  # really Simplified, not converted to 繁體
    grade = load_graders()["no_misquotes"](type("T", (), {"prompt": question})(), run.to_dict())
    assert grade.passed, grade.details  # quotations are compared with the 繁體 和合本 after conversion
