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
    assert "掃描" in rag.system_addendum(wiki)  # this file came from OCR (entries carry a page)


CONTENTS = """<H2><A NAME="contents"></A>CONTENTS.</H2>
<P>
PART I. CONTAINING INTRODUCTORY HYMNS
<P>
SECTION I. <A HREF="#h1" >Exhorting Sinners to return to God
</A>1
<P>
PART V.
<P>
SECTION I. <A HREF="#h478" >For the Society Meeting  </A>478
<P>
II. <A HREF="#h488" >Giving Thanks  </A>488
<P>
SUPPLEMENT.
<P>
SECTION III. THE LORD JESUS CHRIST.
<P>
<A HREF="#h699" >His Sufferings and Death  </A>699
<P>
SECTION V. <A HREF="#h772" >PENITENTIAL HYMNS  </A>772
<P>
<H2>Index</H2>
"""
PAGE = """<HTML><HEAD><TITLE>Hymn 488</TITLE></HEAD><BODY>
<H3>C.M.</H3>
<P>
1 O FOR a thousand tongues to sing<BR>
My great Redeemer&#146;s praise,<BR>
</BODY></HTML>"""


def test_ccel_etext_sections_and_hymns(tmp_path):
    secs = dict(hymns.ccel_sections(CONTENTS))
    assert secs[1] == "Introductory Hymns · Exhorting Sinners to return to God"
    assert secs[488] == "For the Society · Giving Thanks"  # Part V is named only through its sections
    assert secs[699] == "Supplement · The Lord Jesus Christ · His Sufferings and Death"
    assert secs[772] == "Supplement · PENITENTIAL HYMNS"  # a new section leaves the previous group
    (tmp_path / "hymn.html").write_text(CONTENTS, encoding="latin-1")
    (tmp_path / "jwg04_jwg0490.html").write_text(PAGE, encoding="latin-1")
    [h] = hymns.split_ccel(tmp_path)
    assert h["number"] == 490 and h["section"] == "For the Society · Giving Thanks"
    assert h["text"].splitlines() == ["C.M.", "1 O FOR a thousand tongues to sing", "My great Redeemer’s praise,"]  # &#146; is the Windows apostrophe
    wiki = tmp_path / "kb" / "wiki"
    (wiki / "hymns").mkdir(parents=True)
    (wiki / "hymns" / "wesley-hymns-1780.json").write_text("[]", encoding="utf-8")
    r = hymns.build_ccel(tmp_path, tmp_path / "kb")
    assert r["hymns"] == 1 and not (wiki / "hymns" / "wesley-hymns-1780.json").exists()  # replaces the OCR text
    assert "掃描" not in rag.system_addendum(wiki)
