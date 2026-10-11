"""Structural quality of a compiled wiki, measured without any model calls, so two
compiles (other model, other language) can be compared on more than cost:

    pages              summary / concept / entity pages written
    broken_link_rate   [[wikilinks]] whose target page does not exist
    index_coverage     share of pages that index.md links to
    frontmatter_ok     share of pages whose frontmatter has a non-empty type and description
    fact_coverage      share of anchor phrases (facts file) found in the compiled pages, i.e.
                       how much of what must be in the wiki survived compilation

A facts file lists, per source document, phrases a good wiki must contain:

    general-rules-1743-en: ["doing no harm", "doing good", "ordinances of God"]
    plain-account-of-christian-perfection: ["loving God with all our heart"]
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from ...common.corpus import normalize_en, normalize_zh

PAGE_FOLDERS = ("summaries", "concepts", "entities")
LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
CJK = re.compile(r"[㐀-鿿]")


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    try:
        data = yaml.safe_load(text[3:end]) if end > 0 else None
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _resolves(wiki: Path, target: str) -> bool:
    target = target.strip().removesuffix(".md")
    return (wiki / f"{target}.md").is_file() or (wiki / target).is_file()


def _norm(text: str, phrase: str) -> tuple[str, str]:
    if CJK.search(phrase):
        return normalize_zh(text), normalize_zh(phrase)
    return normalize_en(text), normalize_en(phrase)


def wiki_metrics(wiki: Path, facts: dict[str, list[str]] | None = None) -> dict:
    pages = {f: sorted((wiki / f).glob("*.md")) for f in PAGE_FOLDERS}
    texts = {p: p.read_text(encoding="utf-8") for ps in pages.values() for p in ps}
    all_pages = list(texts)
    links = [t for p, text in texts.items() for t in LINK.findall(text)]
    index = (wiki / "index.md").read_text(encoding="utf-8") if (wiki / "index.md").is_file() else ""
    indexed = {t.strip().removesuffix(".md") for t in LINK.findall(index)}
    in_index = sum(p.relative_to(wiki).with_suffix("").as_posix() in indexed for p in all_pages)
    fm_ok = sum(bool(str(_frontmatter(t).get("type", "") or "").strip())
                and bool(str(_frontmatter(t).get("description", "") or "").strip()) for t in texts.values())
    out = {
        "pages": {f: len(ps) for f, ps in pages.items()},
        "links": len(links),
        "broken_link_rate": (sum(not _resolves(wiki, t) for t in links) / len(links)) if links else None,
        "index_coverage": in_index / len(all_pages) if all_pages else None,
        "frontmatter_ok": fm_ok / len(all_pages) if all_pages else None,
        "compiled_chars": sum(len(t) for t in texts.values()),
    }
    if facts:
        compiled = "\n".join(texts.values())
        hits, missing = 0, []
        for doc, phrases in facts.items():
            for phrase in phrases:
                text, needle = _norm(compiled, phrase)
                if needle and needle in text:
                    hits += 1
                else:
                    missing.append(f"{doc}: {phrase}")
        total = sum(len(v) for v in facts.values())
        out["fact_coverage"] = hits / total if total else None
        out["facts_missing"] = missing
    return out


def load_facts(path: str | Path) -> dict[str, list[str]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): [str(x) for x in v] for k, v in data.items()}
