"""Turn a profile's source list into the input files OpenKB compiles.

Every source is a file in the Methodist folder (source_dir) or one of its subfolders. A source can be
narrowed to some pages of a PDF, turned into plain text, or converted to 繁體:

    - file: 02_John_Wesley_Plain_Account_of_Christian_Perfection.pdf
    - file: 00_聖經_新標點和合本_繁體_全文_公版.pdf
      outline: 羅馬書            # the pages under this PDF bookmark (see: kb.compile outline <file>)
      name: cuv-romans.pdf
    - file: 06_The_General_Rules_Bilingual_Wesley_1743.md
      s2t: true                 # convert Simplified characters to 繁體
    - wesley_nt_notes: true     # Wesley's NT notes, parsed from the 03 PDF into data/wesley_nt.json
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from ...common.paths import DATA_DIR
from ...common.refs import EN_NAME, OSIS_IDS
from ...common.zh import to_traditional

MAX_FILE_CHARS = 80_000  # under the kb_read_file cap (100k), so every page of a note file stays readable
TEXT_SUFFIXES = (".md", ".txt", ".markdown")


@dataclass
class PreparedInput:
    path: str             # the file in inputs/ that OpenKB compiles
    origin: str           # where it came from (a file in the Methodist folder)
    kind: str             # pdf | md
    pages: int | None     # PDF pages
    sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip()


def find_source(source_dir: Path, name: str) -> Path:
    """The file called ``name`` in source_dir or any folder under it (Global_base/, HK/, ...);
    tolerant of full-width punctuation and spacing. ``name`` may include the folder (HK/x.md)
    to pick one of two files with the same name."""
    exact = source_dir / name
    if exact.is_file():
        return exact
    want = _norm_name(Path(name).name)
    matches = [p for p in sorted(source_dir.rglob("*")) if p.is_file() and _norm_name(p.name) == want]
    if len(matches) > 1:
        found = ", ".join(p.relative_to(source_dir).as_posix() for p in matches)
        raise FileNotFoundError(f"{name!r} matches several files in {source_dir}: {found}; write the folder too")
    if not matches:
        raise FileNotFoundError(f"{name!r} is not in {source_dir} or its subfolders")
    return matches[0]


# ---------------------------------------------------------------- PDFs

def _reader(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise SystemExit("pip install pypdf (needed to cut or read PDFs)") from e
    return PdfReader(str(path))


def pdf_outline(path: Path) -> tuple[list[tuple[int, str, int | None]], int]:
    """([(level, title, first page, 1-based)], total pages) from the PDF's bookmarks."""
    reader = _reader(path)
    out: list[tuple[int, str, int | None]] = []

    def walk(items, level):
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                page = None
            out.append((level, str(getattr(item, "title", item)), page))

    walk(reader.outline, 0)
    return out, len(reader.pages)


def outline_pages(path: Path, title: str) -> list[int]:
    """Pages under the first bookmark whose title contains ``title``, up to the next
    bookmark at the same or a higher level."""
    entries, total = pdf_outline(path)
    want = _norm_name(title)
    for i, (level, name, start) in enumerate(entries):
        if start is None or want not in _norm_name(name):
            continue
        end = total
        for lvl, _, page in entries[i + 1:]:
            if page is not None and lvl <= level and page > start:
                end = page - 1
                break
        return list(range(start, end + 1))
    raise ValueError(f"no bookmark containing {title!r} in {path.name}; list them with: "
                     f"python -m theoclaw.kb.compile outline \"{path.name}\"")


def parse_pages(spec: str | int) -> list[int]:
    pages: list[int] = []
    for part in str(spec).replace(" ", "").split(","):
        if "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
            if b < a:
                raise ValueError(f"bad page range {part!r}")
            pages.extend(range(a, b + 1))
        elif part:
            pages.append(int(part))
    return pages


def slice_pdf(src: Path, pages: list[int], dst: Path) -> None:
    from pypdf import PdfWriter
    reader, writer = _reader(src), PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    with open(dst, "wb") as f:
        writer.write(f)


def pdf_text(path: Path) -> str:
    """Plain text with a "## Page N" heading per page, so answers can cite pages."""
    reader = _reader(path)
    return "\n\n".join(f"## Page {i}\n\n{(page.extract_text() or '').strip()}"
                       for i, page in enumerate(reader.pages, 1))


