"""Bible-dictionary tools for pastor mode: ISBE (1915), Easton (1897) and Smith (1884), all public
domain, looked up by program (no model, no tokens until the result is read).

    dictionary_entry   the entry for a headword (SAMARIA, GRACE ...) in each dictionary
    dictionary_search  BM25 over all entries, for a topic without a headword of its own

Data: data/reference/, built by scripts/build_reference.py from the CrossWire modules.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from ..common.paths import DATA_DIR
from ..common.tooling import Handler, ToolError

DIR = DATA_DIR / "reference"
SOURCES = {"isbe": "ISBE（國際標準聖經百科，1915）", "easton": "Easton 聖經辭典（1897）", "smith": "Smith 聖經辭典（1884）"}
PART_CHARS = 4000

TOOL_DEFS: list[dict] = [
    {
        "name": "dictionary_entry",
        "description": ("查聖經百科辭典的條目（ISBE、Easton、Smith，英文，公共領域）。用英文條目名，例如 SAMARIA、"
                        "GRACE、PHARISEES、JACOB'S WELL。條目很長時用 part 讀下一段。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "英文條目名（人名、地名、風俗、神學詞）。"},
                "source": {"type": "string", "enum": ["all", "isbe", "easton", "smith"], "description": "預設 all。"},
                "part": {"type": "integer", "description": "第幾段（從 1 開始），預設 1。"},
            },
            "required": ["term"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dictionary_search",
        "description": "在三部聖經百科辭典的全文中做英文關鍵詞檢索，回傳最相關的條目片段。沒有現成條目名時用。",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "英文關鍵詞。"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]

SYSTEM_ADDENDUM = """
聖經百科辭典（dictionary_entry、dictionary_search）的使用方式：
1. 用來查背景：人物、地名、風俗、歷史、詞語。用英文條目名查；查不到就用 dictionary_search。
2. 這些是 1884–1915 年的英文著作，學術觀點可能過時；引用時註明辭典名稱與條目，並把要點譯成中文。
"""


def available() -> bool:
    return all((DIR / f"{s}.json").is_file() for s in SOURCES)


@lru_cache(maxsize=None)
def _load(source: str) -> dict[str, str]:
    return json.loads((DIR / f"{source}.json").read_text(encoding="utf-8"))


def _norm(key: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", key.upper())


@lru_cache(maxsize=None)
def _by_norm(source: str) -> dict[str, str]:
    """JACOBSWELL -> JACOB'S WELL: punctuation and spacing do not have to match."""
    out: dict[str, str] = {}
    for k in _load(source):
        out.setdefault(_norm(k), k)
    return out


def _variants(term: str) -> list[str]:
    t = re.sub(r"\s+", " ", term.strip().upper())
    out = [t, t.replace("’", "'")]
    if t.endswith("S"):
        out.append(t[:-1])
    else:
        out.append(t + "S")
    if t.startswith("THE "):
        out.append(t[4:])
    return list(dict.fromkeys(out))


def entry(inp: dict) -> str:
    term = str(inp.get("term", "")).strip()
    if not term:
        raise ToolError("請提供條目名")
    source = inp.get("source") or "all"
    part = inp.get("part") or 1
    if not isinstance(part, int) or part < 1:
        raise ToolError("part 必須是正整數")
    sources = list(SOURCES) if source == "all" else [source]
    if any(s not in SOURCES for s in sources):
        raise ToolError(f"source 只能是 all、{'、'.join(SOURCES)}")
    found = []
    for s in sources:
        data = _load(s)
        key = next((v for v in _variants(term) if v in data), None)
        if key is None:
            key = next((_by_norm(s)[_norm(v)] for v in _variants(term) if _norm(v) in _by_norm(s)), None)
        if key is None:
            continue
        text = data[key]
        chunk = text[(part - 1) * PART_CHARS: part * PART_CHARS]
        if not chunk:
            continue
        more = len(text) > part * PART_CHARS
        found.append(f"[{SOURCES[s]} · {key}{f' · 第 {part} 段' if part > 1 or more else ''}]\n{chunk}"
                     + (f"\n（還有下文：part={part + 1}）" if more else ""))
    if found:
        return "\n\n".join(found)
    near = sorted({k for s in sources for k in _load(s) if term.upper() in k})[:12]
    return ("查不到這個條目。" + (f"相近的條目：{'、'.join(near)}" if near else "請改用 dictionary_search。"))


@lru_cache(maxsize=1)
def _index():
    from ..kb.query.rag import BM25, Chunk, chunk
    chunks = []
    for s in SOURCES:
        for key, text in _load(s).items():
            for c in chunk(f"{SOURCES[s]} · {key}", text, size=1500, overlap=150):
                chunks.append(Chunk(c.doc, len(chunks) + 1, c.text))
    return BM25(chunks)


def search(inp: dict) -> str:
    query = str(inp.get("query", "")).strip()
    if not query:
        raise ToolError("請提供查詢字詞")
    hits = _index().search(query, 5)
    if not hits:
        return "沒有找到相關條目；請換用其他英文關鍵詞。"
    return "\n\n".join(f"[{c.doc}]\n{c.text}" for _, c in hits)


def make_handlers() -> dict[str, Handler]:
    if not available():
        raise FileNotFoundError(f"no dictionary data in {DIR}; run scripts/build_reference.py")
    return {"dictionary_entry": entry, "dictionary_search": search}
