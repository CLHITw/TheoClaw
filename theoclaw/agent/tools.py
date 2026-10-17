"""The agent's tools, in groups that can be switched on and off:

    scripture  lookup_verse, cross_references   (Bible text: 和合本 / KJV)
    wesley     wesley_note                      (Wesley's NT notes, looked up by verse)
    kb         kb_read_file, kb_get_page_content (a compiled OpenKB wiki; theoclaw.kb.query)
    rag        rag_search (BM25 over the same wiki's source text, nothing compiled; theoclaw.kb.query.rag)
    reference  dictionary_entry, dictionary_search (ISBE, Easton, Smith; pastor mode; theoclaw.agent.reference)

Every handler takes the tool input dict and returns a string. A handler raises
ToolError for a failure the model should be told about; the agent loop turns it
into a tool_result with is_error=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..common.corpus import VERSIONS, Corpus, default_corpus
from ..common.refs import NT_BOOKS, Ref, RefError, parse_ref
from ..common.tooling import Handler, ToolError

MAX_VERSES = 30
EMPTY_VERSE = "（本譯本此節無單獨經文，多半已併入上一節）"


TOOL_DEFS: list[dict] = [
    {
        "name": "lookup_verse",
        "description": (
            "查詢聖經經文原文。輸入一處經文出處（可為單節或同一章內的範圍，最多 30 節），"
            "回傳該版本的逐節經文。引用經文時只能使用本工具回傳的文字。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {
                    "type": "string",
                    "description": "經文出處，例如「約翰福音 3:16」「羅 5:1-5」「John 3:16」。",
                },
                "version": {
                    "type": "string",
                    "enum": list(VERSIONS),
                    "description": "cuv = 和合本（繁體）；kjv = King James Version。",
                },
            },
            "required": ["reference", "version"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cross_references",
        "description": (
            "查詢某一節經文的串珠（相關經文），依 OpenBible.info 的投票數由高到低排列。"
            "只接受單節經文。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "單節經文出處，例如「羅馬書 5:8」。"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25,
                          "description": "最多回傳幾筆，預設 10。"},
            },
            "required": ["reference"],
            "additionalProperties": False,
        },
    },
    {
        "name": "wesley_note",
        "description": (
            "查詢約翰．衛斯理《新約聖經註釋》（Explanatory Notes upon the New Testament）"
            "對某一節經文的註釋，回傳英文原文。只收錄新約。若該節沒有註釋，會明確說明。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "新約單節經文出處，例如「羅馬書 8:16」。"},
            },
            "required": ["reference"],
            "additionalProperties": False,
        },
    },
]


def _parse(reference: str) -> Ref:
    try:
        return parse_ref(reference)
    except RefError as e:
        raise ToolError(str(e)) from e


def lookup_verse(inp: dict, corpus: Corpus) -> str:
    ref = _parse(str(inp.get("reference", "")))
    version = inp.get("version", "cuv")
    if version not in VERSIONS:
        raise ToolError(f"不支援的版本：{version}（可用：{', '.join(VERSIONS)}）")
    if ref.verse_end - ref.verse_start + 1 > MAX_VERSES:
        raise ToolError(f"一次最多查詢 {MAX_VERSES} 節")
    try:
        verses = corpus.passage(ref, version)
    except KeyError as e:
        raise ToolError(f"經文不存在：{ref.zh()}（{e.args[0]}）") from e
    lines = [f"【{VERSIONS[version]}】{ref.zh()}"]
    for v, text in verses:
        lines.append(f"{ref.chapter}:{v} {text or EMPTY_VERSE}")
    return "\n".join(lines)


def cross_references(inp: dict, corpus: Corpus) -> str:
    ref = _parse(str(inp.get("reference", "")))
    if not ref.is_single:
        raise ToolError("串珠只接受單節經文")
    if not corpus.has_verse(ref.book, ref.chapter, ref.verse_start):
        raise ToolError(f"經文不存在：{ref.zh()}")
    limit = int(inp.get("limit") or 10)
    rows = corpus.crossrefs.get(ref.osis(), [])[: max(1, min(limit, 25))]
    if not rows:
        return f"{ref.zh()} 沒有串珠資料。"
    lines = [f"{ref.zh()} 的串珠（票數由高到低）："]
    for target, votes in rows:
        try:
            label = parse_ref(target).zh()
        except RefError:
            label = target
        lines.append(f"- {label}（{votes} 票）")
    return "\n".join(lines)


def wesley_note(inp: dict, corpus: Corpus) -> str:
    ref = _parse(str(inp.get("reference", "")))
    if ref.book not in NT_BOOKS:
        raise ToolError("v0 只收錄衛斯理的新約註釋")
    if not ref.is_single:
        raise ToolError("請查詢單節經文")
    if not corpus.has_verse(ref.book, ref.chapter, ref.verse_start):
        raise ToolError(f"經文不存在：{ref.zh()}")
    note = corpus.wesley.get(ref.osis())
    if not note:
        return f"衛斯理《新約聖經註釋》對 {ref.zh()} 沒有註釋。"
    return f"衛斯理《新約聖經註釋》{ref.en()}（英文原文）：\n{note}"


def make_handlers(corpus: Corpus | None = None) -> dict[str, Handler]:
    corpus = corpus or default_corpus()
    return {
        "lookup_verse": lambda inp: lookup_verse(inp, corpus),
        "cross_references": lambda inp: cross_references(inp, corpus),
        "wesley_note": lambda inp: wesley_note(inp, corpus),
    }


GROUPS = {
    "scripture": ["lookup_verse", "cross_references"],
    "wesley": ["wesley_note"],
    "kb": ["kb_read_file", "kb_get_page_content"],
    "rag": ["rag_search"],
    "reference": ["dictionary_entry", "dictionary_search"],  # pastor mode only: ISBE, Easton, Smith
}
DEFAULT_TOOLS = ("scripture", "wesley")


def parse_tools(spec: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """"scripture,kb" -> ["scripture", "kb"], in a fixed order so the tool list (and
    the prompt cache) does not depend on how the groups were typed."""
    if spec is None:
        return list(DEFAULT_TOOLS)
    names = [s.strip() for s in (spec.split(",") if isinstance(spec, str) else spec) if s.strip()]
    unknown = set(names) - set(GROUPS)
    if unknown or not names:
        raise ValueError(f"unknown tool groups {sorted(unknown)}; choose from {list(GROUPS)}")
    return [g for g in GROUPS if g in names]


@dataclass
class ToolSet:
    """What one configuration of the agent gets: tool definitions, handlers, the
    matching system prompt, and metadata recorded with every run."""
    groups: list[str]
    defs: list[dict]
    handlers: dict[str, Handler]
    system: str
    meta: dict = field(default_factory=dict)


def build_tool_set(tools=None, kb: str | Path | None = None, corpus: Corpus | None = None) -> ToolSet:
    """Scripture lookup and cross references stay the same whatever else is switched
    on, so comparing two tool sets changes only how Methodist sources are retrieved."""
    from .prompt import system_prompt

    groups = parse_tools(tools)
    by_name = {d["name"]: d for d in TOOL_DEFS}
    base = make_handlers(corpus)
    names = [n for g in groups if g not in ("kb", "rag", "reference") for n in GROUPS[g]]
    defs, handlers = [by_name[n] for n in names], {n: base[n] for n in names}
    meta: dict = {"tools": groups}
    addendum = ""
    if "kb" in groups or "rag" in groups:
        if not kb:
            raise ValueError("the kb and rag tool groups need --kb (a folder in knowledge/ or a wiki/ folder)")
        from ..kb.query import KnowledgeBase, rag, tools as kb_tools
        base_kb = KnowledgeBase.open(kb)
        if "kb" in groups:
            defs += kb_tools.TOOL_DEFS
            handlers.update(kb_tools.make_handlers(base_kb.wiki))
            addendum = kb_tools.system_addendum(base_kb.wiki)
        if "rag" in groups:  # the wiki's source text, chunked and searched; with kb too, a hybrid
            defs += rag.TOOL_DEFS
            handlers.update(rag.make_handlers(base_kb.wiki))
            addendum += rag.SYSTEM_ADDENDUM
        meta.update(base_kb.meta())
    elif kb:
        raise ValueError("--kb given but neither the kb nor the rag tool group is switched on")
    if "reference" in groups:  # Bible dictionaries, looked up by program
        from . import reference
        defs += reference.TOOL_DEFS
        handlers.update(reference.make_handlers())
        addendum += reference.SYSTEM_ADDENDUM
    return ToolSet(groups, defs, handlers, system_prompt(groups) + addendum, meta)
