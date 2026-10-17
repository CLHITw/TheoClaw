import json

from theoclaw.kb import hymns
from theoclaw.kb.query import rag


PAGE_1 = """9
Exhorting Sinners to return to God.
HYMN
1.
c. m.
1 OFOR a thousand tongues to sing
My great Redeemer's praise
;
The glories of my God
and King
!
HYMN 2. l. m.
1 Come, sinners, to the gospel feast
"""
PAGE_2 = """JO
Exhorting Sinners
to return to God.
2 Ye all may now be justified
;
See HYMN 9. for the tune.
HYMN 3.
1 Ho! every one that thirsts, draw nigh
"""
INDEX = """INDEX TO THE HYMNS.
HYMN 4. never counted
"""


def test_split_by_headings_joins_broken_lines_and_ignores_cross_references():
    hs = hymns.split_hymns([PAGE_1, PAGE_2, INDEX])
    assert [h["number"] for h in hs] == [1, 2, 3]  # "See HYMN 9." is too far ahead; the index is not read
    assert hs[0]["section"] == "Exhorting Sinners to return to God"
    assert "My great Redeemer's praise;" in hs[0]["text"] and "God and King!" in hs[0]["text"]
    assert "Ye all may now be justified;" in hs[1]["text"]  # continues across the page break
    assert hs[2]["section"] == "Exhorting Sinners to return to God"


def test_hymns_are_searched_one_per_passage_after_the_sources(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "sources").mkdir(parents=True)
    (wiki / "sources" / "a.md").write_text("perfect love " * 10, encoding="utf-8")
    (wiki / "sources" / "b.md").write_text("assurance witness " * 10, encoding="utf-8")
    (wiki / "hymns").mkdir()
    (wiki / "hymns" / "wesley-hymns-1780.json").write_text(json.dumps(
        [{"number": 385, "page": 1, "section": "Seeking for full Redemption", "text": "Love Divine, all loves excelling"}]),
        encoding="utf-8")
    ix = rag.index_wiki_sources(wiki)
    assert [c.index for c in ix.chunks] == [1, 2, 3]  # numbered through the whole index
    top = ix.search("loves excelling", 1)[0][1]
    assert top.doc == "wesley-hymns-1780 第 385 首" and top.text.startswith("HYMN 385 (Seeking")
    assert "聖詩" in rag.system_addendum(wiki) and "聖詩" not in rag.system_addendum(tmp_path)
