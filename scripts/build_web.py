"""Build data/web.json, the World English Bible, from eBible.org's verse-per-line text.

    python scripts/build_web.py --vpl <eng-web_vpl.txt>     (inside https://ebible.org/Scriptures/eng-web_vpl.zip)

The World English Bible is in the public domain ("World English Bible" is a trademark of
eBible.org, so it is named as such). Only the 66 books are kept, keyed like data/kjv.json
("John.3.16"); the deuterocanonical books in the same file are left out.
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
    path = ROOT / "data" / "web.json"
    path.write_text(json.dumps(bible, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path} ({len(bible)} verses)")


if __name__ == "__main__":
    main()
