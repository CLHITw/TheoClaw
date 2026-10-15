import json

import pytest

from theoclaw.common.tooling import ToolError
from theoclaw.evals import ground
from theoclaw.kb.query import rag


def test_chunks_overlap_and_cover_the_text():
    text = "".join(f"Paragraph {i}. " + "word " * 60 + "\n\n" for i in range(40))
    chunks = rag.chunk("doc", text, size=600, overlap=100)
    assert len(chunks) > 5 and all(len(c.text) <= 600 for c in chunks)
    assert [c.index for c in chunks] == list(range(1, len(chunks) + 1))
    assert "Paragraph 0." in chunks[0].text and "Paragraph 39." in chunks[-1].text


def test_bm25_ranks_the_matching_chunk_first():
    chunks = [rag.Chunk("d", 1, "love joy peace"), rag.Chunk("d", 2, "Bishop Gibson at Whitehall asked about perfection"),
              rag.Chunk("d", 3, "perfection perfection hymns")]
    idx = rag.BM25(chunks)
    assert idx.search("Gibson Whitehall")[0][1].index == 2
    assert idx.search("zzz") == []
    assert "沒有找到" in rag.search({"query": "zzz"}, idx)
    with pytest.raises(ToolError):
        rag.search({"query": ""}, idx)
    with pytest.raises(ToolError):
        rag.search({"query": "love", "k": 99}, idx)


def test_summarize_scores_claims_and_facts():
    parsed = {"claims": [{"claim": "a", "verdict": "supported"}, {"claim": "b", "verdict": "partial"},
                         {"claim": "c", "verdict": "unsupported"}, {"claim": "x", "verdict": "bogus"}],
              "facts": [{"i": 1, "in_answer": "yes", "in_context": "yes"}, {"i": 2, "in_answer": "partial", "in_context": "no"}],
              "relevance": 8}
    s = ground.summarize(parsed, 2)
    assert s["faithfulness"] == pytest.approx(0.5) and s["n_claims"] == 3 and s["unsupported"] == ["c"]
    assert s["fact_recall"] == pytest.approx(0.75) and s["context_recall"] == pytest.approx(0.5)
    assert ground.summarize({**parsed, "relevance": 11}, 2) is None
    assert ground.summarize({**parsed, "facts": parsed["facts"][:1]}, 2) is None  # a fact left out


def test_context_skips_errors_duplicates_and_cross_references():
    call = lambda n, i, o, e=False: {"name": n, "input": i, "output": o, "is_error": e}
    trace = {"steps": [{"tool_calls": [call("rag_search", {"query": "q"}, "TEXT"), call("rag_search", {"query": "q"}, "TEXT"),
                                       call("cross_references", {"reference": "x"}, "REFS"),
                                       call("lookup_verse", {"reference": "y"}, "ERR", True)]}]}
    ctx, cut = ground._context(trace)
    assert ctx.count("TEXT") == 1 and "REFS" not in ctx and "ERR" not in ctx and not cut
