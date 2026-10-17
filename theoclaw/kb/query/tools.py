"""Knowledge-base tools that read an OpenKB wiki (https://github.com/VectifyAI/OpenKB).

OpenKB compiles documents ahead of time into a wiki: an index, LLM-written summary,
concept and entity pages, and the converted source text (``sources/``; long PDFs as
page-numbered JSON built with PageIndex). At question time an agent navigates that
wiki with two tools. These are ports of OpenKB's query tools (``read_file`` and
``get_page_content``, Apache-2.0) so the same wiki can be used inside this harness's
own loop, with the model, tasks and graders unchanged.

The query model is whatever model runs the agent; it does not have to be the model
that compiled the wiki (see theoclaw.kb.compile), which is where the cost saving is.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ...common.tooling import Handler, ToolError

MAX_CHARS = 100_000  # a whole long source file would flood the context window

TOOL_DEFS: list[dict] = [
    {
        "name": "kb_read_file",
        "description": (
            "讀取衛理宗文獻知識庫（OpenKB wiki）中的一個檔案。路徑相對於 wiki 根目錄，"
            "例如 index.md、summaries/plain-account.md、concepts/christian-perfection.md、"
            "sources/general-rules.md。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相對於 wiki 根目錄的檔案路徑。"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kb_get_page_content",
        "description": (
            "讀取長文件（doc_type: pageindex）指定頁碼的原文。只用於長文件；短文件請用 kb_read_file。"
            "請指定精確的頁碼範圍，不要一次讀整份文件。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_name": {"type": "string", "description": "文件名稱，不含副檔名，例如 sermons-on-several-occasions。"},
                "pages": {"type": "string", "description": "頁碼，例如 3-5,7,10-12。"},
            },
            "required": ["doc_name", "pages"],
            "additionalProperties": False,
        },
    },
]

# Adapted from OpenKB's query instructions; rule 5 is ours: compiled pages are a
# model's paraphrase, so quotations must come from the converted sources.
SYSTEM_ADDENDUM = """
知識庫（OpenKB wiki）的使用方式：
1. 先用 kb_read_file 讀 index.md，查看有哪些文件、概念與人物，以及每一項的簡介。每份文件標有 (short) 或 (pageindex)。
2. 讀相關的摘要頁（summaries/）掌握文件大意。摘要可能省略細節，需要原文時，依摘要開頭 full_text 欄位找到原文。
3. 讀概念頁（concepts/）取得跨文件的綜合整理；問到人物、組織、地點時，先讀 entities/ 底下對應的頁面。
4. 需要原文時：短文件用 kb_read_file 讀 full_text 指向的 .md；長文件用 kb_get_page_content 指定頁碼範圍。
5. 摘要頁、概念頁和人物頁是模型整理出來的，不是衛斯理的原話。引用衛斯理的原話時，必須出自 sources/ 底下的原文，並註明文件名稱與頁碼。
6. 對使用者不要說「知識庫」「wiki」「檢索」「摘要頁」這類工具用語；說「衛斯理的著作」「手邊的資料」即可。查不到時就說手邊的資料沒有談到。
"""


def _resolve(root: Path, rel: str) -> Path:
    full = (root / rel).resolve()
    if not full.is_relative_to(root):
        raise ToolError("路徑超出知識庫範圍")
    return full


def _parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            if hi < lo or hi - lo > 50:
                raise ToolError("頁碼範圍不合理（一次最多 50 頁）")
            pages.extend(range(lo, hi + 1))
        else:
            pages.append(int(part))
    if not pages:
        raise ToolError("請指定頁碼")
    return pages


def read_file(inp: dict, root: Path) -> str:
    path = _resolve(root, str(inp.get("path", "")).lstrip("/\\"))
    if not path.is_file():
        raise ToolError(f"找不到檔案：{inp.get('path')}")
    text = path.read_text(encoding="utf-8")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n\n（檔案共 {len(text)} 字元，已截斷；長文件請改用 kb_get_page_content。）"
    return text


def get_page_content(inp: dict, root: Path) -> str:
    doc = str(inp.get("doc_name", ""))
    target = _resolve(root, f"sources/{doc}.json")
    if not target.is_file():
        raise ToolError(f"找不到長文件：sources/{doc}.json")
    try:
        requested = set(_parse_pages(str(inp.get("pages", ""))))
    except ValueError as e:
        raise ToolError("頁碼格式錯誤") from e
    data = json.loads(target.read_text(encoding="utf-8"))
    matches = [e for e in data if e.get("page") in requested]
    if not matches:
        raise ToolError(f"{doc} 沒有第 {inp.get('pages')} 頁的內容")
    return "\n\n".join(f"[Page {e['page']}]\n{e.get('content', '')}" for e in matches)


def make_handlers(wiki_dir: Path | str) -> dict[str, Handler]:
    root = Path(wiki_dir).resolve()
    if not (root / "index.md").is_file():
        raise FileNotFoundError(f"{root} is not an OpenKB wiki (no index.md); pass the wiki/ folder")
    return {
        "kb_read_file": lambda inp: read_file(inp, root),
        "kb_get_page_content": lambda inp: get_page_content(inp, root),
    }


def system_addendum(wiki_dir: Path | str) -> str:
    """Our usage rules plus the wiki's own AGENTS.md, as OpenKB's query agent does."""
    schema = Path(wiki_dir) / "AGENTS.md"
    text = SYSTEM_ADDENDUM
    if schema.is_file():
        text += "\n知識庫的結構說明（wiki/AGENTS.md）：\n" + schema.read_text(encoding="utf-8")
    return text


def fingerprint(wiki_dir: Path | str) -> str:
    """A hash of every file's path and size, so a report says which build of the wiki it used."""
    root = Path(wiki_dir).resolve()
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(f"{p.relative_to(root).as_posix()}:{p.stat().st_size}\n".encode())
    return h.hexdigest()[:12]


def source_texts(wiki_dir: Path | str) -> list[str]:
    """Converted original text of every ingested document (not the compiled pages)."""
    root = Path(wiki_dir) / "sources"
    texts = []
    for p in sorted(root.glob("*.md")):
        texts.append(p.read_text(encoding="utf-8"))
    for p in sorted(root.glob("*.json")):
        texts.append("\n".join(e.get("content", "") for e in json.loads(p.read_text(encoding="utf-8"))))
    return texts
