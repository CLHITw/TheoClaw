"""Build data/web.json, the World English Bible, from eBible.org's verse-per-line text.

    python scripts/build_web.py --vpl <eng-web_vpl.txt> --psalms-usfm <20-PSAeng-web.usfm>
    (inside https://ebible.org/Scriptures/eng-web_vpl.zip and eng-web_usfm.zip)

The World English Bible is in the public domain ("World English Bible" is a trademark of
eBible.org, so it is named as such). Only the 66 books are kept, keyed like data/kjv.json
("John.3.16"); the deuterocanonical books in the same file are left out.

The verse-per-line text puts a psalm's heading ("A Psalm by David.") at the start of verse 1,
where the KJV and the 和合本 do not; the USFM edition marks the headings (the d marker), so they are
taken off verse 1 again.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BOOKS = dict(zip(
    "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SOL ISA JER LAM EZE DAN "
    "HOS JOE AMO OBA JON MIC NAH HAB ZEP HAG ZEC MAL MAT MAR LUK JOH ACT ROM 1CO 2CO GAL EPH PHI COL 1TH 2TH "
    "1TI 2TI TIT PHM HEB JAM 1PE 2PE 1JO 2JO 3JO JUD REV".split(),
    "Gen Exod Lev Num Deut Josh Judg Ruth 1Sam 2Sam 1Kgs 2Kgs 1Chr 2Chr Ezra Neh Esth Job Ps Prov Eccl Song Isa "
    "Jer Lam Ezek Dan Hos Joel Amos Obad Jonah Mic Nah Hab Zeph Hag Zech Mal Matt Mark Luke John Acts Rom 1Cor "
    "2Cor Gal Eph Phil Col 1Thess 2Thess 1Tim 2Tim Titus Phlm Heb Jas 1Pet 2Pet 1John 2John 3John Jude Rev".split()))
LINE = re.compile(r"^([1-4A-Z]{3}) (\d+):(\d+) (.*)$")


def usfm_plain(text: str) -> str:
    """USFM inline markup off (word|strong="H1" -> word); footnotes dropped."""
    text = re.sub(r"\\f .*?\\f\*", "", text)
    text = re.sub(r"\|[^\\]*?(?=\\w\*)", "", text)
    text = re.sub(r"\\\+?[a-z]+\d?\*?", "", text)
    return re.sub(r"\s+", " ", text).strip()


def psalm_titles(usfm: Path) -> dict[int, list[str]]:
    """Psalm number -> its headings (the USFM d lines; Psalm 119 has one per Hebrew letter)."""
    out: dict[int, list[str]] = {}
    chapter = 0
    for line in usfm.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("\\c "):
            chapter = int(line.split()[1])
        elif line.startswith("\\d ") and chapter:
            out.setdefault(chapter, []).append(usfm_plain(line[3:]))
    return out


def strip_titles(bible: dict[str, str], titles: dict[int, list[str]]) -> int:
    """A heading off the start of verse 1; Psalm 119's letter headings (ALEPH, BETH ...) off the
    start of verse 1 and the end of the verse before each section, where the text put them."""
    n = 0
    for chapter, heads in titles.items():
        if len(heads) == 1:
            key = f"Ps.{chapter}.1"
            if key in bible and bible[key].startswith(heads[0]):
                bible[key] = bible[key][len(heads[0]):].strip()
                n += 1
            continue
        letters = "|".join(re.escape(h) for h in heads)
        for key in [k for k in bible if k.startswith(f"Ps.{chapter}.")]:
            new = re.sub(rf"\s+(?:{letters})$", "", re.sub(rf"^(?:{letters})\s+", "", bible[key]))
            if new != bible[key]:
                bible[key] = new
                n += 1
    return n


def build(vpl: Path) -> dict[str, str]:
    out = {}
    for line in vpl.read_text(encoding="utf-8-sig").splitlines():
        m = LINE.match(line.strip())
        if m and m.group(1) in BOOKS:
            out[f"{BOOKS[m.group(1)]}.{int(m.group(2))}.{int(m.group(3))}"] = m.group(4).strip()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--vpl", required=True)
    ap.add_argument("--psalms-usfm", help="20-PSAeng-web.usfm, to take the psalm headings off verse 1")
    a = ap.parse_args()
    bible = build(Path(a.vpl))
    if a.psalms_usfm:
        titles = psalm_titles(Path(a.psalms_usfm))
        print(f"psalm headings taken out of the verse text: {strip_titles(bible, titles)}")
    path = ROOT / "data" / "web.json"
    path.write_text(json.dumps(bible, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path} ({len(bible)} verses)")


if __name__ == "__main__":
    main()
