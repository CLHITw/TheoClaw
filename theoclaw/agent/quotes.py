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

from ..common.corpus import DEFAULT_VERSION, TAGS, VERSION_LANG, VERSIONS
from ..common.refs import RefError, parse_ref
from ..common.tooling import Handler, ToolError
from .tools import EMPTY_VERSE, ref_label

# 〔經文：羅馬書 5:8〕, 〔經文：羅 5:6-8，和合本〕, 〔經文：John 3:16，KJV〕, 〔經文：John 3:16，WEB〕, 〔經文：Römer 5,8，LUT〕
# (【經文：…】 and an ASCII colon are accepted too; a Simplified 經 is converted before filling)
PLACEHOLDER_RE = re.compile(r"[〔【]\s*[經\u7ecf]文\s*[：:]\s*([^〔〕【】]{1,40}?)\s*[〕】]")
_TAG_VERSION = {**{n.lower(): v for v, n in VERSIONS.items()}, **{t.lower(): v for v, t in TAGS.items()},
                **{v: v for v in VERSIONS}}
_VERSION_RE = re.compile(r"\s*[,，、]\s*(" + "|".join(map(re.escape, _TAG_VERSION)) + r")\s*$", re.I)
_VERSE_NUMBER = re.compile(r"^\s*\d+:\d+\s*")


def _verse_lines(output: str) -> list[str]:
    """Verse texts from lookup_verse output: the 【版本】 header line dropped, verse numbers
    removed, and verses merged into the one before them (no text of their own) left out."""
    lines = [l for l in output.splitlines() if l.strip()]
    return [t for t in (_VERSE_NUMBER.sub("", l) for l in lines[1:]) if t != EMPTY_VERSE]


# A passage can end mid-sentence (1 Kor 13,5 "... rechnet das Böse nicht zu,"); its last
# comma, semicolon or colon is dropped so the quotation does not end on one.
_OPEN_END = re.compile(r"[,;:，；：、]+$")


def _balanced(text: str) -> str:
    """The 和合本 opens or closes a speech in the verse where it starts or ends (John 3:16 opens
    with 「 that a later verse closes); a mark left without its pair in the quoted verses comes off."""
    open_at, drop = [], set()
    for i, ch in enumerate(text):
        if ch in "「『":
            open_at.append(i)
        elif ch in "」』":
            if open_at:
                open_at.pop()
            else:
                drop.add(i)
    drop.update(open_at)
    return "".join(ch for i, ch in enumerate(text) if i not in drop)


def _render(output: str, version: str, label: str) -> str:
    verses = _verse_lines(output)
    if verses:
        verses[-1] = _OPEN_END.sub("", verses[-1].rstrip())
    lang = VERSION_LANG[version]
    if lang == "de":
        return f"„{' '.join(verses)}“ ({label}, {VERSIONS[version]})"  # German answers: „…“
    if lang == "en":
        return f"“{' '.join(verses)}” ({label}, {TAGS[version]})"  # English answers: ASCII brackets
    text = _balanced("".join(verses)).replace("「", "『").replace("」", "』")  # keep the outer 「」 unambiguous
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


# an English or German answer gets no Chinese words: the tool names become words in its language
_INTERNAL_EN = [
    (re.compile(r"`?(?:lookup_verse|fill_quote)`?"), "the Bible lookup"),
    (re.compile(r"`?cross_references`?"), "the cross-references"),
    (re.compile(r"`?wesley_note`?"), "Wesley's notes"),
]
_INTERNAL_DE = [
    (re.compile(r"`?(?:lookup_verse|fill_quote)`?"), "die Bibelsuche"),
    (re.compile(r"`?cross_references`?"), "die Querverweise"),
    (re.compile(r"`?wesley_note`?"), "Wesleys Anmerkungen"),
]
LOOKUP_FAILED = {"zh": "〔經文查詢失敗：{}〕", "en": "[Bible passage not found: {}]", "de": "[Bibelstelle nicht gefunden: {}]"}


