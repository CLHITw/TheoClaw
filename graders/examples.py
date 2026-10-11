"""Example graders, to show the shape. The real graders are yours to write
(in this folder, any file name); delete or rewrite these freely."""

import re

from theoclaw.common.corpus import normalize_zh
from theoclaw.common.refs import parse_ref
from theoclaw.evals.grading import (Grade, answer_refs, grader, in_wesley_sources, is_verbatim, quotation_citations,
                                    quotation_version, quoted_spans, refs_overlap, simplified_in_answer,
                                    text_seen_in_tools)


@grader("example_quotes_expected_verbatim")
def quotes_expected_verbatim(task, run):
    """Each expected reference has at least one quotation that matches the 和合本 text,
    and every quotation of 6+ characters cited to an expected reference, as in
    「…」（羅馬書 5:8）, matches the text of the reference it cites. One correct
    fragment no longer covers a misquoted full verse elsewhere in the answer."""
    spans = quoted_spans(run["final_text"])
    expected = [parse_ref(r) for r in task.expect.get("refs", [])]
    missing = [r.zh() for r in expected if not any(is_verbatim(s, r) for s in spans)]
    misquoted = [s for s, cite, refs in quotation_citations(run["final_text"])
                 if len(s) >= 6 and (v := quotation_version(s, cite))  # English only when marked KJV
                 and any(refs_overlap(c, r) for c in refs for r in expected)
                 and not any(is_verbatim(s, c, v) for c in refs)]
    problems = ([f"no verbatim quotation for {missing}"] if missing else []) + \
               ([f"misquoted: {misquoted[:2]}"] if misquoted else [])
    return Grade(not problems, "; ".join(problems) or "ok")


@grader("example_no_unsourced_quotes")
def no_unsourced_quotes(task, run):
    """No scripture quotation may appear unless a tool returned it in this run.

    Limitation (on purpose, to show what a grader cannot see): a quotation counts as
    scripture only if it matches the gold text of a cited or expected reference, so
    a *misquoted* verse written from memory slips through here. The verbatim grader
    above is what catches misquotes.
    """
    refs = set(answer_refs(run)) | {parse_ref(r) for r in task.expect.get("refs", [])}
    scripture = [s for s in quoted_spans(run["final_text"])
                 if len(s) >= 6 and any(is_verbatim(s, r) for r in refs)]
    asked = normalize_zh(task.prompt)  # words echoed from the question, e.g. 「青草地」, are not quotations
    unsourced = [s for s in scripture if not text_seen_in_tools(s, run) and normalize_zh(s) not in asked]
    return Grade(not unsourced,
                 f"written without a tool result: {unsourced[:3]}" if unsourced
                 else f"{len(scripture)} scripture quotations, all from tool results")


@grader("example_english_quotes_in_sources")
def english_quotes_in_sources(task, run):
    """Every English quotation of 5+ words (in quotation marks, a > block quote or
    brackets) must appear word for word in the original Methodist texts this run
    could read (see grading.in_wesley_sources). A quotation copied from an OpenKB
    summary or concept page fails: those are paraphrases."""
    text = run["final_text"]
    candidates = (quoted_spans(text) + re.findall(r"(?m)^\s*>\s*(.+)$", text)
                  + re.findall(r"[\uff08(]([^\uff08\uff09()]+)[\uff09)]", text))
    spans = [s for s in candidates if len(s.split()) >= 5 and not re.search(r"[\u3400-\u9fff]", s)]
    if not spans:
        return Grade(False, "no English quotation")
    bad = [s for s in spans if not in_wesley_sources(s, run)]
    return Grade(not bad, f"not in sources: {bad[:2]}" if bad else f"{len(spans)} quotations found in sources")


@grader("example_traditional_only")
def traditional_only(task, run):
    """The answer contains no Simplified characters (needs opencc-python-reimplemented)."""
    bad = simplified_in_answer(run)
    if bad is None:
        return Grade(False, "opencc not installed, cannot check")
    return Grade(not bad, f"Simplified characters: {''.join(sorted(bad))}" if bad else "all 繁體")
