"""Original-language word studies built by the program, without a model.

    from theoclaw.common import original
    rows = original.word_study("路加福音 15:20")      # every content word of the passage
    rows += original.theme_words("恩典與成聖")        # the Strong's numbers a theme's words render
    print(original.render(rows))                     # a compact table for the research agent

The 和合本 with Strong's numbers (信望愛 FHL) says which original word each Chinese word
translates; the STEPBible lexicons (CC BY) give the lemma, transliteration and meaning; and the
whole tagged 和合本 gives the usual Chinese renderings of each word. A model only reads the
table; it does not choose the words or recall their meanings. Data: data/original/, built by
scripts/build_original.py.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .paths import DATA_DIR
from .refs import RefError, parse_ref

DIR = DATA_DIR / "original"
COMMON = 1500   # Strong's numbers more frequent than this (articles, 和, 他 ...) are left out
MAX_ROWS = 30
CREDIT = "原文資料：STEPBible.org（Tyndale House，CC BY 4.0）；和合本 Strong's 編號：信望愛 FHL"


def available() -> bool:
    return (DIR / "verses.json").is_file()


@lru_cache(maxsize=None)
def _load(name: str):
    return json.loads((DIR / name).read_text(encoding="utf-8"))


def _row(strong: str, words: str, where: str | None = None) -> dict | None:
    lex = _load("lexicon.json").get(strong)
    if lex is None:
        return None
    return {"strong": strong, "zh": words, "lemma": lex["lemma"], "translit": lex["translit"],
            "pos": lex["pos"], "gloss": lex["gloss"], "def": lex["def"],
            "renderings": [w for w, _ in _load("renderings.json").get(strong, [])[:4]],
            "count": _load("frequency.json").get(strong, 0), "where": [where] if where else []}


def word_study(reference: str, max_rows: int = MAX_ROWS) -> list[dict]:
    """The content words of a passage, in order, each original word once (with its verses)."""
    if not available():
        return []
    try:
        ref = parse_ref(reference)
    except RefError:
        return []
    verses = _load("verses.json")
    freq = _load("frequency.json")
    rows: dict[str, dict] = {}
    for v in range(ref.verse_start, ref.verse_end + 1):
        for words, strongs, minor in verses.get(f"{ref.book}.{ref.chapter}.{v}", []):
            if minor or not words:
                continue
            for s in strongs:
                if freq.get(s, 0) > COMMON:
                    continue
                where = f"{ref.chapter}:{v}"
                if s in rows:
                    if where not in rows[s]["where"]:
                        rows[s]["where"].append(where)
                    continue
                r = _row(s, words, where)
                if r:
                    rows[s] = r
    out = list(rows.values())
    if len(out) > max_rows:  # keep the rarer, more telling words, in passage order
        keep = {r["strong"] for r in sorted(out, key=lambda r: r["count"])[:max_rows]}
        out = [r for r in out if r["strong"] in keep]
    return out


def segment(text: str, longest: int = 6) -> list[str]:
    """Forward maximum matching against the 和合本's own vocabulary (words of 2+ characters)."""
    index = _load("zh_index.json")
    out, i = [], 0
    while i < len(text):
        for n in range(min(longest, len(text) - i), 1, -1):
            if text[i:i + n] in index:
                out.append(text[i:i + n])
                i += n
                break
        else:
            i += 1
    return out


def theme_words(text: str, per_word: int = 2, max_rows: int = 10) -> list[dict]:
    """The original words a theme's Chinese words usually translate (e.g. 恩典 -> χάρις, חֵן)."""
    if not available() or not text:
        return []
    from . import zh
    if zh.available():
        text = zh.to_traditional(text)
    index = _load("zh_index.json")
    freq = _load("frequency.json")
    rows, seen = [], set()
    for word in segment(text):
        for s, n in index.get(word, [])[:per_word]:
            if s in seen or freq.get(s, 0) > COMMON or n < 2:
                continue
            r = _row(s, word)
            if r:
                r["theme_matches"] = n
                rows.append(r)
                seen.add(s)
    return rows[:max_rows]


def render(rows: list[dict], def_chars: int = 140) -> str:
    """A compact table for a model to read."""
    if not rows:
        return ""
    lines = ["| 和合本 | 原文 | 音譯 | 詞性 | 字義（英文） | 和合本常見譯法 | 本段出現 | 全本次數 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        gloss = r["gloss"] + ("：" + r["def"][:def_chars] if r["def"] and r["def"] != r["gloss"] else "")
        lines.append(f"| {r['zh']} | {r['lemma']} ({r['strong']}) | {r['translit']} | {r['pos']} | "
                     f"{gloss.replace('|', '/')} | {'、'.join(r['renderings'])} | {', '.join(r['where']) or '主題'} | {r['count']} |")
    return "\n".join(lines) + f"\n\n{CREDIT}"
