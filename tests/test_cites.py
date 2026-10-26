"""Source titles in answers follow the answer's language. The page's own readableCites (the
block between // <cites> and // </cites> in human-scoring.html) is run in Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "human_scoring" / "human-scoring.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")


def cites(cases: list[tuple[str, str | None]]) -> list[str]:
    block = re.search(r"// <cites>\n(.*?)// </cites>", PAGE.read_text(encoding="utf-8"), re.S).group(1)
    script = block + "\nconst cases = " + json.dumps(cases, ensure_ascii=False) + ";\n" \
        "process.stdout.write(JSON.stringify(cases.map(([t, l]) => readableCites(t, l))));\n"
    out = subprocess.run([NODE, "-"], input=script.encode("utf-8"), capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def test_titles_follow_the_answer_language():
    zh, en, de = cites([
        ("衛斯理說（*standard-sermons*，第 327 頁，段落 1462）。", "zh"),
        ('"leave the whole event to God" (Wesley, *standard-sermons*, page 328, paragraph 1464).', "en"),
        ("„das ganze Ereignis Gott überlassen“ (*standard-sermons*, Seite 328, Absatz 1464).", "de"),
    ])
    assert zh == "衛斯理說（《衛斯理講道集》，第 327 頁）。"
    assert en == '"leave the whole event to God" (Wesley, Wesley\'s Standard Sermons, page 328).'
    assert de == "„das ganze Ereignis Gott überlassen“ (Die Lehrpredigten John Wesleys, Seite 328)."


def test_every_source_has_an_english_and_a_german_title():
    names = ["wesley-journal", "wesley-hymns-1780", "plain-account-of-christian-perfection",
             "articles-of-religion", "general-rules-1743-en", "課程03-成聖", "屬靈恩賜"]
    texts = [f"(*{n}*)" for n in names]
    for lang in ("en", "de"):
        for out in cites([(t, lang) for t in texts]):
            assert not re.search(r"[㐀-鿿《》]", out), out
    assert cites([("(*課程03-成聖*)", "en"), ("(*課程03-成聖*)", "de"), ("（*課程03-成聖*）", "zh")]) == [
        "(Faith Course, Lesson 3)", "(Glaubenskurs, Lektion 3)", "（《信仰課程：成聖》）"]


def test_hymn_numbers():
    out = cites([
        ("（*wesley-hymns*，第 12 首）", "zh"),
        ('"Mine only is the present hour" (Hymn 835).', "en"),
        ("(*wesley-hymns-1780*, Hymn No. 835)", "en"),
        ("(*wesley-hymns*, Lied 835)", "de"),
        ("(Hymn 835)", "de"),
    ])
    assert out == ["（《衛斯理聖詩集》，第 12 首）", '"Mine only is the present hour" (Wesley Hymns No. 835).',
                   "(Wesley Hymns No. 835)", "(Wesley-Gesangbuch Nr. 835)", "(Wesley-Gesangbuch Nr. 835)"]


def test_a_chinese_answer_keeps_chinese_titles_whatever_the_page_language():
    assert cites([("（*wesley-journal*）", "en")]) == ["（《衛斯理日記》）"]


def test_german_titles_are_the_ones_german_methodists_use():
    assert cites([("(*plain-account*)", "de"), ("(*articles-of-religion*)", "de"), ("(*general-rules-1743-en*)", "de")]) == [
        "(Eine klare Darstellung der christlichen Vollkommenheit)", "(Die Glaubensartikel der Methodistischen Kirche)",
        "(Die Allgemeinen Regeln)"]


def test_new_testament_notes_get_the_emk_title_in_german_only():
    assert cites([
        ("(Wesleys Anmerkungen, Römer 5,8)", "de"),
        ("(Wesley's Explanatory Notes upon the New Testament, Römer 5,8)", "de"),
        ("(John Wesleys Anmerkungen zum Neuen Testament, Römer 5,8)", "de"),
        ("(Wesley's Explanatory Notes, Romans 5:8)", "en"),
    ]) == ["(John Wesleys Anmerkungen zum Neuen Testament, Römer 5,8)"] * 3 + ["(Wesley's Explanatory Notes, Romans 5:8)"]
