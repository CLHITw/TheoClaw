import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from theoclaw.common import zh
from theoclaw.kb.compile import build, sources
from theoclaw.kb.compile.usage import UsageLog, normalize_litellm_usage

pypdf = pytest.importorskip("pypdf")


def make_pdf(path: Path, pages: int, bookmarks: list[tuple[str, int]] = ()) -> Path:
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    for title, page in bookmarks:
        w.add_outline_item(title, page - 1)
    with open(path, "wb") as f:
        w.write(f)
    return path


@pytest.fixture
def methodist(tmp_path):
    d = tmp_path / "Methodist"
    d.mkdir()
    # the Simplified spelling of 衛理公會總規則 (escaped: the source file is Simplified, our code is not)
    (d / "06_rules.md").write_text("\u536b\u7406\u516c\u4f1a\u603b\u89c4\u5219\nFirst, by doing no harm.",
                                   encoding="utf-8")
    make_pdf(d / "00_bible.pdf", 10, [("創世記", 1), ("羅馬書", 4), ("哥林多前書", 8)])
    make_pdf(d / "第五課 我信聖靈（1） 聖靈位格  成聖生活.pdf", 2)
    return d


def test_find_source_looks_in_subfolders(tmp_path):
    (tmp_path / "HK").mkdir(); (tmp_path / "Global_base").mkdir()
    (tmp_path / "HK" / "rules.md").write_text("x", encoding="utf-8")
    (tmp_path / "HK" / "same.md").write_text("x", encoding="utf-8")
    (tmp_path / "Global_base" / "same.md").write_text("y", encoding="utf-8")
    assert sources.find_source(tmp_path, "rules.md") == tmp_path / "HK" / "rules.md"
    assert sources.find_source(tmp_path, "Global_base/same.md") == tmp_path / "Global_base" / "same.md"
    with pytest.raises(FileNotFoundError, match="several files"):
        sources.find_source(tmp_path, "same.md")


def test_find_source_tolerates_spacing_and_width(methodist):
    assert sources.find_source(methodist, "第五課 我信聖靈(1) 聖靈位格 成聖生活.pdf").name.startswith("第五課")
    with pytest.raises(FileNotFoundError):
        sources.find_source(methodist, "missing.pdf")


def test_outline_and_page_slicing(methodist, tmp_path):
    entries, total = sources.pdf_outline(methodist / "00_bible.pdf")
    assert total == 10 and [e[1] for e in entries] == ["創世記", "羅馬書", "哥林多前書"]
    assert sources.outline_pages(methodist / "00_bible.pdf", "羅馬書") == [4, 5, 6, 7]
    assert sources.outline_pages(methodist / "00_bible.pdf", "哥林多前書") == [8, 9, 10]
    with pytest.raises(ValueError):
        sources.outline_pages(methodist / "00_bible.pdf", "啟示錄")
    assert sources.parse_pages("3-5,9") == [3, 4, 5, 9]
    out = tmp_path / "out"
    [inp] = sources.prepare_source({"file": "00_bible.pdf", "outline": "羅馬書", "name": "romans.pdf"}, methodist, out)
    assert inp.kind == "pdf" and inp.pages == 4 and "pages 4-7" in inp.origin
    assert len(pypdf.PdfReader(inp.path).pages) == 4


@pytest.mark.skipif(not zh.available(), reason="opencc needed")
def test_text_source_converted_to_traditional(methodist, tmp_path):
    [inp] = sources.prepare_source({"file": "06_rules.md", "s2t": True, "name": "rules.md"}, methodist, tmp_path)
    text = Path(inp.path).read_text(encoding="utf-8")
    assert text.startswith("衛理公會總規則") and not zh.simplified_chars(text)


def test_wesley_nt_notes_split_into_files(tmp_path):
    if not (sources.DATA_DIR / "wesley_nt.json").exists():
        pytest.skip("data/ not built")
    inputs = sources.prepare_source({"wesley_nt_notes": True}, tmp_path, tmp_path / "out")
    assert len(inputs) >= 27 and all(len(Path(i.path).read_text(encoding="utf-8")) <= 81_000 for i in inputs)


def write_profiles(tmp_path, methodist) -> Path:
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump({
        "source_dir": str(methodist), "defaults": {"language": "en"},
        "profiles": {"rules": {"description": "總規", "sources": [{"file": "06_rules.md", "name": "rules.md"},
                                                                  {"file": "00_bible.pdf", "pages": "1-2"}]}}},
        allow_unicode=True), encoding="utf-8")
    return path


