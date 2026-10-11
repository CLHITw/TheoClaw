import json
from types import SimpleNamespace

from theoclaw.evals import decide, judge


def test_decide_non_inferiority_and_cost():
    cur = {f"t{i}": {r: {"usable": 1.0, "cost": 0.02} for r in range(5)} for i in range(10)}
    new = {f"t{i}": {r: {"usable": 1.0, "cost": 0.005} for r in range(5)} for i in range(10)}
    d = decide.decide(cur, new, {"usable": 0.05})
    assert d["verdicts"]["cost"] == "better" and d["verdicts"]["usable"] == "not worse" and d["switch"]
    worse = {f"t{i}": {r: {"usable": float(r > 2), "cost": 0.005} for r in range(5)} for i in range(10)}
    d = decide.decide(cur, worse, {"usable": 0.05})
    assert d["verdicts"]["usable"] == "worse" and not d["switch"]
    assert [k for k, _, _ in decide.sequential(cur, new, {"usable": 0.05})] == [1, 2, 3, 4, 5]


class StubClient:
    def __init__(self, text):
        self.text = text
        self.messages = self

    def create(self, **kw):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)], stop_reason="end_turn",
                               usage={"input_tokens": 100, "output_tokens": 20})


def _run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir(parents=True)
    t = {"task_id": "q1", "run_index": 0, "prompt": "請引用羅馬書 5:8", "final_text": "答案", "outcome": "completed",
         "steps": [{"tool_calls": [{"name": "lookup_verse", "input": {"reference": "羅馬書 5:8"}, "output": "經文",
                                    "is_error": False}]}]}
    (d / "traces.jsonl").write_text(json.dumps(t, ensure_ascii=False) + "\n", encoding="utf-8")
    return d


def test_judge_score_saves_a_rater(tmp_path):
    d = _run_dir(tmp_path)
    reply = '好的：{"scores": {"scripture": 5, "wesleyan": null, "honesty": 4, "helpful": 9, "language": 5}, ' \
            '"verdict": "y", "comment": "準確"}'
    out = judge.score([d], "deepseek-flash", client=StubClient(reply))
    assert out["scored"] == 1 and out["rater"] == "judge-deepseek-flash"
    rec = json.loads((d / "human" / "judge-deepseek-flash.jsonl").read_text(encoding="utf-8"))
    assert rec["verdict"] is True and rec["scores"]["helpful"] is None and rec["scores"]["honesty"] == 4
    assert judge.score([d], "deepseek-flash", client=StubClient(reply))["scored"] == 0  # already scored


def test_judge_pair_records_both_orders(tmp_path):
    a, b = _run_dir(tmp_path / "a"), _run_dir(tmp_path / "b")
    out = judge.pair(a, b, "deepseek-flash", out_dir=tmp_path, client=StubClient('{"better": "A", "reason": "x"}'))
    recs = [json.loads(x) for x in open(out["file"], encoding="utf-8")]
    assert {r["order"] for r in recs} == {"ab", "ba"}
    assert {r["winner"] for r in recs} == {"a", "b"}  # always "A" = always the first position
