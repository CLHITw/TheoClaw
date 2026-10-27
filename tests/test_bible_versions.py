"""The public-domain Bible versions a reader can pick (BSB, ASV, Elberfelder 1905): their data,
lookups, placeholder filling, grading, and the version carried from the page to the agent."""

import importlib.util
import re
import time
from pathlib import Path

import pytest

from theoclaw.agent.quotes import fill_placeholders
from theoclaw.agent.tools import lookup_verse
from theoclaw.common.corpus import default_corpus
from theoclaw.evals.grading import quotation_citations, quotation_version

_spec = importlib.util.spec_from_file_location("build_web", Path(__file__).parent.parent / "scripts" / "build_web.py")
build_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_web)


@pytest.mark.parametrize("version, john316, ps23", [
    ("bsb", "For God so loved the world that He gave His one and only Son",
     "The LORD is my shepherd; I shall not want."),
    ("asv", "For God so loved the world, that he gave his only begotten Son",
     "Jehovah is my shepherd; I shall not want."),
    ("elb", "Denn also hat Gott die Welt geliebt, daß er seinen eingeborenen Sohn gab",
     "Jehova ist mein Hirte, mir wird nichts mangeln."),
])
def test_data_files(version, john316, ps23):
    c = default_corpus()
    assert c.verse_text("John", 3, 16, version).startswith(john316)
    assert c.verse_text("Ps", 23, 1, version) == ps23  # the heading "A Psalm of David." is off verse 1
    assert len(c.bible(version)) > 31000


@pytest.mark.parametrize("version", ["bsb", "asv", "elb"])
def test_no_psalm_heading_left_on_verse_one(version):
    b = default_corpus().bible(version)
    words = ("Psalm ", "Psalm.", "Musician", "choirmaster", "Vorsänger", "Maskil", "Stufenlied", "Song of Ascents")
    assert [c for c in range(1, 151) if any(w in b[f"Ps.{c}.1"][:40] for w in words)] == []
    assert b["Ps.18.1"].startswith(("I love", "Ich liebe"))


def test_asv_brackets_do_not_hide_a_heading():
    bible = {"Ps.11.1": "For the Chief Musician. [A Psalm] of David. In Jehovah do I take refuge"}
    assert build_web.strip_titles(bible, {11: ["For the Chief Musician. A Psalm of David."]}) == 1
    assert bible["Ps.11.1"] == "In Jehovah do I take refuge"


def test_elberfelder_headings_recognised_by_their_words():
    bible = {"Ps.4.1": "Dem Vorsänger mit Saitenspiel. Ein Psalm von David. Wenn ich rufe, antworte mir",
             "Ps.54.1": "Dem Vorsänger, mit Saitenspiel. Ein Maskil von David, als die Siphiter kamen und zu Saul "
                        "sprachen: Hält David sich nicht bei uns verborgen? Gott, durch deinen Namen rette mich",
             "Ps.101.1": "Von David; ein Psalm. Von Güte und Recht will ich singen",
             "Ps.1.1": "Glückselig der Mann"}
    assert build_web.strip_elb_titles(bible) == 3
    assert bible["Ps.4.1"] == "Wenn ich rufe, antworte mir"
    assert bible["Ps.54.1"] == "Gott, durch deinen Namen rette mich"
    assert bible["Ps.101.1"] == "Von Güte und Recht will ich singen"  # "Von Güte" is the psalm, not a heading


def _handlers():
    c = default_corpus()
    return {"lookup_verse": lambda inp: lookup_verse(inp, c)}


def test_lookup_and_fill_new_versions():
    assert lookup_verse({"reference": "Romans 5:8", "version": "bsb"}, default_corpus()).startswith("【BSB】Romans 5:8")
    assert lookup_verse({"reference": "Römer 5:8", "version": "elb"}, default_corpus()).startswith("【Elberfelder 1905】Römer 5")
    text, calls = fill_placeholders("〔經文：Romans 5:8，BSB〕\n〔經文：Römer 5:8，ELB〕", _handlers())
    assert "“But God proves His love for us in this" in text and "(Romans 5:8, BSB)" in text
    assert "„Gott aber erweist seine Liebe" in text and "(Römer 5,8, Elberfelder 1905)" in text
    assert [c.input["version"] for c in calls] == ["bsb", "elb"]


def test_picked_version_replaces_the_default_only():
    text, calls = fill_placeholders("〔經文：Romans 5:8，WEB〕 〔經文：John 3:16，KJV〕", _handlers(), bible="bsb")
    assert [c.input["version"] for c in calls] == ["bsb", "kjv"]  # an asked-for KJV stays KJV
    assert "(Romans 5:8, BSB)" in text and "(John 3:16, KJV)" in text
    _, calls = fill_placeholders("〔經文：Römer 5:8，LUT〕 〔經文：羅馬書 5:8〕", _handlers(), bible="elb")
    assert [c.input["version"] for c in calls] == ["elb", "cuv"]


def test_graders_know_the_new_tags():
    assert quotation_version("while we were still sinners", "Romans 5:8, BSB") == "bsb"
    assert quotation_version("while we were yet sinners", "Romans 5:8, ASV") == "asv"
    assert quotation_version("da wir noch Sünder waren", "Römer 5,8, ELB") == "elb"
    [(span, cite, refs)] = quotation_citations("“While we were still sinners” (Romans 5:8, BSB)")
    assert refs[0].book == "Rom"


