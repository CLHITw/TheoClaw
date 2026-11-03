"""Each church tradition gets its own stance and sources; Methodist stays exactly as it was."""

from theoclaw.agent import prompt, sermon, workspace
from theoclaw.agent.tools import build_tool_set
from theoclaw.common import denominations as denoms
from theoclaw.kb.query import rag, tools as kb_tools


def test_lookup_falls_back_to_methodist():
    assert denoms.get("lutheran").key == "lutheran"
    assert denoms.get("浸信會 Baptist").key == "baptist"
    for other in (None, "", "無宗派 Non-denominational", "made up"):
        assert denoms.get(other) is denoms.METHODIST
    assert len({d.kb for d in denoms.DENOMS.values()}) == 5
    assert denoms.get("長老會／改革宗 Presbyterian / Reformed").key == "reformed"


def test_methodist_texts_unchanged():
    for groups in (["scripture", "wesley"], ["scripture", "wesley", "kb", "rag"], ["scripture"]):
        assert prompt.system_prompt(groups) == prompt.system_prompt(groups, "methodist")
    assert "循道衛理傳統" in prompt.SYSTEM_PROMPT and prompt.WESLEY in prompt.SYSTEM_PROMPT
    assert kb_tools.tool_defs() is kb_tools.TOOL_DEFS and rag.tool_defs("methodist") is rag.TOOL_DEFS
    t = sermon.texts(None)
    assert t["research"] is sermon.RESEARCH_TRADITION and t["writer"] is sermon.WRITER and t["check"] is sermon.CHECK
    assert workspace.assistant_text() is workspace.ASSISTANT


def test_other_traditions_have_their_own_stance():
    for key in ("lutheran", "baptist", "anglican", "reformed"):
        d = denoms.DENOMS[key]
        text = prompt.system_prompt(["scripture", "kb", "rag"], key)
        assert f"依據聖經和{d.name}傳統" in text and f"以{d.name}傳統為主" in text
        assert prompt.WESLEY not in text and "衛斯理的話直接引英文原文" not in text
        assert d.sources in text  # quote the tradition's own texts, looked up first
        assert "衛理宗" not in kb_tools.tool_defs(key)[0]["description"]
        assert "衛理宗" not in rag.tool_defs(key)[0]["description"] and d.query_example in rag.tool_defs(key)[0]["description"]
        add = kb_tools.SYSTEM_ADDENDUM_OTHER.format(figure=d.figure, name=d.name)
        assert "課程01" not in add and "衛斯理" not in add  # the Hong Kong Methodist course rule is Methodist only
        t = sermon.texts(key)
        assert d.brief_zh in t["research"] and "循道" not in t["research"] and "衛斯理" not in t["research"]
        assert d.name in t["writer"] and "循道衛理" not in t["writer"]
        assert "Wesley" not in t["en"] and d.brief_en in t["en"] and "Wesley" not in t["de"]
        a = workspace.assistant_text(key)
        assert "衛斯理" not in a and d.cite_example in a


def test_tool_set_without_wesley_for_other_traditions():
    ts = build_tool_set("scripture", denomination="baptist")
    assert ts.meta["denomination"] == "baptist" and "wesley_note" not in ts.handlers
    assert "浸信會傳統" in ts.system
    assert workspace._tool_groups(None, "anglican").startswith("scripture") and "wesley" not in workspace._tool_groups(None, "anglican")
    assert "wesley" in workspace._tool_groups(None)


def test_long_texts_split_and_search_only(tmp_path):
    from theoclaw.kb.compile.build import estimate_cost
    from theoclaw.kb.compile.sources import prepare_source, split_text
    from theoclaw.kb.query.rag import index_wiki_sources
    text = "# Book\n\n" + "".join(f"## Chapter {i}\n\n" + ("word " * 300 + "\n\n") * 4 for i in range(1, 9))
    parts = split_text(text, 15_000)
    assert len(parts) > 1 and all(len(p) <= 15_001 for p in parts)
    assert "".join(parts).split() == text.split()  # nothing lost
    src = tmp_path / "src"
    src.mkdir()
    (src / "book.md").write_text(text, encoding="utf-8")
    (src / "sermons.txt").write_text("# Sermons\n\nfaith alone justifies\n", encoding="utf-8")
    out = tmp_path / "inputs"
    compiled = prepare_source({"file": "book.md", "split": 15_000}, src, out)
    assert len(compiled) == len(parts) and all(i.kind == "md" for i in compiled)
    assert all(open(i.path, encoding="utf-8").read().startswith("# ") for i in compiled)
    [searched] = prepare_source({"file": "sermons.txt", "search_only": True}, src, out)
    assert searched.kind == "search" and "search" in searched.path and searched.path.endswith(".md")
    rows = [{"kind": "md", "chars": 200_000}, {"kind": "search", "chars": 5_000_000},
            {"kind": "pdf", "pages": 100, "chars": 1_000_000}, {"kind": "pdf", "pages": 10, "chars": 100_000}]
    assert estimate_cost(rows, "deepseek/deepseek-flash") == 1.24 and estimate_cost(rows, "x/unknown") is None
    wiki = tmp_path / "wiki"
    (wiki / "sources").mkdir(parents=True)
    (wiki / "sources" / "a.md").write_text("grace through faith", encoding="utf-8")
    (wiki / "library").mkdir()
    (wiki / "library" / "sermons.md").write_text("faith alone justifies the sinner", encoding="utf-8")
    docs = [c.doc for c in index_wiki_sources(wiki).chunks]
    assert docs == ["a", "sermons"]
    assert "library/" in kb_tools.system_addendum(wiki, "lutheran")
