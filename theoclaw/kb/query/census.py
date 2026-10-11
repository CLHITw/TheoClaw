"""How big a compiled wiki is, in characters and in tokens of a given model, per folder.

This is the query-side cost driver: every page the agent reads is sent back to the
model as input. A wiki written in Chinese and one written in English hold the same
ideas in different numbers of tokens; the census measures that difference directly.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ...common.tokens import TokenCounter


def _page_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":  # PageIndex pages of a long document
        try:
            return "\n".join(e.get("content", "") for e in json.loads(text))
        except (ValueError, AttributeError):
            return text
    return text


def folder_of(rel: str) -> str:
    head = rel.split("/")[0]
    return "index" if head == "index.md" else head if "/" in rel else "(top level)"


def census(wiki: Path, counter: TokenCounter | None = None) -> dict:
    """{folder: {files, chars, tokens}}; tokens only when a counter is given."""
    out: dict[str, dict] = defaultdict(lambda: {"files": 0, "chars": 0, "tokens": 0 if counter else None})
    for path in sorted(wiki.rglob("*")):
        if not path.is_file() or path.suffix not in (".md", ".json") or "images" in path.parts:
            continue
        rel = path.relative_to(wiki).as_posix()
        text = _page_text(path)
        row = out[folder_of(rel)]
        row["files"] += 1
        row["chars"] += len(text)
        if counter:
            row["tokens"] += counter.count(text)
    return dict(out)
