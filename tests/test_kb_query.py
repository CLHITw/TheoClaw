import pytest

from theoclaw.agent.loop import run_agent
from theoclaw.agent.tools import build_tool_set, parse_tools
from theoclaw.common.tooling import ToolError
from theoclaw.common.tokens import TokenCounter, _chunks
from theoclaw.evals.fake import FakeClient, _Block, _Response, _Usage
from theoclaw.evals.grading import in_wesley_sources, kb_reads_by_folder
from theoclaw.kb.query import KnowledgeBase, tools
from theoclaw.kb.query.census import census
from theoclaw.kb.query.metrics import wiki_metrics


def test_read_file_and_pages(wiki_kb):
    h = tools.make_handlers(wiki_kb / "wiki")
    assert "three rules" in h["kb_read_file"]({"path": "index.md"})
    out = h["kb_get_page_content"]({"doc_name": "sermons", "pages": "2-3,5"})
    assert "[Page 2]" in out and "[Page 3]" in out and "[Page 5]" in out and "[Page 4]" not in out


def test_path_escape_and_missing(wiki_kb):
    h = tools.make_handlers(wiki_kb / "wiki")
    with pytest.raises(ToolError, match="超出"):
        h["kb_read_file"]({"path": "../../../secret.md"})
    with pytest.raises(ToolError, match="找不到"):
        h["kb_read_file"]({"path": "concepts/none.md"})
    with pytest.raises(ToolError):
        h["kb_get_page_content"]({"doc_name": "sermons", "pages": "1-200"})


def test_open_by_root_wiki_or_name(wiki_kb, monkeypatch):
    for ref in (wiki_kb, wiki_kb / "wiki"):
        kb = KnowledgeBase.open(ref)
        assert kb.root == wiki_kb.resolve() and kb.name == "mini.en.claude-sonnet-5-5"
        assert kb.manifest["model"] == "anthropic/claude-sonnet-5-5"
    monkeypatch.setattr("theoclaw.kb.query.kb.KNOWLEDGE_DIR", wiki_kb.parent)
    meta = KnowledgeBase.open("mini.en.claude-sonnet-5-5").meta()
    assert meta["compile"]["cost_usd"] == 0.75 and len(meta["wiki_fingerprint"]) == 12
    with pytest.raises(FileNotFoundError):
        KnowledgeBase.open(wiki_kb.parent / "nothing")


def test_tool_groups(wiki_kb, corpus):
    names = lambda ts: [d["name"] for d in ts.defs]
    exact = build_tool_set(corpus=corpus)
    assert names(exact) == ["lookup_verse", "cross_references", "wesley_note"]
    assert "lookup_verse" in exact.system and "sources/" not in exact.system
    ts = build_tool_set("kb,scripture", wiki_kb, corpus=corpus)  # order typed does not matter
    assert ts.groups == ["scripture", "kb"]
    assert names(ts) == ["lookup_verse", "cross_references", "kb_read_file", "kb_get_page_content"]
    assert "Wiki schema" in ts.system and ts.meta["compile"]["model"] == "anthropic/claude-sonnet-5-5"
    kb_only = build_tool_set("kb", wiki_kb, corpus=corpus)
    assert "lookup_verse" not in kb_only.system and "sources/" in kb_only.system
    assert len(build_tool_set("scripture,wesley,kb", wiki_kb, corpus=corpus).defs) == 5
    with pytest.raises(ValueError):
        build_tool_set("scripture,kb", corpus=corpus)  # kb without --kb
    with pytest.raises(ValueError):
        build_tool_set("scripture", wiki_kb, corpus=corpus)  # --kb without the kb group
    with pytest.raises(ValueError):
        parse_tools("scripture,bible")


def test_agent_uses_kb_tools_and_graders_check_sources(wiki_kb, corpus):
    ts = build_tool_set("scripture,kb", wiki_kb, corpus=corpus)

    class Client:
        calls = []

        @property
        def messages(self):
            return self

        def create(self, **kw):
            self.calls.append(kw)
            if len(self.calls) == 1:
                return _Response([_Block("tool_use", id="1", name="kb_read_file", input={"path": "index.md"}),
                                  _Block("tool_use", id="2", name="kb_read_file",
                                         input={"path": "sources/general-rules.md"})], "tool_use", _Usage(10, 10))
            return _Response([_Block("text", text="「by doing no harm」")], "end_turn", _Usage(10, 10))

    client = Client()
    run = run_agent(client, "q", model="m", handlers=ts.handlers, tools=ts.defs, system=ts.system)
    rec = {"toolset": ts.meta, **run.to_dict()}
    assert kb_reads_by_folder(rec) == {"index": 1, "sources": 1}
    assert in_wesley_sources("By doing no harm,", rec)
    assert in_wesley_sources("不作惡，避免各樣的惡事", rec)        # Chinese sources count too
    assert not in_wesley_sources("Wesley lists three rules", rec)  # summary text, not a source


def test_census_counts_per_folder(wiki_kb):
    rows = census(wiki_kb / "wiki", TokenCounter(FakeClient(), "m"))
    assert set(rows) == {"index", "summaries", "sources", "(top level)"}
    assert rows["sources"]["files"] == 2 and rows["sources"]["tokens"] > 0
    assert census(wiki_kb / "wiki")["index"]["tokens"] is None


def test_token_counter_chunks_and_overhead():
    counter = TokenCounter(FakeClient(), "m")
    assert counter.count("") == 0
    assert counter.count("神愛世人") == 4                  # fake: one token per CJK character
    long = "神愛世人\n" * 50_000                            # 250k characters
    parts = _chunks(long)
    assert len(parts) == 2 and all(p.endswith("\n") for p in parts) and "".join(parts) == long
    # fake tokenizer: 1 per CJK character, 1 per 4 other characters; framing subtracted per chunk
    assert counter.count(long) == 200_000 + 50_000 // 4


def test_wiki_metrics(wiki_kb):
    w = wiki_kb / "wiki"
    (w / "concepts").mkdir()
    (w / "concepts" / "perfection.md").write_text(
        "---\ntype: concept\ndescription: 基督徒的完全\n---\nSee [[summaries/general-rules]] and [[concepts/missing]].\n"
        "Loving God with all our heart.", encoding="utf-8")
    m = wiki_metrics(w, {"rules": ["doing no harm"], "plain": ["loving God with all our heart", "不作惡"]})
    assert m["pages"] == {"summaries": 1, "concepts": 1, "entities": 0}
    assert m["broken_link_rate"] == 0.5          # one of two links has no page
    assert m["index_coverage"] == 0.5            # index.md links the summary, not the concept
    assert m["frontmatter_ok"] == 0.5            # the summary has no type/description
    assert m["fact_coverage"] == pytest.approx(1 / 3) and len(m["facts_missing"]) == 2
