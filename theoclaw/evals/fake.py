"""Deterministic stand-ins for the model, for testing the harness and your graders
without spending API money.

    python -m theoclaw.evals run tasks/tasks.example.yaml --model fake-honest
    python -m theoclaw.evals run tasks/tasks.example.yaml --model fake-fabricator

Both look up every reference found in the prompt (plus Wesley's note when the
prompt mentions 衛斯理, and cross references when it mentions 串珠; only tools the
agent was given), then quote what the tools returned. They differ only when a tool fails:

- fake-honest      says the lookup failed
- fake-fabricator  quotes the verse anyway, "from memory" (it reads the corpus
                   directly), exactly the behaviour the fault tasks should catch

A grader that passes fake-fabricator on a fault task is not measuring what you
think it measures.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass, field

from ..common.corpus import Corpus, default_corpus
from ..common.refs import extract_refs, parse_ref


@dataclass
class _Block:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None

    def model_dump(self, mode: str = "json", exclude_none: bool = True) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None or not exclude_none}


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class _Response:
    content: list[_Block]
    stop_reason: str
    usage: _Usage


@dataclass
class FakeClient:
    behaviour: str = "honest"  # honest | fabricator
    corpus: Corpus | None = None
    _ids: itertools.count = field(default_factory=itertools.count)

    @property
    def messages(self) -> "FakeClient":
        return self

    def create(self, *, messages: list[dict], tools: list[dict] | None = None, **_: object) -> _Response:
        last = messages[-1]
        if isinstance(last["content"], str):
            available = {t["name"] for t in tools} if tools is not None else None
            return self._plan(last["content"], available)
        calls = {b.id: b for b in messages[-2]["content"] if getattr(b, "type", None) == "tool_use"}
        return self._answer(calls, last["content"])

    def _respond(self, blocks: list[_Block], stop: str, prompt_len: int) -> _Response:
        out_len = sum(len(b.text or "") + len(str(b.input or "")) for b in blocks)
        return _Response(blocks, stop, _Usage(input_tokens=1500 + prompt_len, output_tokens=out_len))

    def count_tokens(self, *, messages: list[dict], **_: object) -> _Usage:
        """Stand-in for messages.count_tokens: one token per CJK character, one per 4 other characters."""
        text = messages[-1]["content"]
        cjk = len(re.findall(r"[㐀-鿿]", text))
        return _Usage(input_tokens=7 + cjk + (len(text) - cjk + 3) // 4, output_tokens=0)

    def _plan(self, prompt: str, available: set[str] | None = None) -> _Response:
        has = lambda name: available is None or name in available
        refs = extract_refs(prompt)
        if not refs:
            return self._respond([_Block("text", text="（假模型）題目中找不到經文出處。")], "end_turn", len(prompt))
        blocks = []
        for ref in refs:
            if has("lookup_verse"):
                blocks.append(self._tool("lookup_verse", {"reference": ref.zh(), "version": "cuv"}))
            if "衛斯理" in prompt and ref.is_single and has("wesley_note"):
                blocks.append(self._tool("wesley_note", {"reference": ref.zh()}))
        if "串珠" in prompt and has("cross_references"):
            first = refs[0]
            blocks.append(self._tool("cross_references", {"reference": f"{first.book}.{first.chapter}.{first.verse_start}"}))
        if not blocks:
            return self._respond([_Block("text", text="（假模型）沒有可用的工具。")], "end_turn", len(prompt))
        return self._respond(blocks, "tool_use", len(prompt))

    def _tool(self, name: str, inp: dict) -> _Block:
        return _Block("tool_use", id=f"toolu_fake_{next(self._ids)}", name=name, input=inp)

    def _answer(self, calls: dict[str, _Block], results: list[dict]) -> _Response:
        corpus = self.corpus or default_corpus()
        parts = []
        for r in results:
            call = calls[r["tool_use_id"]]
            ref = parse_ref(call.input["reference"])
            content = r.get("content", "")
            failed = r.get("is_error") or not content
            if call.name == "lookup_verse":
                if failed and self.behaviour == "honest":
                    parts.append(f"查詢 {ref.zh()} 失敗，無法引用經文。")
                    continue
                if failed:  # fabricator: write the verse "from memory"
                    text = "".join(t for _, t in corpus.passage(ref, "cuv"))
                else:
                    text = "".join(re.sub(r"^\d+:\d+ ", "", line) for line in content.splitlines()[1:])
                parts.append(f"「{text}」（{ref.zh()}）")
            elif call.name == "wesley_note":
                if failed:
                    parts.append(f"查詢衛斯理對 {ref.zh()} 的註釋失敗。")
                else:
                    parts.append(f"衛斯理的註釋（英文原文節錄）：{content.splitlines()[-1][:120]}")
            elif call.name == "cross_references":
                parts.append("相關經文：" + ("、".join(l[2:] for l in content.splitlines()[1:4]) if not failed else "查詢失敗"))
        # The tool results are this turn's new input, so a run that reads more pays more.
        read = sum(len(str(r.get("content", ""))) for r in results)
        return self._respond([_Block("text", text="\n".join(parts))], "end_turn", read)
