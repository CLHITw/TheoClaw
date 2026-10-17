import json

import pytest

from theoclaw.agent import reference
from theoclaw.common.tooling import ToolError


@pytest.fixture
def tiny(tmp_path, monkeypatch):
    d = tmp_path / "reference"
    d.mkdir()
    data = {"isbe": {"SAMARITANS": "Samaritans: " + "x" * 5000, "JACOB'S WELL": "the well at Sychar"},
            "easton": {"SAMARIA": "A watch-mountain."}, "smith": {"SAMARIA": "(watch mountain). A city."}}
    for name, entries in data.items():
        (d / f"{name}.json").write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(reference, "DIR", d)
    for f in (reference._load, reference._by_norm, reference._index):
        f.cache_clear()
    yield
    for f in (reference._load, reference._by_norm, reference._index):
        f.cache_clear()


def test_entry_by_headword_with_plurals_punctuation_and_parts(tiny):
    out = reference.entry({"term": "Samaritan"})
    assert "SAMARITANS" in out and "part=2" in out
    assert "x" * 100 in reference.entry({"term": "samaritans", "part": 2}) and "part=3" not in reference.entry({"term": "samaritans", "part": 2})
    both = reference.entry({"term": "Samaria"})
    assert "Easton" in both and "Smith" in both
    assert "Sychar" in reference.entry({"term": "jacobs well"})
    assert "查不到" in reference.entry({"term": "Babylon"})
    with pytest.raises(ToolError):
        reference.entry({"term": ""})


def test_search_finds_entries_without_a_headword(tiny):
    assert "JACOB'S WELL" in reference.search({"query": "well Sychar"})
    assert "沒有找到" in reference.search({"query": "zzz"})
