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

import re

from .paths import DATA_DIR
from .refs import RefError, parse_ref

DIR = DATA_DIR / "original"
# opencc's s2t gives some variant forms; the 繁體 和合本 (data/cuv.json) writes these
VARIANTS = str.maketrans({"爲": "為", "裏": "裡", "啓": "啟", "衆": "眾", "麪": "麵", "牀": "床", "綫": "線"})
SHARE = 0.1      # a Chinese word's candidate original words: those behind at least 10% of its uses
PER_WORD = 4     # ... at most this many
NEAR_KEYS = 12   # an approximate match looks at this many 和合本 words containing the query
_SPLIT = r"[，,。；;、\s與和及跟同或的之在對於]+"
COMMON = 1500   # Strong's numbers more frequent than this (articles, 和, 他 ...) are left out
MAX_ROWS = 30
CREDIT = "原文資料：STEPBible.org（Tyndale House，CC BY 4.0）；和合本 Strong's 編號：信望愛 FHL"
CREDIT_EN = ("Original-language data: STEPBible.org (Tyndale House, CC BY 4.0); Strong's numbers from the "
             "Strong's-tagged Chinese Union Version (FHL).")


def to_hant(text: str) -> str:
    """繁體 with the 和合本's forms, so a Simplified or variant-form query still matches."""
    from . import zh
    if zh.available():
        text = zh.to_traditional(text)
    return text.translate(VARIANTS)


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
            "renderings": [w for w, _ in _load("renderings.json").get(strong, [])[:6]],
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
    """Every 和合本 word (2+ characters) in the text, the longest at each position; a word
    inside one already found is skipped, so 恩典 is not found again inside 恩典的."""
    index = _load("zh_index.json")
    out: list[str] = []
    for i in range(len(text)):
        for n in range(min(longest, len(text) - i), 1, -1):
            w = text[i:i + n]
            if w in index:
                if not any(w in o for o in out):
                    out.append(w)
                break
    return out


def _near(word: str) -> list[tuple[str, int]]:
    """For a word the 和合本 does not use as such (謙虛): the original words behind the
    和合本 words that contain it or that it contains, weighted by how often they are used."""
    index = _load("zh_index.json")
    keys = [k for k in index if len(k) >= 2 and (word in k or k in word)]
    keys.sort(key=lambda k: -sum(n for _, n in index[k]))
    total: dict[str, int] = {}
    for k in keys[:NEAR_KEYS]:
        for st, n in index[k]:
            total[st] = total.get(st, 0) + n
    return sorted(total.items(), key=lambda x: -x[1])


def _related(word: str, strongs: list[str]) -> list[tuple[str, int]]:
    """Near-synonyms through the translation itself: the 和合本's other renderings of the
    word's original words (恩典 -> χάρις -> 恩惠), and the original words behind those
    renderings (恩惠 -> חֵן). Sharing a character is not enough (恩典 is not 典章)."""
    index = _load("zh_index.json")
    renderings = _load("renderings.json")
    total: dict[str, int] = {}
    for st in strongs:
        for other, _ in renderings.get(st, [])[:6]:
            if other == word or len(other) < 2:
                continue
            for st2, n in index.get(other, []):
                if st2 not in strongs:
                    total[st2] = total.get(st2, 0) + n
    return sorted(total.items(), key=lambda x: -x[1])


def _candidates(pairs, freq: dict) -> list[tuple[str, int]]:
    pairs = [(st, n) for st, n in pairs if freq.get(st, 0) <= COMMON and n >= 2]
    total = sum(n for _, n in pairs) or 1
    return [(st, n) for st, n in pairs if n / total >= SHARE][:PER_WORD]


def theme_words(text: str, max_rows: int = 14) -> list[dict]:
    """The original words a theme's Chinese words translate (恩典 -> χάρις, חֵן ...), up to four
    per word when the 和合本 uses the word for several. A word the 和合本 does not use as such
    gets an approximate match through the words containing it, marked "near"."""
    if not available() or not text:
        return []
    text = to_hant(text)
    index = _load("zh_index.json")
    freq = _load("frequency.json")
    pieces = [w for w in re.split(_SPLIT, text) if w]
    words = segment(text) + [w for w in pieces if len(w) == 1 and w in index]  # 愛, 信, 罪 on their own
    leftovers = [w for w in pieces if len(w) >= 2 and not any(w in x or x in w for x in words)]
    jobs = [(w, index[w], "exact") for w in words] + [(w, _near(w), "near") for w in leftovers]
    # near-synonyms in the 和合本's own translation (恩典 -> 恩惠 -> חֵן), at most two per word
    for w in words:
        own = [st for st, _ in _candidates(index[w], freq)]
        jobs.append((w, _related(w, own)[:2], "near"))
    rows, seen = [], set()
    for word, pairs, match in jobs:
        for st, n in _candidates(pairs, freq):
            if st in seen:
                continue
            r = _row(st, word)
            if r:
                r["theme_matches"], r["match"] = n, match
                rows.append(r)
                seen.add(st)
    return rows[:max_rows]


def render(rows: list[dict], def_chars: int = 140, lang: str = "zh") -> str:
    """A compact table for a model (and the pastor) to read; lang="en" for an English-speaking
    pastor: the original word, transliteration, part of speech and English meaning, without the
    Chinese renderings (there is no Strong's-tagged English Bible here to give the KJV's words)."""
    if not rows:
        return ""
    if lang == "en":
        lines = ["| Original | Transliteration | Part of speech | Meaning | In this passage | Times in the Bible |",
                 "|---|---|---|---|---|---|"]
        for r in rows:
            gloss = r["gloss"] + (": " + r["def"][:def_chars] if r["def"] and r["def"] != r["gloss"] else "")
            where = ", ".join(r["where"]) or "theme"
            lines.append(f"| {r['lemma']} ({r['strong']}) | {r['translit']} | {r['pos']} | {gloss.replace('|', '/')} | "
                         f"{where} | {r['count']} |")
        return "\n".join(lines) + f"\n\n{CREDIT_EN}"
    lines = ["| 和合本 | 原文 | 音譯 | 詞性 | 字義（英文） | 和合本常見譯法 | 本段出現 | 全本次數 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        gloss = r["gloss"] + ("：" + r["def"][:def_chars] if r["def"] and r["def"] != r["gloss"] else "")
        where = ", ".join(r["where"]) or ("主題（近似）" if r.get("match") == "near" else "主題")
        lines.append(f"| {r['zh']} | {r['lemma']} ({r['strong']}) | {r['translit']} | {r['pos']} | "
                     f"{gloss.replace('|', '/')} | {'、'.join(r['renderings'])} | {where} | {r['count']} |")
    note = ("\n「主題（近似）」：和合本沒有這個詞，是從含有它的和合本用詞推出來的原文，只作參考。"
            if any(r.get("match") == "near" for r in rows) else "")
    return "\n".join(lines) + note + f"\n\n{CREDIT}"
