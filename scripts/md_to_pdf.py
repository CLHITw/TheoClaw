"""Typeset a Markdown text as a text-layer PDF with a printed table of contents, bookmarks
and a page number on every page, so OpenKB compiles it page by page (PageIndex reads the
contents page to build its tree) instead of as one long document.

    python scripts/md_to_pdf.py <in.md> <out.pdf> [--title "..."] [--levels 2]

For texts that exist only as plain text (Gutenberg, Wikisource, archive.org). Headings
(#, ##, ###) up to --levels deep go into the contents and the bookmarks; each # or ##
heading starts a new page. Page numbers printed on the pages are the PDF page numbers.
"""

from __future__ import annotations

import argparse
import re
import textwrap
from pathlib import Path

import pymupdf

PAGE_W, PAGE_H = 595, 842          # A4
MARGIN_X, TOP, BOTTOM = 56, 60, 60
SIZE, LEAD = 10, 13.2
WRAP = 98                          # characters per line at this size (Arial)
LINES = int((PAGE_H - TOP - BOTTOM) / LEAD)
FONT_FILES = ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_HEAD = re.compile(r"^(#{1,6})\s+(.*)$")


def _font() -> tuple[str, str | None]:
    for f in FONT_FILES:
        if Path(f).is_file():
            return "body", f
    return "helv", None


def layout(md: str, levels: int) -> tuple[list[list[tuple[str, bool]]], list[tuple[int, str, int]]]:
    """Pages of (line, is_heading) and the headings as (level, title, page index from 0)."""
    pages: list[list[tuple[str, bool]]] = [[]]
    heads: list[tuple[int, str, int]] = []

    def emit(line: str, bold: bool = False):
        if len(pages[-1]) >= LINES:
            pages.append([])
        pages[-1].append((line, bold))

    para: list[str] = []

    def flush():
        if para:
            for ln in textwrap.wrap(" ".join(para), WRAP) or [""]:
                emit(ln)
            emit("")
            para.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        m = _HEAD.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip().strip("#").strip()
            if level <= 2 and any(t for t, _ in pages[-1]):
                pages.append([])
            elif len(pages[-1]) > LINES - 4:
                pages.append([])
            if level <= levels:
                heads.append((level, title, len(pages) - 1))
            for ln in textwrap.wrap(title, WRAP - 10) or [title]:
                emit(ln, True)
            emit("")
        elif not line.strip():
            flush()
        elif line.lstrip().startswith(">"):
            flush()
            for ln in textwrap.wrap(line.lstrip("> ").strip(), WRAP) or [""]:
                emit(ln)
        else:
            para.append(line.strip())
    flush()
    return [p for p in pages if p], heads


def build(md_path: Path, out: Path, title: str | None = None, levels: int = 2) -> dict:
    md = md_path.read_text(encoding="utf-8")
    title = title or next((m.group(2) for m in map(_HEAD.match, md.splitlines()) if m), md_path.stem)
    body, heads = layout(md, levels)
    toc_lines = [(f"{'    ' * (lvl - 1)}{t[:80]}", p) for lvl, t, p in heads]
    n_toc = max(1, -(-(len(toc_lines) + 3) // LINES))
    doc = pymupdf.open()
    fname, ffile = _font()

    def new_page(num: int):
        pg = doc.new_page(width=PAGE_W, height=PAGE_H)
        if ffile:
            pg.insert_font(fontname=fname, fontfile=ffile)
        pg.insert_text((PAGE_W / 2 - 10, PAGE_H - 30), str(num), fontname=fname, fontsize=9)
        return pg

    rows = [("CONTENTS", None), ("", None)] + [(t, p + n_toc + 1) for t, p in toc_lines]
    for i in range(n_toc):
        pg = new_page(i + 1)
        if i == 0:
            pg.insert_text((MARGIN_X, TOP - 20), title[:90], fontname=fname, fontsize=12)
        for j, (text, num) in enumerate(rows[i * LINES:(i + 1) * LINES]):
            y = TOP + j * LEAD
            pg.insert_text((MARGIN_X, y), text, fontname=fname, fontsize=SIZE)
            if num:
                pg.insert_text((PAGE_W - MARGIN_X - 24, y), str(num), fontname=fname, fontsize=SIZE)
    for k, lines in enumerate(body):
        pg = new_page(n_toc + k + 1)
        for j, (text, bold) in enumerate(lines):
            pg.insert_text((MARGIN_X, TOP + j * LEAD), text, fontname=fname, fontsize=SIZE + (1 if bold else 0))
    doc.set_toc([[lvl, t[:120], p + n_toc + 1] for lvl, t, p in heads])
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out, garbage=3, deflate=True)
    return {"pages": len(doc), "contents_pages": n_toc, "headings": len(heads), "chars": len(md)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("md")
    ap.add_argument("pdf")
    ap.add_argument("--title")
    ap.add_argument("--levels", type=int, default=2, help="heading depth in the contents (default 2)")
    a = ap.parse_args(argv)
    r = build(Path(a.md), Path(a.pdf), a.title, a.levels)
    print(f"{a.pdf}: {r['pages']} pages ({r['contents_pages']} contents), {r['headings']} headings, {r['chars']:,} characters")


if __name__ == "__main__":
    main()
