"""Detect Simplified Chinese characters (the project rule: everything we generate is 繁體).

Needs opencc-python-reimplemented; without it the check reports "unknown" (None).
"""

from __future__ import annotations

import re
from functools import lru_cache

CJK_RUN = re.compile(r"[㐀-鿿]+")
# Characters opencc's s2t rewrites even though they are standard in Hong Kong/Taiwan usage.
ALLOWED = set("着")
# Characters s2t rewrites on their own that are also ordinary Traditional characters
# (皇后, 鄰里, 干戈, 准許 ...). Checked one character at a time, these are not evidence
# of Simplified text.
DUAL_USE = set("干里后台余范云采征准于丑斗吁")


@lru_cache(maxsize=1)
def _s2t():
    try:
        import opencc
    except ImportError:
        return None
    return opencc.OpenCC("s2t")


def available() -> bool:
    return _s2t() is not None


@lru_cache(maxsize=1)
def traditional_reference() -> frozenset[str]:
    """Every character the 繁體 和合本 uses (data/cuv.json). opencc's s2t also rewrites
    variant forms that are ordinary Traditional characters (吃 -> 喫, 群 -> 羣, 峰 -> 峯,
    床, 唇 ...); a character the 和合本 itself uses is not evidence of Simplified text."""
    import json
    from .paths import DATA_DIR
    path = DATA_DIR / "cuv.json"
    if not path.is_file():
        return frozenset()

    def strings(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from strings(v)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v)

    return frozenset("".join(CJK_RUN.findall("".join(strings(json.loads(path.read_text(encoding="utf-8")))))))


def simplified_chars(text: str, phrases: bool = False) -> set[str] | None:
    """Simplified characters in ``text``, or None if opencc is not installed.

    By default each character is checked on its own, so Traditional text quoted from
    the 和合本 (顯明了) is not flagged for phrase-level rewrites (明了 -> 明瞭). With
    phrases=True whole runs are converted, which also flags such phrases."""
    conv = _s2t()
    if conv is None:
        return None
    ok = ALLOWED | DUAL_USE | traditional_reference()
    bad: set[str] = set()
    for run in CJK_RUN.findall(text):
        if phrases:
            bad |= {a for a, b in zip(run, conv.convert(run)) if a != b and a not in ALLOWED}
        else:
            bad |= {a for a in set(run) if a not in ok and conv.convert(a) != a}
    return bad


def fix_simplified(text: str) -> tuple[str, list[str]]:
    """Replace the Simplified characters in ``text`` with their 繁體 forms; returns the text
    and the characters replaced. Only flagged characters change (see simplified_chars), so
    Traditional wording around them is left alone; each run is converted as a whole first,
    so a character that maps to two Traditional forms gets the one its context needs."""
    conv = _s2t()
    bad = simplified_chars(text) if conv is not None else None
    if not bad:
        return text, []

    def fix_run(m: re.Match) -> str:
        run = m.group(0)
        whole = conv.convert(run)
        if len(whole) == len(run):
            return "".join(b if a in bad else a for a, b in zip(run, whole))
        return "".join(conv.convert(a) if a in bad else a for a in run)

    return CJK_RUN.sub(fix_run, text), sorted(bad)


def to_traditional(text: str) -> str:
    conv = _s2t()
    if conv is None:
        raise RuntimeError("pip install opencc-python-reimplemented (needed to convert to 繁體)")
    return conv.convert(text)


def width(text: str) -> int:
    """Display width in a terminal: CJK characters take two columns."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text: str, n: int) -> str:
    """Left-aligned to n display columns (for tables with Chinese file names)."""
    return text + " " * max(0, n - width(text))