def scrub_internal(text: str, lang: str = "zh") -> tuple[str, list[str]]:
    """Rewrite internal words in the final answer (in its language, zh, en or de); returns the
    text and what was changed."""
    changed = []
    for pattern, repl in {"en": _INTERNAL_EN, "de": _INTERNAL_DE}.get(lang, _INTERNAL):
        def sub(m, repl=repl):
            changed.append(m.group(0))
            return repl
        text = pattern.sub(sub, text)
    return text, changed


# The model sometimes answers in HTML (<p>, <strong>, <h3>) instead of Markdown; the page shows
# text, not HTML, so the common tags become their Markdown. Other tags are left as they are.
_HTML_MD = [
    (re.compile(r"<h[1-4][^>]*>\s*(.*?)\s*</h[1-4]>", re.I | re.S), r"\n\n## \1\n\n"),
    (re.compile(r"<li[^>]*>\s*(.*?)\s*</li>", re.I | re.S), r"\n- \1"),
    (re.compile(r"</?(?:strong|b)>", re.I), "**"),
    (re.compile(r"</?(?:em|i)>", re.I), "*"),
    (re.compile(r"<br\s*/?>", re.I), "\n"),
    (re.compile(r"</?(?:p|div|ul|ol|blockquote)[^>]*>", re.I), "\n\n"),
]


def html_to_markdown(text: str) -> str:
    if not re.search(r"</?(?:p|strong|b|em|i|h[1-4]|li|ul|ol|br|div|blockquote)\b[^>]*>", text, re.I):
        return text
    for pattern, repl in _HTML_MD:
        text = pattern.sub(repl, text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_CJK = re.compile(r"[㐀-鿿]")
_GERMAN = re.compile(r"[äöüßÄÖÜ]|\b(?:und|der|die|das|nicht|ist|ich|Sie|Gott|auch)\b")


def answer_language(text: str) -> str:
    """zh, en or de: the language an answer is written in, from its own words (the markers and
    their references left out). A marker without a version is filled in this language's Bible."""
    words = PLACEHOLDER_RE.sub(" ", text)
    cjk = len(_CJK.findall(words))
    latin = len(re.findall(r"[A-Za-zäöüßÄÖÜ]", words))
    if (cjk and cjk >= latin // 10) or latin < 20:  # too few words to tell: the 和合本, as before
        return "zh"
    return "de" if len(_GERMAN.findall(words)) >= 3 else "en"


def fill_placeholders(text: str, handlers: dict[str, Handler], bible: str | None = None) -> tuple[str, list[Any]]:
    """Replace every placeholder in ``text``; returns the new text and one ToolCall per
    placeholder (name fill_quote), so traces and graders see where the text came from.
    ``bible`` is the version the reader picked: a marker naming its language's default
    version (WEB, LUT), or naming none in an answer in that language, is filled from it instead,
    so the whole answer quotes one version."""
    from .loop import ToolCall  # loop imports this module

    calls: list[ToolCall] = []
    # an English or German answer never quotes the 和合本: a marker without a version there
    # (〔經文：Matthäus 28,19〕) takes that language's Bible, not the Chinese default
    lang = answer_language(text)
    default = DEFAULT_VERSION[lang]

    def replace(m: re.Match) -> str:
        body = m.group(1)
        v = _VERSION_RE.search(body)
        version = _TAG_VERSION.get(v.group(1).lower(), default) if v else default
        if lang != "zh" and VERSION_LANG[version] == "zh":
            version = default  # 〔經文：John 3:16，和合本〕 in an English answer: no Chinese there either
        if bible in VERSIONS and version == DEFAULT_VERSION.get(VERSION_LANG[bible]):
            version = bible
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
            return LOOKUP_FAILED[lang].format(reference)
        try:
            ref = parse_ref(reference)
            label = ref_label(ref, version)
        except RefError:
            label = reference
        return _render(output, version, label)

    return PLACEHOLDER_RE.sub(replace, text), calls
