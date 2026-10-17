"""Loads the prebuilt data files (see scripts/build_data.py) and answers lookups.

Data files live in ``data/`` and are flat JSON objects keyed by OSIS verse id
("John.3.16"):

- cuv.json      和合本（繁體）
- kjv.json      King James Version
- web.json      World English Bible (public domain; scripts/build_web.py)
- crossrefs.json  {"John.3.16": [["Rom.5.8", 96], ...]}  (OpenBible.info, CC-BY)
- wesley_nt.json  {"John.3.16": "Yea, and this was ..."}  (Wesley, Explanatory Notes upon the NT)
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR
from .refs import Ref

VERSIONS = {"cuv": "和合本", "kjv": "KJV", "web": "WEB"}


class Corpus:
    def __init__(self, data_dir: Path | str = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._bibles: dict[str, dict[str, str]] = {}
        self._crossrefs: dict[str, list[list]] | None = None
        self._wesley: dict[str, str] | None = None

    def _load(self, name: str):
        path = self.data_dir / name
        if not path.exists():
            raise FileNotFoundError(f"{path} 不存在，請先執行 python scripts/build_data.py")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def bible(self, version: str) -> dict[str, str]:
        if version not in VERSIONS:
            raise KeyError(version)
        if version not in self._bibles:
            bible = self._load(f"{version}.json")
            # The 和合本 source marks a verse merged into the one before it with the text "a"
            # (e.g. Luke 21:30, whose words are printed under 21:29); keep it as an empty verse.
            self._bibles[version] = {k: "" if v.strip() == "a" else v for k, v in bible.items()}
        return self._bibles[version]

    @property
    def crossrefs(self) -> dict[str, list[list]]:
        if self._crossrefs is None:
            self._crossrefs = self._load("crossrefs.json")
        return self._crossrefs

    @property
    def wesley(self) -> dict[str, str]:
        if self._wesley is None:
            self._wesley = self._load("wesley_nt.json")
        return self._wesley

    def has_verse(self, book: str, chapter: int, verse: int, version: str = "cuv") -> bool:
        return f"{book}.{chapter}.{verse}" in self.bible(version)

    def verse_text(self, book: str, chapter: int, verse: int, version: str = "cuv") -> str | None:
        return self.bible(version).get(f"{book}.{chapter}.{verse}")

    def passage(self, ref: Ref, version: str = "cuv") -> list[tuple[int, str]]:
        """[(verse, text)] for the range; raises KeyError naming the first missing verse."""
        out = []
        for ch, v in ref.verses():
            text = self.verse_text(ref.book, ch, v, version)
            if text is None:
                raise KeyError(f"{ref.book}.{ch}.{v}")
            out.append((v, text))
        return out


@lru_cache(maxsize=1)
def default_corpus() -> Corpus:
    return Corpus()


# ---------------------------------------------------------------- text normalisation

_ZH_KEEP = re.compile(r"[㐀-鿿豈-﫿0-9A-Za-z]")


def normalize_zh(text: str) -> str:
    """Keep only CJK characters, digits and letters, so punctuation, spacing and
    quote-mark differences do not count as a misquotation."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(_ZH_KEEP.findall(text))


def normalize_en(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str, version: str) -> str:
    return normalize_zh(text) if version == "cuv" else normalize_en(text)
