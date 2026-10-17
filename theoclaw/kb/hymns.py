"""Hymn books as search passages, split by program instead of compiled.

A hymn book is hundreds of short numbered pieces with no prose to summarise. Compiling the
1780 Collection (a scanned PDF with no outline) with PageIndex spent 961 model calls guessing
a table of contents. Here the hymns are cut by program (no model calls, no cost) and
written to ``wiki/hymns/<name>.json``; ``rag_search`` finds a hymn by its words or theme,
one hymn per passage, labelled with its number.

Two sources, best first:

- ``build-ccel``: the CCEL e-text of the Collection (John Harris's public-domain edition of
  the 1876 hymn book; its first 539 hymns are substantially Wesley's 1780 text), one page
  per hymn, with the contents page giving each hymn's part and section. Clean text.
- ``build``: an OCR'd PDF, cut at the "HYMN n." headings. Good enough for search (about 95%
  dictionary words) but the large first letter of each hymn is usually lost ("ET
  everlasting" for "LET"); lines broken at punctuation are joined back.

    python -m theoclaw.kb.hymns build-ccel E:/DESK/theoclaw/Methodist/ccel_wesley_hymns_1876 --kb methodist.en.deepseek-flash
    python -m theoclaw.kb.hymns build E:/DESK/theoclaw/Methodist/Global_base/05_...pdf --kb methodist.en.deepseek-flash
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

HYMN_DIR = "hymns"   # under the wiki folder; rag.index_wiki_sources reads it
NAME = "wesley-hymns-1780"      # from the OCR'd PDF
CCEL_NAME = "wesley-hymns"      # from the CCEL e-text; replaces the OCR file when built

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


# The contents page names Part V only through its sections ("For the Society Meeting",
# "Giving Thanks", ...); Part III's sections name themselves.
_UNNAMED_PARTS = {"PART V.": "For the Society"}


def ccel_sections(contents_html: str) -> list[tuple[int, str]]:
    """(first hymn number, "part · section") from the e-text's contents page, in order."""
    out, part, group = [], "", ""
    body = contents_html[contents_html.find('NAME="contents"'):]
    for para in re.split(r"(?i)<P>", body):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", para))).strip()
        m = re.search(r'(?i)HREF="#h(\d+)"\s*>([^<]+)</A>', para)
        if m:
            if text.startswith("SECTION"):  # a new section that is itself a heading: leave the last group
                group = ""
            title = re.sub(r"\s+", " ", html.unescape(m.group(2))).strip()
            out.append((int(m.group(1)), " · ".join(x for x in (part, group, title) if x)))
        elif text.startswith("SECTION"):  # a section heading with subsections under it
            group = re.sub(r"^SECTION [IVX]+\.\s*", "", text).rstrip(".").title()
        elif re.match(r"PART [IVX]+\.|SUPPLEMENT", text):
            part, group = re.sub(r"^PART [IVX]+\.\s*(CONTAINING\s+)?", "", text).rstrip(".").title(), ""
            part = part or _UNNAMED_PARTS.get(text, "")
        if text.upper().startswith("INDEX"):
            break
    return sorted(out)


def ccel_hymn(page_html: str) -> str:
    """One hymn page as plain text: the metre and any heading lines, then the verses."""
    body = page_html[page_html.upper().find("<BODY"):]
    body = re.sub(r"(?i)<BR\s*/?>", "\n", body)
    body = re.sub(r"(?i)</?(P|H\d)[^>]*>", "\n", body)
    text = html.unescape(re.sub(r"<[^>]+>", "", body))
    return "\n".join(ln.strip() for ln in text.split("\n") if ln.strip())


def split_ccel(folder: str | Path) -> list[dict]:
    folder = Path(folder)
    sections = ccel_sections((folder / "hymn.html").read_text(encoding="cp1252", errors="replace"))
    hymns = []
    for f in sorted(folder.glob("jwg[0-9][0-9]_jwg*.html")):
        number = int(re.search(r"jwg(\d+)\.html$", f.name).group(1))
        section = next((t for start, t in reversed(sections) if start <= number), "")
        text = ccel_hymn(f.read_text(encoding="cp1252", errors="replace"))
        if text:  # CCEL's pages for hymns 501 and 829 are empty
            hymns.append({"number": number, "section": section, "text": text})
    return sorted(hymns, key=lambda h: h["number"])


def _wiki(kb: str | Path) -> Path:
    root = Path(kb)
    if not root.is_dir():
        root = Path(__file__).resolve().parents[2] / "knowledge" / str(kb)
    if not (root / "wiki").is_dir():
        raise SystemExit(f"no wiki folder in {root}")
    return root / "wiki"


def _write(wiki: Path, name: str, hymns: list[dict]) -> dict:
    out = wiki / HYMN_DIR / f"{name}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(hymns, ensure_ascii=False, indent=1), encoding="utf-8")
    nums = [h["number"] for h in hymns]
    missing = sorted(set(range(1, max(nums) + 1)) - set(nums)) if nums else []
    return {"file": str(out), "hymns": len(hymns), "highest": max(nums, default=0), "missing": missing,
            "chars": sum(len(h["text"]) for h in hymns)}


def build(pdf: str | Path, kb: str | Path, name: str = NAME) -> dict:
    import pymupdf

    with pymupdf.open(str(pdf)) as d:
        pages = [p.get_text() for p in d]
    return _write(_wiki(kb), name, split_hymns(pages))


def build_ccel(folder: str | Path, kb: str | Path, name: str = CCEL_NAME) -> dict:
    """The clean e-text replaces the OCR version, so the same hymn is not found twice."""
    wiki = _wiki(kb)
    r = _write(wiki, name, split_ccel(folder))
    ocr = wiki / HYMN_DIR / f"{NAME}.json"
    if name != NAME and ocr.exists():
        ocr.unlink()
        r["replaced"] = str(ocr)
    return r


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="theoclaw.kb.hymns", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="split a hymn-book PDF into hymns for rag_search")
    b.add_argument("pdf")
    b.add_argument("--kb", required=True, help="knowledge base (a folder in knowledge/ or a path)")
    b.add_argument("--name", default=NAME)
    c = sub.add_parser("build-ccel", help="the CCEL e-text, downloaded one page per hymn (clean; preferred)")
    c.add_argument("folder", help="folder with hymn.html and jwgNN_jwgNNNN.html")
    c.add_argument("--kb", required=True)
    c.add_argument("--name", default=CCEL_NAME)
    a = ap.parse_args(argv)
    r = build(a.pdf, a.kb, a.name) if a.cmd == "build" else build_ccel(a.folder, a.kb, a.name)
    print(f"{r['hymns']} hymns (highest number {r['highest']}, {r['chars']:,} characters) → {r['file']}")
    if r["missing"]:
        print(f"numbers not found ({len(r['missing'])}): {r['missing'][:30]}"
              + ("; from a PDF these are usually OCR-garbled headings, inside the hymn before" if a.cmd == "build"
                 else "; their e-text pages are empty"))


if __name__ == "__main__":
    main()
