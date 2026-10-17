"""Build the original-language data for word studies (data/original/), from openly licensed sources.

    python scripts/build_original.py --step-dir <STEPBible lexicons folder> --fhl-db <bible_gb_little.db>

Sources and licences (credit them wherever the data is shown):
- STEPBible.org, Tyndale House Cambridge, CC BY 4.0: TBESG (Greek, Abbott-Smith based) and TBESH
  (Hebrew, BDB based) brief lexicons of Extended Strong's numbers.
- 信望愛 FHL: the 和合本 with Strong's numbers (table unv), open FDL; the Strong's tags must be kept.
  Only the tagged Bible text is used. The FHL Chinese Strong's dictionary in the same file
  (tables gfhl, hfhl) is not used: part of it comes from a publisher whose licence is unclear.

Written files (git-ignored; packed for the server):
- lexicon.json   Strong's number -> lemma, transliteration, part of speech, gloss, short definition
- verses.json    "OSIS.chapter.verse" -> [[Chinese words, [Strong's numbers]], ...], 和合本 in 繁體
- renderings.json Strong's number -> the Chinese words the 和合本 uses for it, with counts
- zh_index.json  Chinese word -> Strong's numbers it renders, with counts (for matching a theme)
- frequency.json Strong's number -> occurrences in the tagged 和合本 (very frequent ones are skipped)
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from theoclaw.common import zh  # noqa: E402
from theoclaw.common.refs import RefError, parse_ref  # noqa: E402

OUT = ROOT / "data" / "original"
TAG = re.compile(r"<W(A?)([GH])(\d+)>")
MORPH = re.compile(r"<WT[GH]\d+>")
DEF_CHARS = 400
from theoclaw.common.original import to_hant  # noqa: E402  (繁體, with the 和合本's own variant forms)


def norm(letter: str, num: str) -> str:
    return f"{letter}{int(num):04d}"


def clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "; ", text, flags=re.I)
    text = re.sub(r"<ref=[^>]*>|</ref>|<[^>]+>", "", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip(" ;")
    return text


def read_lexicon(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        f = line.split("\t")
        if len(f) < 8 or not re.match(r"^[GH]\d{4}", f[0]):
            continue
        key = f[0][:5]
        if key in out:  # extended numbers (G0001H, H2617b ...): keep the first, main sense
            continue
        out[key] = {"lemma": f[3].strip(), "translit": f[4].strip(), "pos": f[5].strip(),
                    "gloss": clean(f[6]), "def": clean(f[7])[:DEF_CHARS]}
    return out


def book_map(con: sqlite3.Connection) -> dict[str, str]:
    """FHL book code (Gen, 1 Kin, Is ...) -> OSIS id, through the Chinese book name."""
    out = {}
    for engs, chinesef in con.execute("select engs, chinesef from main"):
        name = to_hant(chinesef.strip())
        try:
            out[engs.strip()] = parse_ref(f"{name} 1:1").book
        except RefError:
            raise SystemExit(f"cannot map FHL book {engs!r} ({name})")
    return out


def split_verse(txt: str) -> list[tuple[str, list[str], bool]]:
    """[(Chinese words, [Strong's], minor)]: the words before a run of tags are what those tags
    render; {…} marks an original word the translation leaves out; WA tags are minor words."""
    txt = MORPH.sub("", txt)
    out, pos, buf = [], 0, ""
    items = list(TAG.finditer(txt))
    i = 0
    while i < len(items):
        m = items[i]
        buf += txt[pos:m.start()]
        run = [m]
        while i + 1 < len(items) and items[i + 1].start() == run[-1].end():
            i += 1
            run.append(items[i])
        words = re.sub(r"[\s　「」『』，。；：、？！（）{}\[\]]", "", buf)
        strongs = [norm(r.group(2), r.group(3)) for r in run]
        minor = all(r.group(1) == "A" for r in run)
        out.append((to_hant(words), strongs, minor))
        buf, pos = "", run[-1].end()
        i += 1
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--step-dir", required=True)
    ap.add_argument("--fhl-db", required=True)
    a = ap.parse_args(argv)
    step = Path(a.step_dir)
    lex = {}
    for pattern in ("TBESG*.txt", "TBESH*.txt"):
        files = sorted(step.glob(pattern))
        if not files:
            raise SystemExit(f"no {pattern} in {step}")
        lex.update(read_lexicon(files[0]))
    con = sqlite3.connect(f"file:{a.fhl_db}?mode=ro", uri=True)
    books = book_map(con)
    verses, renderings, index, freq = {}, defaultdict(Counter), defaultdict(Counter), Counter()
    for engs, chap, sec, txt in con.execute("select engs, chap, sec, txt from unv"):
        parts = split_verse(txt or "")
        verses[f"{books[engs.strip()]}.{chap}.{sec}"] = [[w, s, minor] for w, s, minor in parts]
        for words, strongs, minor in parts:
            for s in strongs:
                freq[s] += 1
                shown = words.strip("的")  # 「的恩」 -> 「恩」: the particle is the sentence's, not the word's
                if shown and not minor and len(shown) <= 4 and not any(x in shown for x in ("或譯", "願")):
                    renderings[s][shown] += 1
            if words and len(strongs) == 1 and not minor:
                index[words][strongs[0]] += 1
    OUT.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")),
                                                     encoding="utf-8")
    dump("lexicon.json", lex)
    dump("verses.json", verses)
    dump("renderings.json", {s: c.most_common(12) for s, c in renderings.items()})
    dump("zh_index.json", {w: c.most_common(8) for w, c in index.items() if len(w) <= 6})
    dump("frequency.json", dict(freq))
    (OUT / "SOURCES.md").write_text(
        "Lexicons: STEPBible.org (Tyndale House, Cambridge), TBESG and TBESH, CC BY 4.0.\n"
        "和合本 with Strong's numbers: 信望愛 FHL (https://www.fhl.net/main/fhl/fhl8.html), FDL; Strong's tags kept.\n",
        encoding="utf-8")
    print(f"{len(lex)} lexicon entries, {len(verses)} verses, {len(index)} Chinese words -> {OUT}")


if __name__ == "__main__":
    main()
