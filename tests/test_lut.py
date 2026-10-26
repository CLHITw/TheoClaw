import importlib.util
from pathlib import Path

from theoclaw.agent.quotes import _render

_spec = importlib.util.spec_from_file_location("build_lut", Path(__file__).parent.parent / "scripts" / "build_lut.py")
build_lut = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_lut)


def test_psalm_headings_come_off_verse_one():
    bible = {
        "Ps.1.1": "Wohl dem, der nicht wandelt im Rat der Gottlosen,",
        "Ps.18.1": "Ein Psalm, vorzusingen, Davids, des Knechtes des HERRN, welcher hat dem Herrn die Worte "
                   "dieses Liedes geredet, und sprach: Herzlich lieb habe ich dich, HERR, meine Stärke!",
        "Ps.23.1": "Ein Psalm Davids. Der HERR ist mein Hirte; mir wird nichts mangeln.",
        "Ps.88.1": "Ein Psalmlied der Kinder Korah, vorzusingen. Eine Unterweisung Hemans, des Esrahiten. "
                   "HERR, Gott, mein Heiland, ich schreie Tag und Nacht vor dir.",
        "Ps.138.1": "Davids. Ich danke dir von ganzem Herzen.",
    }
    assert build_lut.strip_titles(bible) == 4
    assert bible["Ps.1.1"].startswith("Wohl dem")
    assert bible["Ps.18.1"] == "Herzlich lieb habe ich dich, HERR, meine Stärke!"
    assert bible["Ps.23.1"] == "Der HERR ist mein Hirte; mir wird nichts mangeln."
    assert bible["Ps.88.1"].startswith("HERR, Gott, mein Heiland")
    assert bible["Ps.138.1"] == "Ich danke dir von ganzem Herzen."


def test_quotation_does_not_end_on_a_comma():
    out = "【Luther 1912】1. Korinther 13,4-5\n13:4 Die Liebe ist langmütig,\n13:5 sie rechnet das Böse nicht zu,"
    assert _render(out, "lut", "1. Korinther 13,4-5").startswith("„Die Liebe ist langmütig, sie rechnet das Böse nicht zu“")
    assert _render("【WEB】\n1:1 Blessed is the man,", "web", "Psalms 1:1") == "“Blessed is the man” (Psalms 1:1, WEB)"