def test_page_bible_reaches_the_agent(tmp_path, monkeypatch):
    import human_scoring.human_server as hs
    monkeypatch.setattr(hs, "CHAT_DIR", tmp_path / "default-chat")
    monkeypatch.setenv("THEOCLAW_DB", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    path = tmp_path / "assignment.json"
    hs.prepare([], ["牧者1"], None, None, path)
    code = hs.add_group("International", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0}, chat_dir=tmp_path / "pastor-chat")
    seen = []
    fake = lambda q: seen.append(q) or {"model": "m", "prompt": q, "final_text": "answer", "outcome": "completed",
                                        "steps": [], "usage_total": {}, "cost_usd": 0.001}
    nick = ("Eden", "e" * 20)
    store.db.record_consent(store.who(code, nick))
    for lang, bible in [("en", "bsb"), ("en", "web"), ("zh", "bsb"), ("de", "elb"), ("en", "niv")]:
        store.ask(code, "What is grace?", runner=fake, nick=nick, lang=lang, bible=bible)
        time.sleep(0.3)
    assert 'Berean Standard Bible (BSB): look verses up with version "bsb"' in seen[0]
    assert seen[1].endswith("(Please answer in English.)")  # the default needs no note
    assert "version" not in seen[2]  # Chinese answers always quote the 和合本
    assert 'Elberfelder 1905 (ELB): Verse mit version "elb"' in seen[3]
    assert seen[4].endswith("(Please answer in English.)")  # not a version on offer
    assert [r.get("bible") for r in store.db.answers()] == ["bsb", None, None, "elb", None]


def test_html_answers_become_markdown():
    from theoclaw.agent.quotes import html_to_markdown
    text = "<p><strong>2. 懶惰的特徵</strong></p>\n<p>箴言說<em>再睡片時</em>。<br>下一行</p>\n<h3>三、順服</h3><ul><li>一</li><li>二</li></ul>"
    assert html_to_markdown(text) == "**2. 懶惰的特徵**\n\n箴言說*再睡片時*。\n下一行\n\n## 三、順服\n\n- 一\n- 二"
    assert html_to_markdown("a < b and **bold**") == "a < b and **bold**"  # no HTML: untouched


def test_unpaired_cuv_quote_marks_come_off():
    from theoclaw.agent.quotes import _render
    assert _render("【和合本】約翰福音 3:16\n3:16 「神愛世人，反得永生。", "cuv", "約翰福音 3:16") == \
        "「神愛世人，反得永生。」（約翰福音 3:16，和合本）"
    assert _render("【和合本】x\n1:1 他說：「你們要去。」", "cuv", "x") == "「他說：『你們要去。』」（x，和合本）"


def test_resurrection_is_not_turned_into_overturning():
    from theoclaw.common import zh
    if zh.available():
        assert zh.to_traditional("第三天\u590d活了") == "第三天復活了"


@pytest.mark.parametrize("version, ps69", [
    ("cuv", "神啊，求你救我！因為眾水要淹沒我。"),
    ("kjv", "Save me, O God; for the waters are come in unto my soul."),
])
def test_cuv_and_kjv_psalms_start_with_the_psalm(version, ps69):
    b = default_corpus().bible(version)
    assert b["Ps.69.1"] == ps69  # not 「（大衛的詩，交與伶長。調用百合花。）」 / "To the chief Musician upon Shoshannim"
    assert not [c for c in range(1, 151) if b[f"Ps.{c}.1"].startswith(("（", "To the chief", "A Psalm", "A Song"))]
    assert not [k for k, v in b.items() if k.startswith("Ps.119.") and "ALEPH" in v]


def test_heading_end_ignores_brackets_and_dashes():
    assert build_web.heading_end("To the chief Musician upon Muth–labben, A Psalm of David. I will praise",
                                 "To the chief Musician upon Muthlabben, A Psalm of David.") == 58
    assert build_web.heading_end("[Make haste], O God", "of David, to bring to remembrance.") == 0


def test_unversioned_markers_follow_the_answer_language():
    from theoclaw.agent.quotes import answer_language
    de = "Die Taufe geschieht im Namen des Vaters und des Sohnes und des Geistes: 〔經文：Matthäus 28,19〕 Das ist nicht wenig."
    en = "Moses pitched the tent outside the camp, and the people watched: 〔經文：Exodus 33:7〕 That is the point."
    zh = "耶穌差遣門徒去使萬民作他的門徒，奉父、子、聖靈的名施洗，這是教會的使命：〔經文：馬太福音 28:19〕"
    assert [answer_language(t) for t in (de, en, zh)] == ["de", "en", "zh"]
    _, calls = fill_placeholders(de, _handlers())
    assert calls[0].input["version"] == "lut"
    _, calls = fill_placeholders(en, _handlers(), bible="bsb")
    assert calls[0].input["version"] == "bsb"   # the reader's pick, not the 和合本
    text, calls = fill_placeholders(zh, _handlers())
    assert calls[0].input["version"] == "cuv" and "和合本" in text


def test_no_chinese_in_english_or_german_answers():
    from theoclaw.agent.quotes import scrub_internal
    en = "Jesus speaks of God's love for the whole world in this verse: 〔經文：John 3:16，和合本〕 and also 〔經文：Hezekiah 9:9〕"
    text, calls = fill_placeholders(en, _handlers())
    assert calls[0].input["version"] == "web"            # a 和合本 tag in an English answer: WEB
    assert "[Bible passage not found: Hezekiah 9:9]" in text
    de = "Ich habe das mit lookup_verse und wesley_note nachgeschlagen, und das ist nicht schwer."
    assert scrub_internal(de, "de")[0] == "Ich habe das mit die Bibelsuche und Wesleys Anmerkungen nachgeschlagen, und das ist nicht schwer."
    assert not re.search(r"[㐀-鿿]", text + scrub_internal("I used lookup_verse here.", "en")[0])
