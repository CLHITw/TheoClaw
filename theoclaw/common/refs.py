"""Bible reference parsing and formatting.

A reference is identified by OSIS book id plus chapter and verse range, e.g.
``Ref("John", 3, 16, 16)``. Parsing accepts 繁體 names and abbreviations
(約翰福音 3:16, 約3:16, 約翰福音三章十六節), English names (John 3:16,
1 Cor 13:4-7) and OSIS ids (John.3.16).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (OSIS id, 繁體全名, 繁體簡稱, English name, extra English aliases)
BOOKS: list[tuple[str, str, str, str, tuple[str, ...]]] = [
    ("Gen", "創世記", "創", "Genesis", ("Gen",)),
    ("Exod", "出埃及記", "出", "Exodus", ("Exod", "Ex")),
    ("Lev", "利未記", "利", "Leviticus", ("Lev",)),
    ("Num", "民數記", "民", "Numbers", ("Num",)),
    ("Deut", "申命記", "申", "Deuteronomy", ("Deut", "Dt")),
    ("Josh", "約書亞記", "書", "Joshua", ("Josh",)),
    ("Judg", "士師記", "士", "Judges", ("Judg",)),
    ("Ruth", "路得記", "得", "Ruth", ()),
    ("1Sam", "撒母耳記上", "撒上", "1 Samuel", ("1Sam", "I Samuel")),
    ("2Sam", "撒母耳記下", "撒下", "2 Samuel", ("2Sam", "II Samuel")),
    ("1Kgs", "列王紀上", "王上", "1 Kings", ("1Kgs", "I Kings")),
    ("2Kgs", "列王紀下", "王下", "2 Kings", ("2Kgs", "II Kings")),
    ("1Chr", "歷代志上", "代上", "1 Chronicles", ("1Chr", "I Chronicles")),
    ("2Chr", "歷代志下", "代下", "2 Chronicles", ("2Chr", "II Chronicles")),
    ("Ezra", "以斯拉記", "拉", "Ezra", ()),
    ("Neh", "尼希米記", "尼", "Nehemiah", ("Neh",)),
    ("Esth", "以斯帖記", "斯", "Esther", ("Esth",)),
    ("Job", "約伯記", "伯", "Job", ()),
    ("Ps", "詩篇", "詩", "Psalms", ("Psalm", "Ps", "Psa")),
    ("Prov", "箴言", "箴", "Proverbs", ("Prov",)),
    ("Eccl", "傳道書", "傳", "Ecclesiastes", ("Eccl", "Eccles")),
    ("Song", "雅歌", "歌", "Song of Solomon", ("Song", "Song of Songs")),
    ("Isa", "以賽亞書", "賽", "Isaiah", ("Isa",)),
    ("Jer", "耶利米書", "耶", "Jeremiah", ("Jer",)),
    ("Lam", "耶利米哀歌", "哀", "Lamentations", ("Lam",)),
    ("Ezek", "以西結書", "結", "Ezekiel", ("Ezek",)),
    ("Dan", "但以理書", "但", "Daniel", ("Dan",)),
    ("Hos", "何西阿書", "何", "Hosea", ("Hos",)),
    ("Joel", "約珥書", "珥", "Joel", ()),
    ("Amos", "阿摩司書", "摩", "Amos", ()),
    ("Obad", "俄巴底亞書", "俄", "Obadiah", ("Obad",)),
    ("Jonah", "約拿書", "拿", "Jonah", ()),
    ("Mic", "彌迦書", "彌", "Micah", ("Mic",)),
    ("Nah", "那鴻書", "鴻", "Nahum", ("Nah",)),
    ("Hab", "哈巴谷書", "哈", "Habakkuk", ("Hab",)),
    ("Zeph", "西番雅書", "番", "Zephaniah", ("Zeph",)),
    ("Hag", "哈該書", "該", "Haggai", ("Hag",)),
    ("Zech", "撒迦利亞書", "亞", "Zechariah", ("Zech",)),
    ("Mal", "瑪拉基書", "瑪", "Malachi", ("Mal",)),
    ("Matt", "馬太福音", "太", "Matthew", ("Matt", "Mt")),
    ("Mark", "馬可福音", "可", "Mark", ("Mk",)),
    ("Luke", "路加福音", "路", "Luke", ("Lk",)),
    ("John", "約翰福音", "約", "John", ("Jn",)),
    ("Acts", "使徒行傳", "徒", "Acts", ()),
    ("Rom", "羅馬書", "羅", "Romans", ("Rom",)),
    ("1Cor", "哥林多前書", "林前", "1 Corinthians", ("1Cor", "1 Cor", "I Corinthians")),
    ("2Cor", "哥林多後書", "林後", "2 Corinthians", ("2Cor", "2 Cor", "II Corinthians")),
    ("Gal", "加拉太書", "加", "Galatians", ("Gal",)),
    ("Eph", "以弗所書", "弗", "Ephesians", ("Eph",)),
    ("Phil", "腓立比書", "腓", "Philippians", ("Phil",)),
    ("Col", "歌羅西書", "西", "Colossians", ("Col",)),
    ("1Thess", "帖撒羅尼迦前書", "帖前", "1 Thessalonians", ("1Thess", "1 Thess", "I Thessalonians")),
    ("2Thess", "帖撒羅尼迦後書", "帖後", "2 Thessalonians", ("2Thess", "2 Thess", "II Thessalonians")),
    ("1Tim", "提摩太前書", "提前", "1 Timothy", ("1Tim", "1 Tim", "I Timothy")),
    ("2Tim", "提摩太後書", "提後", "2 Timothy", ("2Tim", "2 Tim", "II Timothy")),
    ("Titus", "提多書", "多", "Titus", ("Tit",)),
    ("Phlm", "腓利門書", "門", "Philemon", ("Phlm", "Philem")),
    ("Heb", "希伯來書", "來", "Hebrews", ("Heb",)),
    ("Jas", "雅各書", "雅", "James", ("Jas",)),
    ("1Pet", "彼得前書", "彼前", "1 Peter", ("1Pet", "1 Pet", "I Peter")),
    ("2Pet", "彼得後書", "彼後", "2 Peter", ("2Pet", "2 Pet", "II Peter")),
    ("1John", "約翰一書", "約壹", "1 John", ("1John", "1 Jn", "I John")),
    ("2John", "約翰二書", "約貳", "2 John", ("2John", "2 Jn", "II John")),
    ("3John", "約翰三書", "約參", "3 John", ("3John", "3 Jn", "III John")),
    ("Jude", "猶大書", "猶", "Jude", ()),
    ("Rev", "啟示錄", "啟", "Revelation", ("Rev", "Revelation of John")),
]

OSIS_IDS = [b[0] for b in BOOKS]
BOOK_INDEX = {b[0]: i for i, b in enumerate(BOOKS)}
ZH_NAME = {b[0]: b[1] for b in BOOKS}
EN_NAME = {b[0]: b[3] for b in BOOKS}
NT_BOOKS = set(OSIS_IDS[39:])

_ZH_LOOKUP: dict[str, str] = {}
for _osis, _full, _abbr, _en, _aliases in BOOKS:
    _ZH_LOOKUP[_full] = _osis
    _ZH_LOOKUP[_abbr] = _osis
# Common alternative forms (all 繁體).
_ZH_LOOKUP.update({"約翰壹書": "1John", "約翰貳書": "2John", "約翰參書": "3John",
                   "約一": "1John", "約二": "2John", "約三": "3John"})

_EN_LOOKUP: dict[str, str] = {}
for _osis, _full, _abbr, _en, _aliases in BOOKS:
    for _name in (_osis, _en, *_aliases):
        _EN_LOOKUP[re.sub(r"[\s.]", "", _name).lower()] = _osis


@dataclass(frozen=True, order=True)
class Ref:
    book: str  # OSIS id
    chapter: int
    verse_start: int
    verse_end: int

    @property
    def is_single(self) -> bool:
        return self.verse_start == self.verse_end

    def osis(self) -> str:
        base = f"{self.book}.{self.chapter}.{self.verse_start}"
        return base if self.is_single else f"{base}-{self.book}.{self.chapter}.{self.verse_end}"

    def zh(self) -> str:
        v = str(self.verse_start) if self.is_single else f"{self.verse_start}-{self.verse_end}"
        return f"{ZH_NAME[self.book]} {self.chapter}:{v}"

    def en(self) -> str:
        v = str(self.verse_start) if self.is_single else f"{self.verse_start}-{self.verse_end}"
        return f"{EN_NAME[self.book]} {self.chapter}:{v}"

    def verses(self) -> list[tuple[int, int]]:
        return [(self.chapter, v) for v in range(self.verse_start, self.verse_end + 1)]


class RefError(ValueError):
    pass


_CN_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(s: str) -> int:
    """Convert 一百五十 / 十六 / 二十三 / 119 to int."""
    if s.isdigit():
        return int(s)
    total, cur = 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            cur = _CN_DIGITS[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        else:
            raise RefError(f"無法解析數字：{s}")
    return total + cur


_NUM = r"[0-9〇零一二兩三四五六七八九十百]+"
_DASH = r"[-–—~～至到]"
_COLON = r"[:：.]"

# Longest names first so 約翰一書 wins over 約, 約壹 over 約.
_ZH_NAMES_SORTED = sorted(_ZH_LOOKUP, key=len, reverse=True)
_ZH_BOOK_RE = "|".join(re.escape(n) for n in _ZH_NAMES_SORTED)

# 約翰福音 3:16-18 / 約3:16 / 約翰福音3章16節 / 約翰福音三章十六至十八節
_ZH_REF_RE = re.compile(
    rf"(?P<book>{_ZH_BOOK_RE})\s*"
    rf"(?:第?(?P<ch>{_NUM})\s*(?:章|篇)\s*第?(?P<v1>{_NUM})\s*(?:節)?(?:\s*{_DASH}\s*第?(?P<v2>{_NUM})\s*節?)?"
    rf"|(?P<ch2>\d+)\s*{_COLON}\s*(?P<v3>\d+)(?:\s*{_DASH}\s*(?P<v4>\d+))?)"
)

_EN_REF_RE = re.compile(
    r"(?P<book>(?:[123]|I{1,3})?\s?[A-Za-z][A-Za-z. ]*?)\s*"
    r"(?P<ch>\d+)\s*[:.]\s*(?P<v1>\d+)(?:\s*[-–]\s*(?:(?P=book)\s*\.?\s*(?P=ch)\s*\.\s*)?(?P<v2>\d+))?$"
)


def _mk(book: str, ch: int, v1: int, v2: int | None) -> Ref:
    v2 = v2 if v2 is not None else v1
    if ch < 1 or v1 < 1 or v2 < v1:
        raise RefError("章節數字不合理")
    return Ref(book, ch, v1, v2)


def parse_ref(text: str, _retry: bool = False) -> Ref:
    """Parse one reference. Raises RefError when it cannot be understood."""
    s = text.strip()
    if not s:
        raise RefError("經文出處為空")
    # OSIS: John.3.16 or John.3.16-John.3.18
    m = re.fullmatch(r"([1-3]?[A-Za-z]+)\.(\d+)\.(\d+)(?:-(?:\1\.\2\.)?(\d+))?", s)
    if m and m.group(1) in BOOK_INDEX:
        return _mk(m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)) if m.group(4) else None)
    m = _ZH_REF_RE.match(s)
    if m and m.end() >= len(s.rstrip("。. ")):
        book = _ZH_LOOKUP[m.group("book")]
        if m.group("ch2"):
            return _mk(book, int(m.group("ch2")), int(m.group("v3")),
                       int(m.group("v4")) if m.group("v4") else None)
        return _mk(book, cn_to_int(m.group("ch")), cn_to_int(m.group("v1")),
                   cn_to_int(m.group("v2")) if m.group("v2") else None)
    m = _EN_REF_RE.match(s)
    if m:
        key = re.sub(r"[\s.]", "", m.group("book")).lower()
        if key in _EN_LOOKUP:
            return _mk(_EN_LOOKUP[key], int(m.group("ch")), int(m.group("v1")),
                       int(m.group("v2")) if m.group("v2") else None)
    if not _retry:  # Simplified book names and s2t variant forms (啓示錄): retry in the 和合本's forms
        from .zh import to_hant
        t = to_hant(s)
        if t != s:
            try:
                return parse_ref(t, _retry=True)
            except RefError:
                pass
    raise RefError(f"無法辨識的經文出處：{text}")


def extract_refs(text: str) -> list[Ref]:
    """Find every 繁體-style reference in free text (an agent's answer), in order.

    Only Chinese-form references are extracted; a bare abbreviation like 約 counts
    only when directly followed by chapter:verse, so ordinary prose is not misread.
    """
    found: list[Ref] = []
    for m in _ZH_REF_RE.finditer(text):
        try:
            book = _ZH_LOOKUP[m.group("book")]
            if m.group("ch2"):
                ref = _mk(book, int(m.group("ch2")), int(m.group("v3")),
                          int(m.group("v4")) if m.group("v4") else None)
            else:
                ref = _mk(book, cn_to_int(m.group("ch")), cn_to_int(m.group("v1")),
                          cn_to_int(m.group("v2")) if m.group("v2") else None)
        except RefError:
            continue
        found.append(ref)
    return found
