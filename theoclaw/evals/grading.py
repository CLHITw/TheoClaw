"""Grader registry and helpers for writing graders.

A grader is a function (task, run) -> Grade, registered by name:

    from theoclaw.grading import Grade, grader

    @grader("cites_expected_refs")
    def cites_expected_refs(task, run):
        ...
        return Grade(passed, "why")

``task`` is the Task from tasks.yaml; ``run`` is the trace dict written by the
runner (see AgentRun.to_dict): final_text, outcome, steps[].tool_calls[], faults...
A run passes a task only if every grader listed on the task passes.

Graders are loaded from every .py file in graders/ at the project root.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
from typing import Callable

from ..common import zh
from ..common.corpus import Corpus, default_corpus, normalize, normalize_en, normalize_zh
from ..common.paths import GRADERS_DIR
from ..common.refs import Ref, RefError, extract_refs, parse_ref


@dataclass
class Grade:
    passed: bool
    details: str = ""


GraderFn = Callable[[object, dict], Grade]
REGISTRY: dict[str, GraderFn] = {}


def grader(name: str) -> Callable[[GraderFn], GraderFn]:
    def register(fn: GraderFn) -> GraderFn:
        old = REGISTRY.get(name)
        # Re-loading the same file (grading twice in one process) replaces the old function;
        # the same name defined in two different places is a mistake.
        if old is not None and (old.__module__, old.__qualname__) != (fn.__module__, fn.__qualname__):
            raise ValueError(f"grader {name!r} is defined twice ({old.__module__} and {fn.__module__})")
        REGISTRY[name] = fn
        return fn
    return register


def load_graders(directory: Path | str = GRADERS_DIR) -> dict[str, GraderFn]:
    for path in sorted(Path(directory).glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"graders.{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return REGISTRY


# ---------------------------------------------------------------- helpers for graders

def tool_calls(run: dict, name: str | None = None) -> list[dict]:
    calls = [c for s in run["steps"] for c in s["tool_calls"]]
    return [c for c in calls if name is None or c["name"] == name]


def answer_refs(run: dict) -> list[Ref]:
    """References cited in the final answer (繁體 forms such as 約翰福音 3:16 / 約3:16)."""
    return extract_refs(run["final_text"])


_QUOTE_RE = re.compile(r"「([^「」]+)」|『([^『』]+)』|“([^“”]+)”")


def quoted_spans(text: str) -> list[str]:
    """Text inside 「」, 『』 or “” quotation marks."""
    return [next(g for g in m.groups() if g) for m in _QUOTE_RE.finditer(text)]


# 「…」（羅馬書 5:8）, 「…」(羅 5:6-8，和合本) or 「…」——羅馬書 5:8
_CITATION_RE = re.compile(r"[ \t]*(?:[（(]([^（）()]{1,40})[）)]|[—－]{1,2}[ \t]*([^\n「」『』“”。]{1,40}))")


def quotation_citations(text: str) -> list[tuple[str, str, list[Ref]]]:
    """(quotation, citation text, references in it) for every quotation directly
    followed by a bracketed citation that names at least one reference."""
    out = []
    for m in _QUOTE_RE.finditer(text):
        cite = _CITATION_RE.match(text, m.end())
        if not cite:
            continue
        cite_text = cite.group(1) or cite.group(2)
        refs = extract_refs(cite_text)
        if not refs and re.search(r"\b(KJV|WEB)\b", cite_text.upper()):
            try:
                refs = [parse_ref(re.split(r"[,，;；(（]", cite_text)[0].strip())]
            except RefError:
                refs = []
        if refs:
            out.append((next(g for g in m.groups() if g), cite_text, refs))
    return out


def quotation_version(span: str, cite: str) -> str | None:
    """The Bible version a cited quotation is in: Chinese is 和合本 (cuv); English counts
    as a quotation only when the citation says KJV or WEB; anything else is None."""
    if re.search(r"[㐀-鿿]", span):
        return "cuv"
    up = cite.upper()
    return "kjv" if "KJV" in up else ("web" if re.search(r"\bWEB\b", up) else None)


def cited_quotations(text: str) -> list[tuple[str, Ref]]:
    """Quotations directly followed by a bracketed reference, with that reference:
    「…」（羅馬書 5:8） gives (…, 羅馬書 5:8). Quotations without one are left out."""
    return [(span, refs[0]) for span, _, refs in quotation_citations(text)]


def refs_overlap(a: Ref, b: Ref) -> bool:
    return (a.book, a.chapter) == (b.book, b.chapter) and a.verse_start <= b.verse_end and b.verse_start <= a.verse_end


def verse_text(ref: Ref, version: str = "cuv", corpus: Corpus | None = None) -> str | None:
    """Gold text of a reference, or None if it does not exist."""
    corpus = corpus or default_corpus()
    try:
        return "".join(t for _, t in corpus.passage(ref, version))
    except KeyError:
        return None


def is_verbatim(span: str, ref: Ref, version: str = "cuv", corpus: Corpus | None = None) -> bool:
    """True if ``span`` appears inside the gold text of ``ref`` after normalisation
    (punctuation and spacing ignored, characters must match exactly)."""
    gold = verse_text(ref, version, corpus)
    if gold is None or not normalize(span, version):
        return False
    return normalize(span, version) in normalize(gold, version)


_VERSE_NUMBER = re.compile(r"(?m)^\s*\d+:\d+\s*")  # "5:7 " at the start of each verse in lookup_verse output


def text_seen_in_tools(span: str, run: dict, version: str = "cuv") -> bool:
    """True if ``span`` appears in some successful tool output of this run, i.e. the
    agent could have copied it rather than written it from memory. Verse numbers are
    dropped first, so a quotation running across verses of one lookup still matches."""
    needle = normalize(span, version)
    return bool(needle) and any(
        needle in normalize(_VERSE_NUMBER.sub("", c["output"]), version)
        for c in tool_calls(run) if not c["is_error"]
    )


def toolset(run: dict) -> dict:
    """The tool configuration a run used (old traces without it used scripture + wesley)."""
    return run.get("toolset") or {"tools": ["scripture", "wesley"]}


@lru_cache(maxsize=8)
def _source_texts(groups: tuple[str, ...], wiki: str | None) -> tuple[str, str]:
    """(English, Chinese) normalised original texts available to a tool configuration."""
    texts: list[str] = []
    if "wesley" in groups:
        texts += list(default_corpus().wesley.values())
    if "kb" in groups and wiki:
        from ..kb.query.tools import source_texts
        texts += source_texts(wiki)
    return "\n".join(normalize_en(t) for t in texts), "".join(normalize_zh(t) for t in texts)


def in_wesley_sources(span: str, run: dict) -> bool:
    """True if a quotation appears word for word in the original Methodist texts this
    run had access to: Wesley's NT notes (wesley tools), the converted sources/ of the
    OpenKB wiki (kb tools). Compiled summary and concept pages do not count; they are a
    model's paraphrase, not the source's words. Chinese quotations are compared with
    Chinese sources (e.g. the course materials), punctuation ignored."""
    meta = toolset(run)
    en, zh_text = _source_texts(tuple(meta.get("tools", [])), meta.get("wiki"))
    if re.search(r"[\u3400-\u9fff]", span):
        needle = normalize_zh(span)
        return bool(needle) and needle in zh_text
    needle = normalize_en(span)
    return bool(needle) and needle in en


def simplified_in_answer(run: dict) -> set[str] | None:
    """Simplified characters in the final answer (None if opencc is not installed)."""
    return zh.simplified_chars(run.get("final_text") or "")


def kb_reads_by_folder(run: dict) -> dict[str, int]:
    """How many kb_read_file calls went to index / summaries / concepts / entities / sources."""
    counts: dict[str, int] = {}
    for c in tool_calls(run, "kb_read_file"):
        folder = c["input"].get("path", "").replace("\\", "/").lstrip("/").split("/")[0]
        folder = "index" if folder == "index.md" else folder
        counts[folder] = counts.get(folder, 0) + 1
    return counts


# ---------------------------------------------------------------- always-on graders
# Applied by grade_run to every task, after the graders the task lists in tasks.yaml.

ALWAYS_ON = ("no_misquotes", "no_internal_words")

# Words from the agent's instructions and tooling that should not reach the user. The
# agent loop rewrites the obvious ones (quotes.scrub_internal); this grader reports what
# is left, so new internal words show up in the reports instead of going unnoticed.
# 「規矩是」只在說自己的規矩時算（「我的規矩是」）；講循道衛理總規時「這些規矩是……」是正常的話。
_INTERNAL_RE = re.compile(
    r"(?:經文|引用|整節|放|寫|補上|貼出|給出)[^，。；\n]{0,4}標記|標記(?:格式|呈現)"
    r"|(?:按|照|依)(?:著|照)?(?:我的)?規矩|我(?:的|們的)規矩是|按(?:照)?規則|系統(?:會)?自動填入|知識庫"
    r"|lookup_verse|cross_references|wesley_note|fill_quote|〔經文：|【經文：")

_ELLIPSIS_RE = re.compile(r"…+|\.{3,}|⋯+")
_NOT_SCRIPTURE_RE = re.compile(r"衛斯理|註釋|注釋|Wesley", re.I)


def _attempts_quote(span: str, gold: str, version: str) -> bool:
    """True if ``span`` shares a run of at least half its length (and 4+ characters)
    with ``gold``, i.e. it reads as an attempt to quote that text, right or wrong."""
    from difflib import SequenceMatcher
    a, b = normalize(span, version), normalize(gold, version)
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size >= max(4, len(a) // 2)


def _as_traditional(run: dict) -> str:
    """The answer in 繁體: a Simplified answer (script "hans") is converted, so quotations
    are compared with the 繁體 和合本 and the internal-word patterns still match."""
    text = run.get("final_text") or ""
    if run.get("script") == "hans":
        from ..common import zh
        text = zh.to_traditional(text)
    return text


@grader("no_misquotes")
def no_misquotes(task, run) -> Grade:
    """Every quotation of 6+ characters directly followed by a scripture citation, as
    in 「…」（羅馬書 5:8）, must match the text it cites word for word (any of the
    references in the citation). Chinese is compared with the 和合本; English only when
    the citation says KJV. Citations naming Wesley or a 註釋 are not scripture and are
    skipped; an ellipsis splits a quotation into parts checked separately. A quotation
    that shares little with every cited verse (a theme label, a paraphrase) is not
    treated as a quotation of it. Text repeated from the question (a draft the user asked
    to have checked) is the user's wording, not the agent's quotation, and is skipped."""
    bad, checked = [], 0
    asked = normalize_zh(getattr(task, "prompt", "") or "")
    for span, cite, refs in quotation_citations(_as_traditional(run)):
        if _NOT_SCRIPTURE_RE.search(cite):
            continue
        if asked and normalize_zh(span) and normalize_zh(span) in asked:
            continue
        version = quotation_version(span, cite)
        if version is None:
            continue
        if len(normalize(span, version)) < 6:
            continue
        texts = [t for t in (verse_text(r, version) for r in refs) if t]
        if texts and not any(_attempts_quote(span, t, version) for t in texts):
            continue  # a label or paraphrase that shares little with the verse, e.g. 「神的愛／神賜下兒子」（羅 5:8）
        checked += 1
        parts = [p for p in _ELLIPSIS_RE.split(span) if normalize(p, version)]
        if not all(any(is_verbatim(p, r, version) for r in refs) for p in parts):
            bad.append(span)
    return Grade(not bad, f"引錯：{bad[:2]}" if bad else f"{checked} cited quotations, all word for word")


@grader("no_internal_words")
def no_internal_words(task, run) -> Grade:
    """The answer must not mention the agent's internals: placeholders (標記) or a
    placeholder left unfilled, the rules it follows (按規矩), tool names. 標記 in its
    ordinary sense (洗禮是分別的標記、可靠標記) is allowed."""
    text = _as_traditional(run)
    hits = []
    for m in _INTERNAL_RE.finditer(text):
        hits.append(text[max(0, m.start() - 12):m.end() + 6].replace("\n", " "))
    return Grade(not hits, f"內部用語：{hits[:3]}" if hits else "no internal words")
