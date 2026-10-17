"""English renderings for the word study (data/original/en_*.json), from STEPBible's tagged Bibles.

    python scripts/build_original_en.py --step-dir <folder with TAGNT and TAHOT> --lex-dir <folder with TBESG and TBESH>

Source and licence (credit it wherever the data is shown): STEPBible.org, Tyndale House
Cambridge, CC BY 4.0 — TAGNT (Translators Amalgamated Greek NT), TAHOT (Translators
Amalgamated Hebrew OT) and the TBESG / TBESH lexicons, https://github.com/STEPBible/STEPBible-Data.
Every Greek and Hebrew word carries its Strong's number and STEP's own English translation in
context (not the ESV or KJV text).

Written files (git-ignored; packed for the server):
- en_verses.json      "OSIS.chapter.verse" -> [[English in context, [Strong's numbers]], ...]
- en_renderings.json  Strong's number -> its usual English renderings, with counts
- en_frequency.json   Strong's number -> occurrences in the tagged Greek NT and Hebrew OT
- en_lexicon.json     Strong's number -> lemma, transliteration, part of speech, gloss, short definition

Numbers are kept extended where STEP gives a letter (G4151G; H7462B "to pasture", where the
plain H7462's first lexicon entry is a place name), and counted under the plain number too, so a
lookup can fall back to it.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "original"

# STEPBible book codes -> the OSIS-style codes data/original/verses.json uses
BOOKS = dict(zip(
    "Gen Exo Lev Num Deu Jos Jdg Rut 1Sa 2Sa 1Ki 2Ki 1Ch 2Ch Ezr Neh Est Job Psa Pro Ecc Sng Isa Jer Lam "
    "Ezk Dan Hos Jol Amo Oba Jon Mic Nam Hab Zep Hag Zec Mal Mat Mrk Luk Jhn Act Rom 1Co 2Co Gal Eph Php "
    "Col 1Th 2Th 1Ti 2Ti Tit Phm Heb Jas 1Pe 2Pe 1Jn 2Jn 3Jn Jud Rev".split(),
    "Gen Exod Lev Num Deut Josh Judg Ruth 1Sam 2Sam 1Kgs 2Kgs 1Chr 2Chr Ezra Neh Esth Job Ps Prov Eccl Song "
    "Isa Jer Lam Ezek Dan Hos Joel Amos Obad Jonah Mic Nah Hab Zeph Hag Zech Mal Matt Mark Luke John Acts "
    "Rom 1Cor 2Cor Gal Eph Phil Col 1Thess 2Thess 1Tim 2Tim Titus Phlm Heb Jas 1Pet 2Pet 1John 2John 3John "
    "Jude Rev".split()))
REF = re.compile(r"^([1-3]?[A-Z][a-z]{1,3})\.(\d+)\.(\d+)(?:\(\d+\.\d+\))?#\d+")
STRONG = re.compile(r"([GH])(\d{1,4})([A-Za-z]?)")
SMALL = {"a", "an", "the", "of", "to", "and", "in", "for", "you", "he", "she", "it", "they", "his", "her",
         "is", "was", "be", "will", "my", "your", "our", "their", "that", "this", "with", "on", "by", "from"}
PARTICLE = 9000   # Hebrew prefixes and suffixes STEP tags with their own numbers (H9001 and up)
SUFFIX = re.compile(r"(\w)<(\w+)>")   # "loyalti<es>" -> "loyalties"


def norm(letter: str, num: str, ext: str = "") -> str:
    return f"{letter}{int(num):04d}{ext.upper()}"


def rendering(english: str) -> str:
    """'[the] Spirit,' -> 'spirit'; 'you have received' -> 'have received'; '' if nothing is left."""
    w = re.sub(r"\[[^\]]*\]|<[^>]*>|[.,;:!?\"“”‘’()]", " ", english.lower())
    words = [x for x in w.split() if x]
    while words and words[0] in SMALL:
        words.pop(0)
    while words and words[-1] in SMALL:
        words.pop()
    return " ".join(words)


def read(step_dir: Path) -> dict[str, list]:
    verses: dict[str, list] = defaultdict(list)
    for path in sorted(step_dir.glob("TA[GH][NO]T *.txt")):
        hebrew = path.name.startswith("TAHOT")
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            m = REF.match(line)
            if not m or m.group(1) not in BOOKS:
                continue
            key = f"{BOOKS[m.group(1)]}.{int(m.group(2))}.{int(m.group(3))}"
            f = line.split("\t")
            if hebrew:   # ref, Hebrew, transliteration, translation "in/ beginning", dStrongs "H9003/{H7225G}"
                if len(f) < 5:
                    continue
                # the word's parts ("in/ beginning", "loyalti<es>") read as one; the main word is in braces
                eng = SUFFIX.sub(r"\1\2", f[3].replace("/ ", " ").replace("/", "")).strip()
                tags = [t for t in re.split(r"[/\\]", f[4]) if "{" in t] or re.split(r"[/\\]", f[4])
                nums = [norm(a, b, c) for t in tags for a, b, c in STRONG.findall(t) if int(b) < PARTICLE]
            else:        # ref, Greek, English translation, "G4151G=N-ASN", ...
                if len(f) < 4:
                    continue
                eng = SUFFIX.sub(r"\1\2", f[2]).strip()
                nums = [norm(a, b, c) for a, b, c in STRONG.findall(f[3].split("=")[0])]
            if nums:
                verses[key].append([eng, nums])
    return verses


def clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "; ", text, flags=re.I)
    text = re.sub(r"<ref=[^>]*>|</ref>|<[^>]+>", "", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip(" ;")


def read_lexicons(lex_dir: Path) -> dict[str, dict]:
    """TBESG / TBESH by the extended number in the third column (G4151G, H7462B); the first
    entry for a plain number is kept under it too, as the fallback."""
    out: dict[str, dict] = {}
    for path in sorted(lex_dir.glob("TBES[GH]*.txt")):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            f = line.split("\t")
            if len(f) < 8 or not re.match(r"^[GH]\d{4}", f[0]):
                continue
            m = STRONG.match(f[2].strip())
            if not m:
                continue
            entry = {"lemma": f[3].strip(), "translit": f[4].strip(), "pos": f[5].strip(),
                     "gloss": clean(f[6]), "def": clean(f[7])[:400]}
            for key in (norm(*m.groups()), norm(m.group(1), m.group(2))):
                out.setdefault(key, entry)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--step-dir", required=True, help="folder with the TAGNT and TAHOT files")
    ap.add_argument("--lex-dir", required=True, help="folder with the TBESG and TBESH lexicons")
    a = ap.parse_args()
    verses = read(Path(a.step_dir))
    freq: Counter = Counter()
    rend: dict[str, Counter] = defaultdict(Counter)
    for words in verses.values():
        for eng, nums in words:
            r = rendering(eng)
            for s in nums:
                for key in {s, s[:5]}:      # the extended number and the plain one
                    freq[key] += 1
                    if r and len(nums) == 1:   # a translation shared by several tagged words says little about each
                        rend[key][r] += 1
    lex = read_lexicons(Path(a.lex_dir))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "en_verses.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
    (OUT / "en_renderings.json").write_text(json.dumps({s: c.most_common(8) for s, c in rend.items()}, ensure_ascii=False),
                                            encoding="utf-8")
    (OUT / "en_frequency.json").write_text(json.dumps(dict(freq)), encoding="utf-8")
    (OUT / "en_lexicon.json").write_text(json.dumps(lex, ensure_ascii=False), encoding="utf-8")
    print(f"{len(verses):,} verses, {sum(len(w) for w in verses.values()):,} tagged words, "
          f"{len(rend):,} Strong's numbers with English renderings, {len(lex):,} lexicon entries -> {OUT}")


if __name__ == "__main__":
    main()
