"""Citation numbers survive only when this run's evidence contains them."""

from theoclaw.agent.citations import check_citations, evidence_numbers


def _steps(*outputs, pages=None):
    calls = [{"name": "kb_read_file", "input": {}, "output": o, "is_error": False} for o in outputs]
    if pages:
        calls.append({"name": "kb_get_page_content", "input": {"doc_name": "x", "pages": pages}, "output": "", "is_error": False})
    return [{"tool_calls": calls}]


WCF = "Chap. xxxi. Of Synods and Councils\n1\nFOR the better government ...\n4\nALL synods since the apostles times may err\n"


def test_evidence_numbers_reads_both_languages():
    ev = evidence_numbers(["Article XVI: Of Civil Affairs.", "Question 74. Are infants also to be baptized?",
                           "[standard-sermons 第 1059 頁 · 段落 4077]", "Q1: What is the chief end", WCF])
    assert 16 in ev["article"] and 74 in ev["question"] and 1 in ev["question"]
    assert 1059 in ev["page"] and 4077 in ev["paragraph"] and 31 in ev["chapter"]
    assert 31004 in ev["section"]


def test_unretrieved_numbers_are_dropped_and_retrieved_kept():
    steps = _steps(WCF, "Article XI: Of Confession. Private Absolution ought to be retained",
                   "[augsburg-confession 第 20 頁 · 段落 801]")
    text = ("西敏信條第三十一章第4條說議會會錯；西敏信條第三十一章第9條另有規定。"
            "《奧斯堡信條》第十一條保留私下赦罪，第二十八條則論教會權柄（段落 801；段落 2336）。"
            "The Augsburg Confession, Article XI, keeps absolution; Article IV of the Augsburg Confession teaches justification. "
            "See Q. 21 and WCF 31.4, WCF 29.7, p. 20, p. 45.")
    out, dropped = check_citations(text, "", steps)
    assert "第三十一章第4條" in out and "第三十一章第9條" not in out
    assert "第十一條" in out and "第二十八條" not in out
    assert "段落 801" in out and "2336" not in out
    assert "Article XI" in out and "Article IV" not in out and "the Augsburg Confession teaches justification" in out
    assert "Q. 21" not in out and "WCF 31.4" in out and "29.7" not in out
    assert "p. 20" in out and "p. 45" not in out
    assert set(dropped) >= {"第三十一章第9條", "第二十八條", "段落 2336", "Article IV of", "Q. 21", "p. 45"}
    assert "（段落 801）" in out  # the emptied part of the parenthesis is tidied


def test_scripture_references_are_never_touched():
    text = "羅馬書第 3 章和約翰福音第六章都講到這點；see chapter 8 of Romans and 羅馬書 5:8。"
    out, dropped = check_citations(text, "", _steps("nothing relevant"))
    assert out == text and not dropped


def test_pages_requested_count_as_read_and_prompt_counts_as_evidence():
    out, _ = check_citations("見《大要理問答》第 86 頁與第 90 頁。", "", _steps("", pages="84-89"))
    assert "第 86 頁" in out and "第 90 頁" not in out
    out, _ = check_citations("如摘要所說（西敏信條第三章）。", "【研究摘要】西敏信條第三章論神永遠的定旨", [])
    assert "第三章" in out


def test_rules_written_as_ordinals_count_as_numbered():
    rules = "First, by doing no harm ... Secondly, by doing good ... Thirdly, by attending upon all the ordinances"
    text = "**第一條：不作惡**；第二條是行善，第三條是守條例，第四條另有規定。"
    out, dropped = check_citations(text, "", _steps(rules))
    assert "第一條" in out and "第二條" in out and "第三條" in out
    assert dropped == ["第四條"]


def test_emptied_parentheses_disappear():
    out, _ = check_citations("He says so (Westminster Confession, chapter 29).", "", _steps(""))
    assert out == "He says so (Westminster Confession)."
    out, _ = check_citations("司布真這樣說（第 21 頁）。", "", _steps(""))
    assert out == "司布真這樣說。"
