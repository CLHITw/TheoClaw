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
    original._main_sense.cache_clear()
    yield
    original._load.cache_clear()
    original._main_sense.cache_clear()


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


def test_english_word_study_from_the_tagged_text_and_the_main_sense(tiny):
    d = original.DIR
    en = {
        "en_verses.json": {"Ps.23.1": [["Yahweh", ["H3068G"]], ["[is] shepherd my", ["H7462B"]], ["I lack", ["H2637"]]]},
        "en_lexicon.json": {"H7462": {"lemma": "בֵּית־עֵקֶד", "translit": "bet-eqed", "pos": "N:N--L", "gloss": "House of Shepherds", "def": ""},
                            "H7462A": {"lemma": "בֵּית־עֵקֶד", "translit": "bet-eqed", "pos": "N:N--L", "gloss": "House of Shepherds", "def": ""},
                            "H7462B": {"lemma": "רָעָה", "translit": "ra.ah", "pos": "H:V", "gloss": "to pasture", "def": "to tend"},
                            "H2637": {"lemma": "חָסֵר", "translit": "cha.ser", "pos": "H:V", "gloss": "to lack", "def": "to lack"},
                            "H3068G": {"lemma": "יְהוָה", "translit": "YHWH", "pos": "N:N-M-T", "gloss": "LORD", "def": "LORD"}},
        "en_renderings.json": {"H7462B": [["shepherd", 48], ["graze", 17]], "H2637": [["lack", 9]]},
        "en_frequency.json": {"H7462": 170, "H7462A": 1, "H7462B": 169, "H2637": 23, "H3068G": 6000, "H3068": 6000},
    }
    for name, obj in en.items():
        (d / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    original._load.cache_clear()
    original._main_sense.cache_clear()
    rows = original.word_study_en("Psalm 23:1")
    assert [r["gloss"] for r in rows] == ["to pasture", "to lack"]  # the extended sense, not the place; LORD too common
    assert rows[0]["here"] == ["[is] shepherd my"] and rows[0]["usual"] == ["shepherd", "graze"]
    table = original.render(rows, lang="en")
    assert "Translated here" in table and "רָעָה (H7462)" in table and "TAGNT" in table
    assert original._main_sense()["H7462"]["gloss"] == "to pasture"  # the Chinese word study's sense too
