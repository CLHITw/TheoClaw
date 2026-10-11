import pytest

from theoclaw.common.refs import Ref, RefError, cn_to_int, extract_refs, parse_ref


@pytest.mark.parametrize("text,expected", [
    ("約翰福音 3:16", Ref("John", 3, 16, 16)),
    ("約3:16", Ref("John", 3, 16, 16)),
    ("約翰福音三章十六節", Ref("John", 3, 16, 16)),
    ("約翰福音3章16-18節", Ref("John", 3, 16, 18)),
    ("羅 5:1-5", Ref("Rom", 5, 1, 5)),
    ("羅馬書５：８", Ref("Rom", 5, 8, 8)),
    ("約翰一書 1:9", Ref("1John", 1, 9, 9)),
    ("約壹1:9", Ref("1John", 1, 9, 9)),
    ("詩篇第一百一十九篇第一百零五節", Ref("Ps", 119, 105, 105)),
    ("John 3:16", Ref("John", 3, 16, 16)),
    ("1 Cor 13:4-7", Ref("1Cor", 13, 4, 7)),
    ("I Corinthians 13:4", Ref("1Cor", 13, 4, 4)),
    ("John.3.16", Ref("John", 3, 16, 16)),
    ("Prov.8.22-Prov.8.30", Ref("Prov", 8, 22, 30)),
])
def test_parse(text, expected):
    assert parse_ref(text) == expected


@pytest.mark.parametrize("text", ["", "約翰說", "Hezekiah 3:16", "約 3:0", "羅 5:5-1"])
def test_parse_rejects(text):
    with pytest.raises(RefError):
        parse_ref(text)


def test_cn_numbers():
    assert cn_to_int("十") == 10
    assert cn_to_int("二十三") == 23
    assert cn_to_int("一百零五") == 105
    assert cn_to_int("一百五十") == 150


def test_extract_refs_from_prose():
    text = "保羅在羅馬書 5:8 說明神的愛，也可對照約3:16；約翰說的話很重要，可以多讀。"
    assert extract_refs(text) == [Ref("Rom", 5, 8, 8), Ref("John", 3, 16, 16)]


def test_format():
    r = Ref("1Cor", 13, 4, 7)
    assert r.zh() == "哥林多前書 13:4-7"
    assert r.en() == "1 Corinthians 13:4-7"
    assert r.osis() == "1Cor.13.4-1Cor.13.7"
