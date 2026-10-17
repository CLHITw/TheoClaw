"""Scripture placeholders: the agent writes 〔經文：羅馬書 5:8〕 and the program fills in
the verse text, so a whole-verse quotation cannot be misquoted from memory.

Each placeholder is filled through the lookup_verse handler the run was given, so an
injected tool fault reaches the filling too: a lookup that fails or comes back empty
leaves 〔經文查詢失敗：…〕 in the answer instead of text from anywhere else.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..common.refs import RefError, parse_ref
from ..common.tooling import Handler, ToolError
from .tools import EMPTY_VERSE

# 〔經文：羅馬書 5:8〕, 〔經文：羅 5:6-8，和合本〕, 〔經文：John 3:16，KJV〕
# (【經文：…】 and an ASCII colon are accepted too; a Simplified 經 is converted before filling)
PLACEHOLDER_RE = re.compile(r"[〔【]\s*[經\u7ecf]文\s*[：:]\s*([^〔〕【】]{1,40}?)\s*[〕】]")
_VERSION_RE = re.compile(r"\s*[,，、]\s*(KJV|kjv|和合本|cuv|CUV)\s*$")
_VERSE_NUMBER = re.compile(r"^\s*\d+:\d+\s*")


def _verse_lines(output: str) -> list[str]:
    """Verse texts from lookup_verse output: the 【版本】 header line dropped, verse numbers
    removed, and verses merged into the one before them (no text of their own) left out."""
    lines = [l for l in output.splitlines() if l.strip()]
    return [t for t in (_VERSE_NUMBER.sub("", l) for l in lines[1:]) if t != EMPTY_VERSE]


def _render(output: str, version: str, label: str) -> str:
    verses = _verse_lines(output)
    if version == "kjv":
        return f"“{' '.join(verses)}” ({label}, KJV)"  # English answers: ASCII brackets
    text = "".join(verses).replace("「", "『").replace("」", "』")  # keep the outer 「」 unambiguous
    return f"「{text}」（{label}，和合本）"


# Internal words the agent sometimes says to the user ("按規矩……不放經文標記"). Only phrases
# that cannot be ordinary Chinese are rewritten; anything else is left to the
# no_internal_words grader, which reports what this list misses.
_INTERNAL = [
    (re.compile(r"`?lookup_verse`?"), "查經工具"),
    (re.compile(r"`?cross_references`?"), "串珠查詢"),
    (re.compile(r"`?wesley_note`?"), "衛斯理註釋查詢"),
    (re.compile(r"`?fill_quote`?"), "查經工具"),
    (re.compile(r"(?:按照|按|依照)(?:我的)?(?:規矩|規則|規定)[，,、]?"), ""),
    (re.compile(r"(?:經文|引用|整節)標記"), "經文"),
    (re.compile(r"以?標記(?:方式)?(?=呈現|列出|補上)"), ""),
]


def scrub_internal(text: str) -> tuple[str, list[str]]:
    """Rewrite internal words in the final answer; returns the text and what was changed."""
    changed = []
    for pattern, repl in _INTERNAL:
        def sub(m, repl=repl):
            changed.append(m.group(0))
            return repl
        text = pattern.sub(sub, text)
    return text, changed


def fill_placeholders(text: str, handlers: dict[str, Handler]) -> tuple[str, list[Any]]:
    """Replace every placeholder in ``text``; returns the new text and one ToolCall per
    placeholder (name fill_quote), so traces and graders see where the text came from."""
    from .loop import ToolCall  # loop imports this module

    calls: list[ToolCall] = []

    def replace(m: re.Match) -> str:
        body = m.group(1)
        v = _VERSION_RE.search(body)
        version = "kjv" if v and v.group(1).lower() == "kjv" else "cuv"
        reference = _VERSION_RE.sub("", body).strip()
        inp = {"reference": reference, "version": version}
        start, output, is_error = time.perf_counter(), "", True
        handler = handlers.get("lookup_verse")
        if handler is None:
            output = "沒有查經工具"
        else:
            try:
                output = handler(inp)
                is_error = not _verse_lines(output)
            except ToolError as e:
                output = str(e)
        calls.append(ToolCall(id=f"fill-{len(calls)}", name="fill_quote", input=inp, output=output,
                              is_error=is_error, latency_s=time.perf_counter() - start))
        if is_error:
            return f"〔經文查詢失敗：{reference}〕"
        try:
            ref = parse_ref(reference)
            label = ref.en() if version == "kjv" else ref.zh()  # 羅 5:8 -> 羅馬書 5:8
        except RefError:
            label = reference
        return _render(output, version, label)

    return PLACEHOLDER_RE.sub(replace, text), calls
