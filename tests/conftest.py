import json

import pytest

from theoclaw.common.corpus import Corpus


@pytest.fixture
def corpus(tmp_path):
    """A tiny corpus so tests do not need the full data/ build."""
    cuv = {
        "Rom.5.8": "惟有基督在我們還作罪人的時候為我們死，神的愛就在此向我們顯明了。",
        "Rom.5.9": "現在我們既靠着他的血稱義，就更要藉着他免去神的忿怒。",
        "John.3.16": "「神愛世人，甚至將他的獨生子賜給他們，叫一切信他的，不致滅亡，反得永生。",
        "John.3.17": "因為神差他的兒子降世，不是要定世人的罪，乃是要叫世人因他得救。",
        "Gen.1.1": "起初，神創造天地。",
    }
    kjv = {k: f"KJV {k}" for k in cuv}
    lut = {"Rom.5.8": "Darum preiset Gott seine Liebe gegen uns, daß Christus für uns gestorben ist, "
                     "da wir noch Sünder waren.",
           "John.3.16": "Also hat Gott die Welt geliebt, daß er seinen eingeborenen Sohn gab."}
    xrefs = {"John.3.16": [["Rom.5.8", 96], ["1John.4.9", 80]]}
    wesley = {"John.3.16": "Yea, and this was the very design of God's love."}
    for name, obj in [("cuv", cuv), ("kjv", kjv), ("lut", lut), ("crossrefs", xrefs), ("wesley_nt", wesley)]:
        (tmp_path / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return Corpus(tmp_path)


@pytest.fixture
def wiki_kb(tmp_path):
    """A miniature knowledge base in OpenKB's layout, with a build record."""
    root = tmp_path / "knowledge" / "mini.en.claude-sonnet-5-5"
    w = root / "wiki"
    (w / "summaries").mkdir(parents=True)
    (w / "sources").mkdir()
    (root / ".openkb").mkdir()
    (w / "index.md").write_text("## Documents\n- [[summaries/general-rules]] (short) — the three rules\n", encoding="utf-8")
    (w / "AGENTS.md").write_text("# Wiki schema\n", encoding="utf-8")
    (w / "summaries" / "general-rules.md").write_text(
        "---\nfull_text: sources/general-rules.md\n---\nWesley lists three rules (paraphrase).\n", encoding="utf-8")
    (w / "sources" / "general-rules.md").write_text(
        "First, by doing no harm, by avoiding evil of every kind.\n第一，不作惡，避免各樣的惡事。", encoding="utf-8")
    pages = [{"page": i, "content": f"sermon text page {i}"} for i in range(1, 6)]
    (w / "sources" / "sermons.json").write_text(json.dumps(pages), encoding="utf-8")
    (root / "build.json").write_text(json.dumps({
        "name": root.name, "profile": "mini", "model": "anthropic/claude-sonnet-5-5", "language": "en",
        "calls": 12, "usage": {"input_tokens": 1000, "output_tokens": 500}, "cost_usd": 0.75}), encoding="utf-8")
    (tmp_path / "secret.md").write_text("outside", encoding="utf-8")
    return root