def test_plan_names_and_validation(tmp_path, methodist, monkeypatch):
    monkeypatch.setattr(build, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    profiles = write_profiles(tmp_path, methodist)
    plan = build.make_plan("rules", profiles_file=profiles)
    assert plan.name == "rules.en.qwen3.8-max" and plan.root == tmp_path / "knowledge" / plan.name
    assert plan.model == "dashscope/qwen3.8-max"  # the compile role, in LiteLLM form for OpenKB
    assert build.make_plan("rules", model="deepseek-flash", profiles_file=profiles).model == "deepseek/deepseek-flash"
    plan = build.make_plan("rules", model="anthropic/claude-haiku-4-5", language="zh-Hant", profiles_file=profiles)
    assert plan.name == "rules.zh-Hant.claude-haiku-4-5"
    with pytest.raises(SystemExit):
        build.make_plan("nope", profiles_file=profiles)
    with pytest.raises(SystemExit):
        build.make_plan("rules", language="fr", profiles_file=profiles)


def test_usage_normalisation_dedupe_and_totals(tmp_path):
    usage = types.SimpleNamespace(prompt_tokens=1300, completion_tokens=200,
                                  cache_creation_input_tokens=1000, cache_read_input_tokens=200)
    assert normalize_litellm_usage(usage) == {"input_tokens": 100, "output_tokens": 200,
                                              "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 200}
    openai_style = {"prompt_tokens": 500, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 400}}
    assert normalize_litellm_usage(openai_style)["input_tokens"] == 100
    log = UsageLog(tmp_path / "u.jsonl")
    resp = types.SimpleNamespace(id="msg_1", usage=usage)
    t0 = datetime.now()
    log.current = "a.md"
    log.record({"model": "anthropic/claude-sonnet-5-5"}, resp, t0, t0 + timedelta(seconds=2))
    log.record({"model": "anthropic/claude-sonnet-5-5"}, resp, t0, t0)  # same call reported twice
    log.current = "b.md"
    log.record({"model": "anthropic/claude-sonnet-5-5"}, types.SimpleNamespace(id="msg_2", usage=usage))
    log.failed({"litellm_call_id": "x"})
    log.failed({"litellm_call_id": "x"})
    t = log.totals("anthropic/claude-sonnet-5-5")
    assert t["calls"] == 2 and set(t["per_input"]) == {"a.md", "b.md"} and t["failed_calls"] == 1
    one = (100 * 2 + 200 * 10 + 200 * 0.2 + 1000 * 2.5) / 1e6
    assert t["cost_usd"] == pytest.approx(2 * one)
    assert len((tmp_path / "u.jsonl").read_text().splitlines()) == 2


@pytest.fixture
def fake_openkb(monkeypatch):
    """Stand-ins for litellm and OpenKB: `add` makes two LLM calls and writes wiki pages."""
    class CustomLogger:
        pass
    litellm = types.ModuleType("litellm")
    litellm.callbacks = []
    integrations = types.ModuleType("litellm.integrations")
    custom = types.ModuleType("litellm.integrations.custom_logger")
    custom.CustomLogger = CustomLogger
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    monkeypatch.setitem(sys.modules, "litellm.integrations", integrations)
    monkeypatch.setitem(sys.modules, "litellm.integrations.custom_logger", custom)
    added = []

    class Cli:
        def main(self, args, standalone_mode=True):
            kb, path = Path(args[1]), Path(args[3])
            if path.name == "broken.md":
                raise RuntimeError("conversion failed")
            added.append(path.name)
            wiki = kb / "wiki"
            (wiki / "summaries").mkdir(parents=True, exist_ok=True)
            (wiki / "index.md").write_text("# index\n", encoding="utf-8")
            simplified = "\u536b\u7406\u516c\u4f1a"  # Simplified spelling, as a model might write it
            (wiki / "summaries" / f"{path.stem}.md").write_text(f"{simplified}\n", encoding="utf-8")
            for i in range(2):
                usage = types.SimpleNamespace(prompt_tokens=1000, completion_tokens=100,
                                              cache_creation_input_tokens=0, cache_read_input_tokens=0)
                for cb in litellm.callbacks:
                    cb.log_success_event({"model": "anthropic/claude-sonnet-5-5"},
                                         types.SimpleNamespace(id=f"{path.name}-{i}", usage=usage), None, None)

    monkeypatch.setattr(build, "_openkb", lambda: Cli())
    return added


@pytest.mark.skipif(not zh.available(), reason="opencc needed")
def test_compile_records_cost_per_input_and_converts_to_traditional(tmp_path, methodist, monkeypatch, fake_openkb):
    monkeypatch.setattr(build, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    (methodist / "broken.md").write_text("x", encoding="utf-8")
    profiles = write_profiles(tmp_path, methodist)
    cfg = yaml.safe_load(profiles.read_text(encoding="utf-8"))
    cfg["profiles"]["rules"]["sources"].append({"file": "broken.md"})
    profiles.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    plan = build.make_plan("rules", language="zh-Hant", profiles_file=profiles)
    plan.root.mkdir(parents=True)
    (plan.root / ".openkb").mkdir()  # pretend `openkb init` already ran with the same settings
    (plan.root / ".openkb" / "config.yaml").write_text(yaml.safe_dump(
        {"model": plan.model, "language": build.LANGUAGES["zh-Hant"]}, allow_unicode=True), encoding="utf-8")
    inputs = build.prepare_inputs(plan)
    m = build.compile_kb(plan, inputs)
    assert fake_openkb == ["rules.md", "00_bible.pdf"]
    assert m["calls"] == 4 and m["usage"]["input_tokens"] == 4000
    assert m["cost_usd"] == pytest.approx(4 * (1000 * 2 + 100 * 10) / 1e6)
    assert set(m["runs"][0]["per_input"]) == {"rules.md", "00_bible.pdf"}
    assert m["runs"][0]["failed_inputs"][0]["file"] == "broken.md"
    tc = m["traditional_check"]
    assert tc["pages_with_simplified"] == 2 and len(tc["converted"]) == 2
    assert not zh.simplified_chars((plan.root / "wiki" / "summaries" / "rules.md").read_text(encoding="utf-8"))
    # a second run adds to the record instead of replacing it
    m2 = build.compile_kb(plan, inputs[:1])
    assert len(m2["runs"]) == 2 and m2["calls"] == 6
    assert json.loads((plan.root / "build.json").read_text(encoding="utf-8"))["calls"] == 6


def test_existing_kb_with_other_settings_is_refused(tmp_path, methodist, monkeypatch):
    monkeypatch.setattr(build, "KNOWLEDGE_DIR", tmp_path / "knowledge")
    plan = build.make_plan("rules", profiles_file=write_profiles(tmp_path, methodist))
    (plan.root / ".openkb").mkdir(parents=True)
    (plan.root / ".openkb" / "config.yaml").write_text("model: gpt-5.4\nlanguage: en\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="initialised"):
        build.init_kb(plan)
