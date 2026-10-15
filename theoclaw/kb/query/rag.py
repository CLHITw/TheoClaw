"""A plain RAG baseline over the same source text an OpenKB wiki was compiled from.

The wiki's converted sources (``wiki/sources/*.md``) are cut into overlapping chunks and
searched with BM25 (lexical, no embeddings, no model calls). The agent gets one tool,
``rag_search``, and writes its own queries; nothing is compiled ahead of time. Comparing
this tool group ("rag") with the wiki tools ("kb") on the same tasks, model and source
text measures what the compile adds.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ...common.tooling import Handler, ToolError

CHUNK_CHARS = 1200
OVERLAP = 200
TOP_K = 5
MAX_K = 8

TOOL_DEFS: list[dict] = [
    {
        "name": "rag_search",
        "description": (
            "在衛理宗文獻的原文中做關鍵詞檢索（BM25），回傳最相關的幾個段落。原文是英文，"
            "請用英文關鍵詞查詢，例如 \"perfect love sin involuntary transgression\"。可以多次查詢。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "英文關鍵詞或短句。"},
                "k": {"type": "integer", "description": f"回傳段落數，預設 {TOP_K}，最多 {MAX_K}。"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]

SYSTEM_ADDENDUM = """
原文檢索（rag_search）的使用方式：
1. 文獻原文是英文。用英文關鍵詞查詢；一次查不到就換說法或同義詞再查。
2. 每個段落標有文件名稱與段落編號。引用衛斯理的原話時，只能用檢索回傳的段落，並註明文件名稱與段落編號。
"""

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the a an and or of to in on at by for is are was were be been it its this that "
                  "with as from not but he his him they them their we our you your i my me".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


@dataclass
class Chunk:
    doc: str
    index: int
    text: str


def chunk(doc: str, text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[Chunk]:
    """Overlapping windows that end on a paragraph or sentence break where one is near."""
    out, start, n = [], 0, len(text)
    while start < n:
        end = min(n, start + size)
        if end < n:
            cut = max(text.rfind("\n\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
            if cut > start:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            out.append(Chunk(doc, len(out) + 1, piece))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tf = [Counter(_tokens(c.text)) for c in chunks]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter(w for t in self.tf for w in t)
        n = len(chunks)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def search(self, query: str, k: int = TOP_K) -> list[tuple[float, Chunk]]:
        q = _tokens(query)
        scored = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scored.append((s, self.chunks[i]))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]


def index_wiki_sources(wiki_dir: Path | str) -> BM25:
    root = Path(wiki_dir) / "sources"
    chunks: list[Chunk] = []
    for p in sorted(root.glob("*.md")):
        chunks += chunk(p.stem, p.read_text(encoding="utf-8"))
    if not chunks:
        raise FileNotFoundError(f"no source text in {root}")
    return BM25(chunks)


def search(inp: dict, index: BM25) -> str:
    query = str(inp.get("query", "")).strip()
    if not query:
        raise ToolError("請提供查詢字詞")
    k = inp.get("k") or TOP_K
    if not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise ToolError(f"k 必須是 1 到 {MAX_K} 的整數")
    hits = index.search(query, k)
    if not hits:
        return "沒有找到相關段落；請換用其他英文關鍵詞。"
    return "\n\n".join(f"[{c.doc} · 段落 {c.index}]\n{c.text}" for _, c in hits)


def make_handlers(wiki_dir: Path | str) -> dict[str, Handler]:
    index = index_wiki_sources(wiki_dir)
    return {"rag_search": lambda inp: search(inp, index)}
