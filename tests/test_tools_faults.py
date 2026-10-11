import pytest

from theoclaw.evals.faults import FaultInjector, FaultSpec
from theoclaw.agent.tools import make_handlers
from theoclaw.common.tooling import ToolError


def test_lookup_verse(corpus):
    h = make_handlers(corpus)
    out = h["lookup_verse"]({"reference": "羅馬書 5:8-9", "version": "cuv"})
    assert out.splitlines()[0] == "【和合本】羅馬書 5:8-9"
    assert "5:8 惟有基督" in out and "5:9 現在我們" in out


def test_lookup_verse_errors(corpus):
    h = make_handlers(corpus)
    with pytest.raises(ToolError, match="經文不存在"):
        h["lookup_verse"]({"reference": "羅馬書 5:99", "version": "cuv"})
    with pytest.raises(ToolError, match="無法辨識"):
        h["lookup_verse"]({"reference": "第五福音 1:1", "version": "cuv"})


def test_wesley_and_crossrefs(corpus):
    h = make_handlers(corpus)
    assert "design of God's love" in h["wesley_note"]({"reference": "約 3:16"})
    assert "沒有註釋" in h["wesley_note"]({"reference": "約 3:17"})
    with pytest.raises(ToolError, match="新約"):
        h["wesley_note"]({"reference": "創 1:1"})
    out = h["cross_references"]({"reference": "約翰福音 3:16", "limit": 1})
    assert "羅馬書 5:8（96 票）" in out and "約翰一書" not in out


def test_fault_error_only_on_listed_calls(corpus):
    inj = FaultInjector([FaultSpec("lookup_verse", "error", calls=(2,))], corpus=corpus)
    h = inj.wrap(make_handlers(corpus))
    h["lookup_verse"]({"reference": "羅 5:8", "version": "cuv"})
    with pytest.raises(ToolError):
        h["lookup_verse"]({"reference": "羅 5:8", "version": "cuv"})
    h["lookup_verse"]({"reference": "羅 5:8", "version": "cuv"})
    assert inj.log == [{"tool": "lookup_verse", "call": 2, "mode": "error"}]


def test_fault_mislabeled_swaps_in_next_verse(corpus):
    inj = FaultInjector([FaultSpec("lookup_verse", "mislabeled")], corpus=corpus)
    out = inj.wrap(make_handlers(corpus))["lookup_verse"]({"reference": "羅 5:8", "version": "cuv"})
    assert out.splitlines()[0].endswith("羅馬書 5:8")
    assert out.splitlines()[1].startswith("5:8 現在我們")  # verse 9's text under verse 8's label


def test_fault_spec_validation():
    with pytest.raises(ValueError):
        FaultSpec.from_dict({"tool": "lookup_verse", "mode": "explode"})
    with pytest.raises(ValueError):
        FaultSpec.from_dict({"tool": "wesley_note", "mode": "mislabeled"})
    assert FaultSpec.from_dict({"tool": "wesley_note", "mode": "empty", "calls": [1]}).calls == (1,)
