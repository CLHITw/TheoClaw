"""Build data/lut.json, the Luther Bible 1912, from eBible.org's verse-per-line text.

    python scripts/build_lut.py --vpl <deu1912_vpl.txt>
    (inside https://ebible.org/Scriptures/deu1912_vpl.zip)

Luther 1912 is public domain (eBible.org, id deu1912). Only the 66 books are kept, keyed
like data/web.json ("John.3.16"); the verse-per-line edition uses the same book codes as
the WEB one. The verse-per-line text keeps each psalm's heading inside verse 1 ("Ein
Psalm Davids. Der HERR ist mein Hirte; ..."); it is taken off, as for the WEB, so a quoted
verse 1 starts with the psalm itself. The USFM edition marks no headings either, so they are
recognised by how they begin and end at their first full stop (Psalm 88 has two sentences,
Psalm 18 runs on to "und sprach:"). Luther 1912 has no Psalm-119 letter headings.
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


TITLE_START = re.compile(r"^(?:Eine? |Die Unschuld |Des Salomo\.|Auf der Gittith|Davids\.)")
TITLE_END = {18: "und sprach: ", 88: "des Esrahiten. "}  # every other heading ends at its first ". "


def strip_titles(bible: dict[str, str]) -> int:
    """Take each psalm's heading off the start of verse 1; returns how many were taken off."""
    n = 0
    for chapter in range(1, 151):
        key = f"Ps.{chapter}.1"
        text = bible.get(key, "")
        if not TITLE_START.match(text):
            continue
        end = TITLE_END.get(chapter, ". ")
        i = text.find(end)
        if i < 0:
            raise SystemExit(f"Psalm {chapter}: heading end {end!r} not found")
        bible[key] = text[i + len(end):].strip()
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
    a = ap.parse_args()
    bible = build(Path(a.vpl))
    print(f"psalm headings taken out of the verse text: {strip_titles(bible)}")
    web = json.loads((ROOT / "data" / "web.json").read_text(encoding="utf-8"))
    missing = sorted(set(web) - set(bible))
    print(f"verses missing from lut but present in web: {len(missing)}")
    for k in missing[:12]:
        print(" ", k)
    path = ROOT / "data" / "lut.json"
    path.write_text(json.dumps(bible, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path} ({len(bible)} verses)")


if __name__ == "__main__":
    main()
