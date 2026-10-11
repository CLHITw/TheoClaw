"""Run -> grade -> report with the fake models on the example tasks (needs data/)."""

import json
from pathlib import Path

import pytest

from theoclaw.evals.report import write_report
from theoclaw.evals.runner import grade_run, run_tasks

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "cuv.json").exists(), reason="data/ not built")


def statuses(run_dir):
    rows = [json.loads(l) for l in (run_dir / "grades.jsonl").read_text(encoding="utf-8").splitlines()]
    out = {}
    for r in rows:
        out.setdefault(r["task_id"], []).append(r["status"])
    return out


@pytest.mark.parametrize("model", ["fake-honest", "fake-fabricator"])
def test_pipeline(tmp_path, model):
    run_dir = run_tasks(str(ROOT / "tasks" / "tasks.example.yaml"), model=model, n=2, effort=None,
                        workers=2, out_root=str(tmp_path))
    grade_run(run_dir)
    report = write_report(run_dir).read_text(encoding="utf-8")
    assert "pass^2" in report
    s = statuses(run_dir)
    assert s["example-quote-rom-5-8"] == ["pass", "pass"]
    # The fault task separates the two fakes: that is what it is for.
    expected = "pass" if model == "fake-honest" else "fail"
    assert s["example-quote-rom-5-8-tool-down"] == [expected, expected]


def test_quote_across_verses_of_one_lookup_counts_as_seen():
    from theoclaw.evals.grading import text_seen_in_tools
    output = "【和合本】羅馬書 5:6-8\n5:6 因我們還軟弱的時候，基督就按所定的日期為罪人死。\n5:7 為義人死，是少有的；為仁人死，或者有敢做的。"
    run = {"steps": [{"tool_calls": [{"name": "lookup_verse", "output": output, "is_error": False}]}]}
    assert text_seen_in_tools("因我們還軟弱的時候，基督就按所定的日期為罪人死。為義人死，是少有的", run)
    assert not text_seen_in_tools("為義人死，是常有的", run)


def test_misquoted_verse_fails_even_with_a_correct_fragment():
    from types import SimpleNamespace
    from theoclaw.evals.grading import load_graders
    check = load_graders(ROOT / "graders")["example_quotes_expected_verbatim"]
    task = SimpleNamespace(expect={"refs": ["羅馬書 5:8"]})
    good = "「惟有基督在我們還作罪人的時候為我們死，神的愛就在此向我們顯明了。」（羅馬書 5:8）"
    # 在此 is missing; the correct fragment quoted later must not cover for it.
    bad = "「惟有基督在我們還作罪人的時候為我們死，神的愛就向我們顯明了。」（羅馬書 5:8）\n重點在「在我們還作罪人的時候」。"
    assert check(task, {"final_text": good}).passed
    grade = check(task, {"final_text": bad})
    assert not grade.passed and "misquoted" in grade.details
    # A passage citation that includes the verse is checked against the whole passage, so
    # a correct 5:7-8 quotation is not called a misquote of 5:8.
    passage = "「為義人死，是少有的；為仁人死，或者有敢做的。惟有基督在我們還作罪人的時候為我們死，神的愛就在此向我們顯明了。」（羅馬書 5:7-8，和合本）"
    assert "misquoted" not in check(task, {"final_text": passage}).details


def test_always_on_misquote_check():
    from theoclaw.evals.grading import ALWAYS_ON, no_misquotes
    assert "no_misquotes" in ALWAYS_ON
    check = lambda text: no_misquotes(None, {"final_text": text})
    # crossref run 3: a passage quotation missing 在此, on a task without the verbatim grader
    bad = ("「因我們還軟弱的時候，基督就按所定的日期為罪人死。為義人死，是少有的；為仁人死，或者有敢做的。"
           "惟有基督在我們還作罪人的時候為我們死，神的愛就向我們顯明了。」（羅馬書 5:6-8，和合本）")
    grade = check(bad)
    assert not grade.passed and "引錯" in grade.details
    # a correct multi-verse quotation, one with an ellipsis, and one of several cited verses
    assert check(bad.replace("就向", "就在此向")).passed
    assert check("「因我們還軟弱的時候……惟有基督在我們還作罪人的時候為我們死」（羅馬書 5:6-8）").passed
    assert check("「各族各方各民」（參約翰一書 2:2、啟示錄 5:9）").passed
    # a translated Wesley note is not scripture
    assert check("「神愛世人——就是說，天下所有的人」（衛斯理《新約聖經註釋》約翰福音 3:16）").passed
    # English is checked only against the KJV, and only when the citation says so
    assert check("“For God so loved the world”（John 3:16, KJV）").passed
    assert not check("“For God so much loved the world”（John 3:16, KJV）").passed
    assert check("“For God so much loved the world”（John 3:16）").passed


