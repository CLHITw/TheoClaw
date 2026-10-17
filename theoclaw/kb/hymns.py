"""Hymn books as search passages, split by program instead of compiled.

A hymn book is hundreds of short numbered pieces with no prose to summarise, and the
scans available are image PDFs with an OCR text layer and no outline. Compiling one with
PageIndex spent 961 model calls guessing a table of contents for the 1780 Collection. Here
the OCR text is cut at the "HYMN n." headings instead (no model calls, no cost), lightly
repaired, and written to ``wiki/hymns/<name>.json``; ``rag_search`` then finds a hymn by
its words or theme, one hymn per passage, labelled with its number.

The OCR is good enough for search (about 95% of words are dictionary words) but not
perfect: the large first letter of each hymn is usually lost ("ET everlasting" for "LET"),
and lines broken at punctuation are joined back here. The search tool says so, so the
agent quotes hymns briefly and by number.

    python -m theoclaw.kb.hymns build E:/DESK/theoclaw/Methodist/Global_base/05_...pdf --kb methodist.en.deepseek-flash
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HYMN_DIR = "hymns"   # under the wiki folder; rag.index_wiki_sources reads it
NAME = "wesley-hymns-1780"

_HEADING = re.compile(r"(?<![Ss]ee )\bHYMN\s+([0-9IlOo]{1,4})\s*\.")
_PUNCT_ONLY = re.compile(r"^[;:!?,.\-–—'\"’”)\]]+$")
_PAGE_NO = re.compile(r"^[\W\dOoIlJ]{1,6}$")       # "9", "*3o4", "1 4 ]", "JO"
_DIGITS = str.maketrans("OoIl", "0011")


def clean_page(text: str) -> tuple[str, str]:
    """(running header, body) of one page: page numbers dropped, lines broken at
    punctuation or mid-line (a line starting in lower case) joined back."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    header = ""
    while lines and _PAGE_NO.match(lines[0]):
        lines.pop(0)
    if lines and not lines[0][0].isdigit() and not _HEADING.search(lines[0]) and re.search(r"[a-z]{3}", lines[0]):
        header = lines.pop(0)
        while lines and lines[0][0].islower() and len(header) < 60:
            header += " " + lines.pop(0)
    while lines and _PAGE_NO.match(lines[0]):
        lines.pop(0)
    out: list[str] = []
    for ln in lines:
        if out and (_PUNCT_ONLY.match(ln) or ln[0] in ";:!?,." or ln[0].islower()):
            out[-1] += ("" if ln[0] in ";:!?,.'\"’”)]" else " ") + ln
        else:
            out.append(ln)
    return header.rstrip(" ."), "\n".join(out)


def split_hymns(pages: list[str]) -> list[dict]:
    """Hymns in order from the pages' text. A heading counts only if its number follows
    the previous one closely, so cross references and OCR noise do not start a hymn."""
    hymns: list[dict] = []
    last = 0
    for page_no, raw in enumerate(pages, 1):
        if raw.lstrip().upper().startswith("INDEX"):
            break
        header, body = clean_page(raw)
        pos = 0
        for m in _HEADING.finditer(body):
            num = m.group(1).translate(_DIGITS)
            if not num.isdigit() or not last < int(num) <= last + 20:
                continue
            if hymns:
                hymns[-1]["text"] += "\n" + body[pos:m.start()]
            hymns.append({"number": int(num), "page": page_no, "section": header, "text": ""})
            last, pos = int(num), m.end()
        if hymns:
            hymns[-1]["text"] += ("\n" if pos == 0 else "") + body[pos:]
    section = ""
    for h in hymns:  # a hymn starting on a page whose header the OCR lost takes the previous section
        section = h["section"] = h["section"] or section
        h["text"] = re.sub(r"\n{2,}", "\n", h["text"]).strip()
    return hymns


def build(pdf: str | Path, kb: str | Path, name: str = NAME) -> dict:
    import pymupdf

    root = Path(kb)
    if not root.is_dir():
        root = Path(__file__).resolve().parents[2] / "knowledge" / str(kb)
    wiki = root / "wiki"
    if not wiki.is_dir():
        raise SystemExit(f"no wiki folder in {root}")
    with pymupdf.open(str(pdf)) as d:
        pages = [p.get_text() for p in d]
    hymns = split_hymns(pages)
    out = wiki / HYMN_DIR / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(hymns, ensure_ascii=False, indent=1), encoding="utf-8")
    nums = [h["number"] for h in hymns]
    missing = sorted(set(range(1, max(nums) + 1)) - set(nums)) if nums else []
    return {"file": str(out), "hymns": len(hymns), "highest": max(nums, default=0), "missing": missing,
            "chars": sum(len(h["text"]) for h in hymns)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="theoclaw.kb.hymns", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="split a hymn-book PDF into hymns for rag_search")
    b.add_argument("pdf")
    b.add_argument("--kb", required=True, help="knowledge base (a folder in knowledge/ or a path)")
    b.add_argument("--name", default=NAME)
    a = ap.parse_args(argv)
    r = build(a.pdf, a.kb, a.name)
    print(f"{r['hymns']} hymns (highest number {r['highest']}, {r['chars']:,} characters) → {r['file']}")
    if r["missing"]:
        print(f"numbers not found ({len(r['missing'])}), usually an OCR-garbled heading; "
              f"those hymns are inside the one before: {r['missing'][:30]}")


if __name__ == "__main__":
    main()
