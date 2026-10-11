"""Build the data/ files the agent's tools read.

    python scripts/build_data.py --wesley-pdf "E:/DESK/theoclaw/Methodist/03_John_Wesley_Explanatory_Notes_Upon_The_New_Testament.pdf"

Sources
- 和合本（繁體） and KJV: scrollmapper/bible_databases (public domain texts)
- Cross references: OpenBible.info (CC-BY), via the same repository
- Wesley's Explanatory Notes upon the New Testament: your local CCEL PDF
  ("Wesley's Notes on the Bible"); only the New Testament part is kept, because
  that part is Wesley's own and is a Methodist doctrinal standard.

Already-downloaded files can be passed with --chiun / --kjv / --crossrefs.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from theoclaw.common.refs import OSIS_IDS  # noqa: E402

RAW = "https://raw.githubusercontent.com/scrollmapper/bible_databases/master"
URLS = {
    "chiun": f"{RAW}/formats/json/ChiUn.json",
    "kjv": f"{RAW}/formats/json/KJV.json",
    "crossrefs": f"{RAW}/sources/extras/cross_references.txt",
}


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        print(f"downloading {url}")
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    return dest


# ---------------------------------------------------------------- Bibles

def build_bible(path: Path, version: str) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    books = data["books"]
    if len(books) != 66:
        raise ValueError(f"{path}: expected 66 books, got {len(books)}")
    out: dict[str, str] = {}
    for osis, book in zip(OSIS_IDS, books):
        for ch in book["chapters"]:
            for v in ch["verses"]:
                text = v["text"]
                if version == "cuv":
                    # The source is word-segmented with spaces; 中文 has none.
                    text = re.sub(r"\s+", "", text)
                else:
                    text = re.sub(r"\s+", " ", text).strip()
                out[f"{osis}.{ch['chapter']}.{v['verse']}"] = text
    return out


# ---------------------------------------------------------------- cross references

def build_crossrefs(path: Path, keep: int = 25) -> dict[str, list[list]]:
    refs: dict[str, list[list]] = {}
    with open(path, encoding="utf-8") as f:
        next(f)  # header
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            src, dst, votes = parts[0], parts[1], int(parts[2])
            refs.setdefault(src, []).append([dst, votes])
    for src in refs:
        refs[src] = sorted(refs[src], key=lambda x: -x[1])[:keep]
    return refs


# ---------------------------------------------------------------- Wesley NT notes

_NT_HEADERS = [  # (regex on the joined "NOTES ON ..." header, OSIS id)
    (r"ST\.? MATTHEW", "Matt"), (r"ST\.? MARK", "Mark"), (r"ST\.? LUKE", "Luke"),
    (r"GOSPEL ACCORDING TO ST\.? JOHN", "John"), (r"ACTS OF THE APOSTLES", "Acts"),
    (r"TO THE ROMANS", "Rom"), (r"FIRST EPISTLE TO THE CORINTHIANS", "1Cor"),
    (r"SECOND EPISTLE TO THE CORINTHIANS", "2Cor"), (r"GALATIANS", "Gal"),
    (r"EPHESIANS", "Eph"), (r"PHILIPPIANS", "Phil"), (r"COLOSSIANS", "Col"),
    (r"FIRST EPISTLE TO THE THESSALONIANS", "1Thess"),
    (r"SECOND EPISTLE TO THE THESSALONIANS", "2Thess"),
    (r"FIRST EPISTLE TO TIMOTHY", "1Tim"), (r"SECOND EPISTLE TO TIMOTHY", "2Tim"),
    (r"TITUS", "Titus"), (r"PHILEMON", "Phlm"), (r"HEBREWS", "Heb"), (r"JAMES", "Jas"),
    (r"FIRST EPISTLE GENERAL OF ST\.? PETER", "1Pet"),
    (r"SECOND EPISTLE GENERAL OF ST\.? PETER", "2Pet"),
    (r"FIRST EPISTLE OF ST\.? JOHN", "1John"), (r"SECOND EPISTLE OF ST\.? JOHN", "2John"),
    (r"THIRD EPISTLE OF ST\.? JOHN", "3John"), (r"JUDE", "Jude"), (r"REVELATION", "Rev"),
]
_ROMAN = re.compile(r"^(?=[IVXL]+$)(L?X{0,3})(IX|IV|V?I{0,3})$")
_VERSE_START = re.compile(r"^(\d{1,3})(?:\s*[-,]\s*(\d{1,3}))?\.\s+(.*)$")


def _roman_to_int(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50}
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        total += -v if b != " " and vals.get(b, 0) > v else v
    return total


def _book_for_header(header: str) -> str | None:
    for pattern, osis in _NT_HEADERS:
        if re.search(pattern, header):
            return osis
    return None


def parse_wesley_text(text: str) -> dict[str, str]:
    """Parse pdftotext output of the CCEL 'Wesley's Notes on the Bible' PDF.

    Book bodies start with a 'NOTES ON ...' line; standalone roman numerals set the
    chapter (they appear both as chapter titles and as running page headers); a line
    starting 'N. ' opens the note on verse N; other lines continue the open note.
    """
    lines = text.splitlines()
    notes: dict[str, list[str]] = {}
    book: str | None = None
    chapter, last_verse = 1, 0
    current: str | None = None
    in_intro = False
    prev = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if line.startswith("NOTES ON"):
            header = line
            if header.endswith(("THE", "TO", "OF", "GENERAL")) and i < len(lines):
                header += " " + lines[i].strip()
                i += 1
            book = _book_for_header(header)  # None for Old Testament books
            chapter, last_verse, current, in_intro = 1, 0, None, True
            continue
        if book is None or not line or line.isdigit():  # skip page numbers
            continue
        if _ROMAN.match(line):
            new_chapter = _roman_to_int(line)
            if new_chapter != chapter:
                chapter, last_verse, current = new_chapter, 0, None
            in_intro = False  # a chapter heading ends any introduction / outline
            continue
        if line.startswith(("Introduction to", "Commentary on")):
            current, in_intro = None, line.startswith("Introduction to")
            continue
        if in_intro:
            continue
        m = _VERSE_START.match(line)
        # A wrapped citation ("Rev. xxii,\n3. The brother ...") also starts with "N. ";
        # a real note follows a finished line and moves forward through the chapter.
        if m and int(m.group(1)) > last_verse and not prev.endswith(","):
            last_verse = int(m.group(1))
            current = f"{book}.{chapter}.{last_verse}"
            notes.setdefault(current, []).append(m.group(3))
        elif current is not None:
            notes[current].append(line)
        prev = line
    out = {}
    for key, parts in notes.items():
        joined = " ".join(parts)
        joined = re.sub(r"\s+", " ", joined).strip()
        out[key] = joined
    return out


def pdf_to_text(pdf: Path) -> str:
    if shutil.which("pdftotext"):
        return subprocess.run(["pdftotext", str(pdf), "-"], check=True,
                              capture_output=True).stdout.decode("utf-8", "replace")
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise SystemExit("需要 pdftotext（poppler）或 pip install pypdf") from e
    print("extracting with pypdf (this PDF has 4465 pages; it takes a few minutes)")
    reader = PdfReader(str(pdf))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--cache", default=str(ROOT / "data" / "_raw"))
    ap.add_argument("--chiun")
    ap.add_argument("--kjv")
    ap.add_argument("--crossrefs")
    ap.add_argument("--wesley-pdf", help="local PDF of Wesley's Notes (CCEL)")
    ap.add_argument("--wesley-txt", help="pdftotext output of the same PDF")
    args = ap.parse_args(argv)

    out, cache = Path(args.out), Path(args.cache)
    out.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    chiun = Path(args.chiun) if args.chiun else fetch(URLS["chiun"], cache / "ChiUn.json")
    kjv = Path(args.kjv) if args.kjv else fetch(URLS["kjv"], cache / "KJV.json")
    xref = Path(args.crossrefs) if args.crossrefs else fetch(URLS["crossrefs"], cache / "cross_references.txt")

    def dump(name, obj):
        (out / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {out / name} ({len(obj)} entries)")

    dump("cuv.json", build_bible(chiun, "cuv"))
    dump("kjv.json", build_bible(kjv, "kjv"))
    dump("crossrefs.json", build_crossrefs(xref))

    if args.wesley_txt:
        text = Path(args.wesley_txt).read_text(encoding="utf-8")
    elif args.wesley_pdf:
        text = pdf_to_text(Path(args.wesley_pdf))
    else:
        print("no --wesley-pdf given; skipping wesley_nt.json")
        return
    cuv_keys = set(json.loads((out / "cuv.json").read_text(encoding="utf-8")))
    notes = {k: v for k, v in parse_wesley_text(text).items() if k in cuv_keys}
    dump("wesley_nt.json", notes)


if __name__ == "__main__":
    main()