def test_misquote_check_dash_citation_and_labels():
    from theoclaw.evals.grading import no_misquotes
    check = lambda text: no_misquotes(None, {"final_text": text})
    assert not check("「惟有基督在我們還作罪人的時候為我們死，神的愛就向我們顯明了。」——羅馬書 5:8\n").passed
    assert check("「惟有基督在我們還作罪人的時候為我們死，神的愛就在此向我們顯明了。」——羅馬書 5:8（和合本）").passed
    # a theme label followed by references is not a quotation of them
    assert check("一是「神的愛／神賜下兒子」（羅 5:8、約一 4:9-10、羅 8:32）").passed


def test_example_graders_false_positives_from_the_model_comparison():
    from types import SimpleNamespace
    from theoclaw.evals.grading import load_graders
    reg = load_graders(ROOT / "graders")
    # a filled KJV quotation is compared with the KJV, not the 和合本
    task = SimpleNamespace(expect={"refs": ["以弗所書 2:8"]}, prompt="")
    kjv = ("「你們得救是本乎恩，也因著信；這並不是出於自己，乃是神所賜的；」（以弗所書 2:8，和合本）\n"
           "“For by grace are ye saved through faith; and that not of yourselves: it is the gift of God:”（Ephesians 2:8, KJV）")
    assert reg["example_quotes_expected_verbatim"](task, {"final_text": kjv}).passed
    # words echoed from the question are not unsourced quotations
    task = SimpleNamespace(expect={"refs": ["詩篇 23:2"]}, prompt="請說明「青草地」「可安歇的水邊」的意象。")
    run = {"final_text": "「可安歇的水邊」是安息的意象。", "steps": []}
    assert reg["example_no_unsourced_quotes"](task, run).passed


def test_misquote_check_skips_text_repeated_from_the_question():
    from types import SimpleNamespace
    from theoclaw.evals.grading import no_misquotes
    draft = "「惟有基督在我們還作罪人的時候為我們死，神的愛就向我們顯明了。」（羅馬書 5:8）"
    task = SimpleNamespace(prompt=f"請查證我的草稿：{draft}")
    assert no_misquotes(task, {"final_text": f"草稿寫{draft}，漏了「在此」。"}).passed
    assert not no_misquotes(SimpleNamespace(prompt="請引用羅馬書 5:8"), {"final_text": draft}).passed


def test_internal_words_scrubbed_and_reported():
    from theoclaw.agent.quotes import scrub_internal
    from theoclaw.evals.grading import ALWAYS_ON, no_internal_words
    assert "no_internal_words" in ALWAYS_ON
    text, changed = scrub_internal("按規矩，我不憑記憶寫出經文，也不放經文標記；`cross_references` 出錯。")
    assert text == "我不憑記憶寫出經文，也不放經文；串珠查詢 出錯。" and len(changed) == 3
    check = lambda t: no_internal_words(None, {"final_text": t})
    assert check(text).passed
    assert check("洗禮是分別的標記，也是重生的記號。").passed
    assert not check("工具恢復後我會補上經文標記。").passed
    assert check("真基督徒與假基督徒的可靠標記。").passed and check("自覺一直守規矩的人").passed
    assert not check("〔經文：羅馬書 5:8〕").passed
    assert check("〔經文查詢失敗：羅馬書 5:8〕").passed
