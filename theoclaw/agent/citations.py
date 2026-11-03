"""Citation numbers in an answer must come from what this run actually read.

Answers cite confessions and books by number: 第三十一章第4條, Article XI, Q. 21, p. 45,
段落 1612, WCF 31.4. The model sometimes writes a number it never looked up (a chapter it did
not open, a paragraph it remembers). In the spirit of the scripture misquote check, every such
number is looked for in the run's evidence (the question and every tool output, including the
pages a tool was asked for); a number that is not there is dropped and the sentence keeps only
the document's name.

Scripture references (羅馬書 5:8, 羅馬書第 3 章, chapter 8 of Romans) are never touched.
"""

from __future__ import annotations

import json
import re

from ..common.refs import EN_NAME, ZH_NAME, cn_to_int

_CN = r"[〇零一二兩三四五六七八九十百]+"
_N = rf"(?:\d+|{_CN})"
_ROMAN = r"(?:[IVXLCDM]+|[ivxlcdm]+)"
_ROMAN_VAL = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
KINDS = ("article", "chapter", "question", "page", "paragraph", "hymn")


def _roman(s: str) -> int | None:
    s = s.upper()
    if not s or any(c not in _ROMAN_VAL for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = _ROMAN_VAL[c]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def _num(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if re.fullmatch(_CN, s):
        try:
            return cn_to_int(s)
        except (ValueError, KeyError):
            return None
    return _roman(s)


_ZH_KIND = {"條": "article", "章": "chapter", "問": "question", "頁": "page", "首": "hymn"}
_EN_KIND = [
    (r"(?:Articles?|Art\.)", "article"),
    (r"(?:Chapters?|Chap\.|Ch\.)", "chapter"),
    (r"(?:Questions?|Q\.?)", "question"),
    (r"(?:pp?\.|pages?)", "page"),
    (r"(?:paragraphs?|paras?\.?|par\.)", "paragraph"),
    (r"(?:Hymn)", "hymn"),
]
_RANGE = r"(?:\s*[-–—~至到]\s*\d+)?"

# 第三十一章第4條: chapter and section, checked as a pair
_ZH_SECTION = re.compile(rf"第\s*({_N})\s*章\s*第\s*({_N})\s*[條節]")
# 第 31 章 / 第十一條 / 第 74 問 / 第 21 頁 / 第 888 首 / 段落 1612 / 問 98
_ZH_CITE = re.compile(rf"第\s*({_N})\s*([條章問頁首])|段落\s*(\d+){_RANGE}|問\s*(\d+)")
# Article XI / Art. IV / Chapter 31 / chap. xxix / Q. 21 / Question 74 / p. 45 / pp. 45-46 / par. 994
_EN_CITE = re.compile(r"\b(" + "|".join(p for p, _ in _EN_KIND) + rf")\s*(\d+|{_ROMAN})\b{_RANGE}", re.I)
# WCF 31.4 / WLC 79 / WSC Q1 / HC 74
_ABBR_CITE = re.compile(r"\b(WCF|WLC|WSC|HC)\s*(Q?)\s*(\d+)(?:\.(\d+))?\b")

_BOOK_NAMES = sorted({*ZH_NAME.values(), *EN_NAME.values()}, key=len, reverse=True)
_BOOKS = "|".join(re.escape(n) for n in _BOOK_NAMES)
_BOOK_BEFORE = re.compile(rf"(?:{_BOOKS})\s*$")
_BOOK_AFTER = re.compile(rf"\s*(?:of\s+)?(?:{_BOOKS})")
_CHAPTER_HEAD = re.compile(rf"(?:Chap(?:ter)?\.?|CHAPTER)\s*({_ROMAN}|\d+)\b", re.I)
_SECTION_LINE = re.compile(r"(?:^|\n)\s*(\d{1,2})\s*(?:\n|\.\s)")


def _en_kind(word: str) -> str:
    for pattern, kind in _EN_KIND:
        if re.fullmatch(pattern, word, re.I):
            return kind
    return "article"


def evidence_numbers(texts: list[str]) -> dict[str, set[int]]:
    """Every citable number in the evidence, by kind; 'section' holds chapter*1000+section."""
    found: dict[str, set[int]] = {k: set() for k in KINDS}
    found["section"] = set()
    found["bare"] = set()
    for t in texts:
        for m in _ZH_CITE.finditer(t):
            if m.group(1):
                n = _num(m.group(1))
                if n is not None:
                    found[_ZH_KIND[m.group(2)]].add(n)
            elif m.group(3):
                found["paragraph"].add(int(m.group(3)))
            elif m.group(4):
                found["question"].add(int(m.group(4)))
        for m in _EN_CITE.finditer(t):
            n = _num(m.group(2))
            if n is not None:
                found[_en_kind(m.group(1))].add(n)
        for m in re.finditer(r"\bQ\s*(\d+)\b", t):
            found["question"].add(int(m.group(1)))
        # article headings ("XXXIV. Of the Traditions", "V. OF THE LAW") and numbered paragraphs
        # inside a chapter ("6. The ...", "Art. VII. Election ..."), which answers cite as 第 N 條
        for m in re.finditer(r"(?m)^\s*(?:Art\.\s*)?([IVXLC]+|\d{1,2})\.\s+(?=[A-Za-z(\[])", t):
            n = _num(m.group(1))
            if n is not None:
                found["article"].add(n)
        # a bare section number on its own line (WCF "6", then "AS God hath ..."): only for chapter.section pairs
        for m in re.finditer(r"(?m)^\s*(\d{1,2})\s*$(?=\n[A-Z])", t):
            found["bare"].add(int(m.group(1)))
        # a chapter heading followed by numbered sections on their own lines (WCF "Chap. xxix", then "1", "2" ...)
        heads = list(_CHAPTER_HEAD.finditer(t))
        for i, h in enumerate(heads):
            c = _num(h.group(1))
            if c is None:
                continue
            end = heads[i + 1].start() if i + 1 < len(heads) else len(t)
            for s in _SECTION_LINE.finditer(t[h.end():end]):
                found["section"].add(c * 1000 + int(s.group(1)))
    return found


def _calls(step):
    calls = step.tool_calls if hasattr(step, "tool_calls") else step.get("tool_calls", [])
    return [c if isinstance(c, dict) else vars(c) for c in calls]


def _evidence(prompt: str, steps: list) -> list[str]:
    texts = [prompt]
    for step in steps:
        for c in _calls(step):
            if c.get("is_error"):
                continue
            texts.append(str(c.get("output") or ""))
            inp = c.get("input") or {}
            for part in str(inp.get("pages") or "").replace(" ", "").split(","):
                a, _, b = part.partition("-")
                if a.isdigit() and (not b or (b.isdigit() and int(b) - int(a) <= 50)):
                    texts.append(" ".join(f"第 {p} 頁" for p in range(int(a), int(b or a) + 1)))
            texts.append(json.dumps(inp, ensure_ascii=False))
    return texts


def _is_scripture(text: str, start: int, end: int) -> bool:
    """A chapter number next to a Bible book's name is a scripture reference."""
    return bool(_BOOK_BEFORE.search(text[max(0, start - 30):start]) or _BOOK_AFTER.match(text, end))


_CLEAN = [
    (re.compile(r"[（(]\s*[，,、;；\s]*[）)]"), ""),          # an emptied parenthesis
    (re.compile(r"([（(])\s*[，,、;；]\s*"), r"\1"),
    (re.compile(r"\s*[，,、;；]\s*([）)])"), r"\1"),
    (re.compile(r"([，,、])\s*[，,、]"), r"\1"),
    (re.compile(r"[ \t]{2,}"), " "),
    (re.compile(r" +([，。、；：）)])"), r"\1"),
]


def check_citations(text: str, prompt: str, steps: list) -> tuple[str, list[str]]:
    """Drop citation numbers not found in the run's evidence; returns the text and what was dropped."""
    ev = evidence_numbers(_evidence(prompt, steps))
    drop: list[tuple[int, int]] = []
    keep: list[tuple[int, int]] = []   # verified pairs: their parts are not checked again

    def taken(pos: int) -> bool:
        return any(a <= pos < b for a, b in keep + drop)

    for m in _ABBR_CITE.finditer(text):
        main, sub = int(m.group(3)), m.group(4)
        if m.group(1) == "WCF":
            good = main in ev["chapter"] if sub is None else (main * 1000 + int(sub)) in ev["section"]
        else:
            good = main in ev["question"]
        (keep if good else drop).append((m.start(2), m.end()) if not good else m.span())
    for m in _ZH_SECTION.finditer(text):
        if _is_scripture(text, m.start(), m.end()):
            continue
        c, s = _num(m.group(1)), _num(m.group(2))
        good = c is not None and s is not None and (
            (c * 1000 + s) in ev["section"] or (c in ev["chapter"] and (s in ev["article"] or s in ev["bare"])))
        (keep if good else drop).append(m.span())
    for m in _ZH_CITE.finditer(text):
        if taken(m.start()):
            continue
        if m.group(1):
            kind, n = _ZH_KIND[m.group(2)], _num(m.group(1))
            if kind == "chapter" and _is_scripture(text, m.start(), m.end()):
                continue
        elif m.group(3):
            kind, n = "paragraph", int(m.group(3))
        else:
            kind, n = "question", int(m.group(4))
        if n is not None and n not in ev[kind] and not (kind == "paragraph" and n in ev["article"]):
            drop.append(m.span())
    for m in _EN_CITE.finditer(text):
        if taken(m.start()):
            continue
        kind, n = _en_kind(m.group(1)), _num(m.group(2))
        if kind == "chapter" and _is_scripture(text, m.start(), m.end()):
            continue
        if n is not None and n not in ev[kind] and not (kind == "paragraph" and n in ev["article"]):
            end = m.end() + (3 if text.startswith(" of ", m.end()) else 0)  # "Article XI of the Augsburg Confession"
            drop.append((m.start(), end))
    if not drop:
        return text, []
    dropped, out, last = [], [], 0
    for a, b in sorted(drop):
        if a < last:
            continue
        dropped.append(text[a:b].strip())
        out.append(text[last:a])
        last = b
    out.append(text[last:])
    text = "".join(out)
    for pattern, repl in _CLEAN:
        text = pattern.sub(repl, text)
    return text, dropped
