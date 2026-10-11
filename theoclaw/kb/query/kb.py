"""Find a compiled knowledge base and read its build record."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from ...common.paths import KNOWLEDGE_DIR
from .. import MANIFEST
from .tools import fingerprint


@dataclass
class KnowledgeBase:
    wiki: Path              # the wiki/ folder the tools read
    root: Path | None       # knowledge/<name>/, or None for a bare wiki folder

    @classmethod
    def open(cls, ref: str | Path) -> "KnowledgeBase":
        """``ref`` is a folder name in knowledge/, a knowledge-base folder, or a wiki/ folder."""
        for cand in (Path(ref), KNOWLEDGE_DIR / str(ref)):
            if (cand / "wiki" / "index.md").is_file():
                return cls((cand / "wiki").resolve(), cand.resolve())
            if (cand / "index.md").is_file():
                parent = cand.resolve().parent
                is_root = (parent / MANIFEST).is_file() or (parent / ".openkb").is_dir()
                return cls(cand.resolve(), parent if is_root else None)
        raise FileNotFoundError(f"no compiled knowledge base at {ref!r} (looked for wiki/index.md, "
                                f"also under {KNOWLEDGE_DIR}); build one with python -m theoclaw.kb.compile")

    @property
    def name(self) -> str:
        return (self.root or self.wiki).name

    @cached_property
    def manifest(self) -> dict:
        path = self.root / MANIFEST if self.root else None
        return json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}

    def meta(self) -> dict:
        """Recorded with every eval run, so a report can name the exact wiki and its compile cost."""
        m = self.manifest
        return {
            "kb": self.name, "wiki": str(self.wiki), "wiki_fingerprint": fingerprint(self.wiki),
            "compile": {k: m.get(k) for k in ("profile", "model", "language", "usage", "cost_usd", "calls")} if m else None,
        }


def list_knowledge_bases(directory: Path = KNOWLEDGE_DIR) -> list[KnowledgeBase]:
    if not directory.is_dir():
        return []
    return [KnowledgeBase((d / "wiki").resolve(), d.resolve())
            for d in sorted(directory.iterdir()) if (d / "wiki" / "index.md").is_file()]
