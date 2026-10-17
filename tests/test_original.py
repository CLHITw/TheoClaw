import json

import pytest

from theoclaw.common import original


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    d = tmp_path / "original"
    d.mkdir()
    files = {
        "lexicon.json": {"G0026": {"lemma": "ἀγάπη", "translit": "agapē", "pos": "G:N-F", "gloss": "love", "def": "love, goodwill"},
                         "G2316": {"lemma": "θεός", "translit": "theos", "pos": "G:N-M", "gloss": "God", "def": "God"},
                         "G5485": {"lemma": "χάρις", "translit": "charis", "pos": "G:N-F", "gloss": "grace", "def": "grace"},
                         "H2580": {"lemma": "חֵן", "translit": "chen", "pos": "H:N-M", "gloss": "favor", "def": "favour, grace"},
                         "H4941": {"lemma": "מִשְׁפָּט", "translit": "mishpat", "pos": "H:N-M", "gloss": "justice", "def": "judgment"}},
        "verses.json": {"Rom.5.8": [["神", ["G2316"], False], ["的", ["G3588"], True], ["愛", ["G0026"], False]],
                        "Rom.5.9": [["愛", ["G0026"], False]]},
        "renderings.json": {"G0026": [["愛", 100], ["愛心", 20]], "G5485": [["恩典", 120], ["恩惠", 9]]},
        "zh_index.json": {"恩典": [["G5485", 120]], "神": [["G2316", 1300]], "恩惠": [["G5485", 9], ["H2580", 4]],
                          "愛": [["G0026", 36]], "典章": [["H4941", 90]]},
        "frequency.json": {"G0026": 116, "G2316": 1317, "G5485": 155, "G3588": 19000, "H2580": 69, "H4941": 420},
    }
    for name, obj in files.items():
        (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(original, "DIR", d)
    original._load.cache_clear()
    yield
    original._load.cache_clear()


def test_word_study_lists_content_words_once_with_their_verses(tiny):
    rows = original.word_study("羅馬書 5:8-9")
    assert [r["strong"] for r in rows] == ["G2316", "G0026"]  # the article (minor) is left out
    assert rows[1]["where"] == ["5:8", "5:9"] and rows[1]["renderings"][:2] == ["愛", "愛心"]
    assert original.word_study("not a reference") == []
    table = original.render(rows)
    assert "ἀγάπη (G0026)" in table and "STEPBible" in table


def test_theme_words_match_the_bibles_own_vocabulary(tiny):
    assert original.segment("恩典與神") == ["恩典"]  # single characters are not matched inside a phrase
    rows = original.theme_words("恩典")
    assert [(r["strong"], r["match"]) for r in rows] == [("G5485", "exact"), ("H2580", "near")]  # 恩典 -> χάρις -> 恩惠 -> חֵן
    assert "H4941" not in {r["strong"] for r in rows}  # sharing the character 典 (典章) is not a synonym
    assert [r["strong"] for r in original.theme_words("愛")] == ["G0026"]  # a single-character theme
    assert "近似" in original.render(rows)


def test_without_data_nothing_breaks(tmp_path, monkeypatch):
    monkeypatch.setattr(original, "DIR", tmp_path / "missing")
    assert original.word_study("羅馬書 5:8") == [] and original.theme_words("恩典") == [] and original.render([]) == ""
