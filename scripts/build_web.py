"""Build data/web.json, the World English Bible, from eBible.org's verse-per-line text; with
--version, one of the other public-domain eBible.org texts laid out the same way.

    python scripts/build_web.py --vpl <eng-web_vpl.txt> --psalms-usfm <20-PSAeng-web.usfm>
    (inside https://ebible.org/Scriptures/eng-web_vpl.zip and eng-web_usfm.zip)
    python scripts/build_web.py --version bsb --vpl <engbsb_vpl.txt> --psalms-usfm <20-PSAengbsb.usfm>
    python scripts/build_web.py --version kjv --psalms-usfm <20-PSAeng-kjv.usfm>   (headings off data/kjv.json)

The World English Bible is in the public domain ("World English Bible" is a trademark of
eBible.org, so it is named as such). So are the others (see EBIBLE_IDS); eBible.org marks each
"Public Domain" on its details page, checked 2026-10-26. Only the 66 books are kept, keyed like data/kjv.json
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
# --version -> eBible.org id: Berean Standard Bible (public domain since 2023), American
# Standard Version 1901, the unrevised Elberfelder 1905 (German)
EBIBLE_IDS = {"web": "eng-web", "bsb": "engbsb", "asv": "eng-asv", "elb": "deuelo",
              "kjv": "eng-kjv"}  # kjv: data/kjv.json (scripts/build_data.py) is kept; only its psalm headings come off
LINE = re.compile(r"^([1-4A-Z]{3}) (\d+):(\d+) (.*)$")


def usfm_plain(text: str) -> str:
    """USFM inline markup off (word|strong="H1" -> word); footnotes dropped."""
    text = re.sub(r"\\f .*?\\f\*", "", text)
    text = re.sub(r"\|[^\\]*?(?=\\\+?w\*)", "", text)  # \w and the nested \+w (the KJV's \nd \+w LORD|...\+w*\nd*)
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


def _letters(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def heading_end(text: str, heading: str) -> int:
    """Where a heading at the start of verse 1 ends, comparing letters and digits only: the ASV
    brackets supplied words ("[A Psalm] of David") and the KJV writes "Muth–labben" where the
    USFM heading has "Muthlabben". 0 when the verse does not start with the heading."""
    want, got = _letters(heading), ""
    for i, ch in enumerate(text):
        got += _letters(ch)
        if got == want:
            while i + 1 < len(text) and text[i + 1] in " .,;:!?]’”":  # not "[": Psalm 70 opens "[Make haste]"
                i += 1  # the heading's closing punctuation and the space after it
            return i + 1
        if not want.startswith(got):
            return 0
    return 0


def strip_titles(bible: dict[str, str], titles: dict[int, list[str]]) -> int:
    """A heading off the start of verse 1; Psalm 119's letter headings (ALEPH, BETH ...) off the
    start of verse 1 and the end of the verse before each section, where the text put them."""
    n = 0
    for chapter, heads in titles.items():
        if len(heads) == 1:
            key = f"Ps.{chapter}.1"
            end = heading_end(bible.get(key, ""), heads[0])
            if end:
                bible[key] = bible[key][end:].strip()
                n += 1
            continue
        # the KJV puts the Hebrew letter before the name: "א ALEPH. Blessed are the undefiled"
        letters = r"(?:[א-ת]\s*)?(?:" + "|".join(re.escape(h) for h in heads) + r")\.?"
        for key in [k for k in bible if k.startswith(f"Ps.{chapter}.")]:
            new = re.sub(rf"\s+{letters}$", "", re.sub(rf"^{letters}\s+", "", bible[key]))
            if new != bible[key]:
                bible[key] = new
                n += 1
    # the KJV's Psalm 119 letters are not marked as headings at all: "א ALEPH. Blessed are ..."
    for key in [k for k in bible if k.startswith("Ps.119.")]:
        new = re.sub(r"^[א-ת]\s*[A-Z]+\.\s+", "", bible[key])
        if new != bible[key]:
            bible[key] = new
            n += 1
    return n


# The Elberfelder USFM marks no headings, so they are recognised by their words: each leading
# sentence of verse 1 that is a heading ("Dem Vorsänger." "Ein Psalm von David.") comes off.
# Psalm 18's runs on to "Und er sprach:", which goes with it, as in Luther 1912; Psalm 54's ends
# with the Ziphites' question ("... verborgen?").
ELB_HEADING = re.compile(
    r"^(?:Dem Vorsänger|Eine? (?:Psalm|Lied|Maskil|Gedicht|Gebet|Lobpsalm|Lobgesang|Stufenlied)|"
    r"Von (?:David|Asaph|Salomo|den Söhnen|dem Knechte)|Für (?:Salomo|den Tag)|Gebet eines|Schiggajon|"
    r"“Verdirb nicht!”)[^.]*\.\s+")


def strip_elb_titles(bible: dict[str, str]) -> int:
    n = 0
    for chapter in range(1, 151):
        key = f"Ps.{chapter}.1"
        text = bible.get(key, "")
        if chapter == 54:
            text = re.sub(r"^Dem Vorsänger[^.]*\.\s+Ein Maskil von David, als die Siphiter[^?]*\?\s+", "", text)
        while m := ELB_HEADING.match(text):
            text = text[m.end():]
        if chapter == 18:
            text = re.sub(r"^Und er sprach:\s+", "", text)
        if text != bible.get(key, ""):
            bible[key] = text
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
    ap.add_argument("--version", choices=EBIBLE_IDS, default="web")
    ap.add_argument("--vpl", help="<id>_vpl.txt (not for kjv)")
    ap.add_argument("--psalms-usfm", help="20-PSA<id>.usfm, to take the psalm headings off verse 1")
    a = ap.parse_args()
    if a.version == "kjv":
        bible = json.loads((ROOT / "data" / "kjv.json").read_text(encoding="utf-8"))
    elif a.vpl:
        bible = build(Path(a.vpl))
    else:
        ap.error("--vpl is needed")
    if a.version == "elb":
        print(f"psalm headings taken out of the verse text: {strip_elb_titles(bible)}")
    elif a.psalms_usfm:
        titles = psalm_titles(Path(a.psalms_usfm))
        print(f"psalm headings taken out of the verse text: {strip_titles(bible, titles)}")
    if a.version != "web":
        web = json.loads((ROOT / "data" / "web.json").read_text(encoding="utf-8"))
        missing = sorted(set(web) - set(bible))
        print(f"verses missing from {a.version} but present in web: {len(missing)} {missing[:12]}")
    path = ROOT / "data" / f"{a.version}.json"
    path.write_text(json.dumps(bible, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {path} ({len(bible)} verses)")


if __name__ == "__main__":
    main()