def input_text(path: Path) -> str:
    """The text of a prepared input, for counting characters and tokens."""
    return pdf_text(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- Wesley's NT notes

def write_nt_notes(folder: Path) -> list[Path]:
    """One Markdown file per NT book (long books split at chapter boundaries), a
    "## John 3:16" heading per verse, from data/wesley_nt.json, so the kb arm and the
    exact-lookup arm read the same notes."""
    notes = json.loads((DATA_DIR / "wesley_nt.json").read_text(encoding="utf-8"))
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for i, book in enumerate(OSIS_IDS[39:], start=1):
        name = EN_NAME[book]
        chapters: dict[int, list[str]] = {}
        for k in sorted((k for k in notes if k.split(".")[0] == book),
                        key=lambda k: (int(k.split(".")[1]), int(k.split(".")[2]))):
            _, ch, v = k.split(".")
            chapters.setdefault(int(ch), []).append(f"## {name} {ch}:{v}\n\n{notes[k]}\n")
        parts: list[list[int]] = [[]]
        size = 0
        for ch, entries in chapters.items():
            ch_size = sum(len(e) for e in entries)
            if parts[-1] and size + ch_size > MAX_FILE_CHARS:
                parts.append([])
                size = 0
            parts[-1].append(ch)
            size += ch_size
        slug = name.lower().replace(" ", "-")
        for chs in (c for c in parts if c):
            split = len(parts) > 1
            title = (f"# John Wesley, Explanatory Notes upon the New Testament: {name}"
                     + (f" {chs[0]}-{chs[-1]}" if split else "") + "\n\n")
            path = folder / (f"wesley-nt-{i:02d}-{slug}" + (f"-{chs[0]}-{chs[-1]}" if split else "") + ".md")
            path.write_text(title + "\n".join(e for ch in chs for e in chapters[ch]), encoding="utf-8")
            written.append(path)
    return written


# ---------------------------------------------------------------- one source

def prepare_source(spec: dict, source_dir: Path, out_dir: Path) -> list[PreparedInput]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if spec.get("wesley_nt_notes"):
        return [PreparedInput(str(p), "03_John_Wesley_Explanatory_Notes_Upon_The_New_Testament.pdf "
                                      "(NT notes, parsed into data/wesley_nt.json)", "md", None, _sha(p))
                for p in write_nt_notes(out_dir)]
    if "file" not in spec:
        raise ValueError(f"a source needs file: or wesley_nt_notes: ({spec})")
    src = find_source(source_dir, spec["file"])
    is_pdf = src.suffix.lower() == ".pdf"
    pages = None
    if is_pdf and ("pages" in spec or "outline" in spec):
        pages = parse_pages(spec["pages"]) if "pages" in spec else outline_pages(src, spec["outline"])
    dst = out_dir / spec.get("name", src.name)

    if is_pdf and spec.get("to_text"):
        tmp = src
        if pages:
            tmp = out_dir / f".{dst.stem}.slice.pdf"
            slice_pdf(src, pages, tmp)
        text = pdf_text(tmp)
        if tmp is not src:
            tmp.unlink()
        dst = dst.with_suffix(".md")
        dst.write_text(to_traditional(text) if spec.get("s2t") else text, encoding="utf-8")
        kind, n_pages = "md", len(pages) if pages else None
    elif is_pdf:
        if pages:
            slice_pdf(src, pages, dst)
        else:
            shutil.copy(src, dst)
        kind, n_pages = "pdf", len(pages) if pages else len(_reader(dst).pages)
    elif src.suffix.lower() in TEXT_SUFFIXES:
        text = src.read_text(encoding="utf-8")
        dst.write_text(to_traditional(text) if spec.get("s2t") else text, encoding="utf-8")
        kind, n_pages = "md", None
    else:
        shutil.copy(src, dst)  # other formats OpenKB converts itself (docx, pptx, html, ...)
        kind, n_pages = src.suffix.lower().lstrip("."), None
    origin = src.relative_to(source_dir).as_posix() + (f" (pages {pages[0]}-{pages[-1]})" if pages else "")
    return [PreparedInput(str(dst), origin, kind, n_pages, _sha(dst))]
