import json

from theoclaw.evals import monitor


def _chat(tmp_path):
    d = tmp_path / "pastor-chat"
    (d / "human").mkdir(parents=True)
    traces = [{"task_id": f"chat-{i}", "run_index": 0, "asked_by": f"查經班·{a}", "asked_at": "20261016-200000",
               "prompt": f"問題{i}", "final_text": "回答", "outcome": "completed", "steps": [], "usage_total": {},
               "cost_usd": 0.01} for i, a in enumerate(["甲", "乙", "甲"])]
    (d / "traces.jsonl").write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in traces), encoding="utf-8")
    (d / "config.json").write_text("{}", encoding="utf-8")
    ratings = [("甲", 0, 9), ("乙", 0, 8), ("乙", 1, 4), ("甲", 1, 5), ("甲", 2, 8)]
    for who, i, s in ratings:
        with open(d / "human" / f"查經班·{who}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"task_id": f"chat-{i}", "run_index": 0, "rater": f"查經班·{who}",
                                "scores": {"overall": s}, "verdict": s >= 7, "comment": "怪" if s < 7 else ""},
                               ensure_ascii=False) + "\n")
    g = [{"task_id": "chat-1", "run_index": 0, "faithfulness": 0.5, "unsupported": ["x"]},
         {"task_id": "chat-0", "run_index": 0, "faithfulness": 1.0, "unsupported": []},
         {"task_id": "chat-2", "run_index": 0, "faithfulness": 0.9, "unsupported": ["a", "b", "c"]}]
    (d / "ground-m.jsonl").write_text("\n".join(json.dumps(x) for x in g), encoding="utf-8")
    (d / "categories-m.jsonl").write_text(json.dumps({"task_id": "chat-1", "category": "other", "label": "家庭"},
                                                     ensure_ascii=False), encoding="utf-8")
    return d


def test_collect_render_and_export(tmp_path):
    d = _chat(tmp_path)
    rows = {r["task_id"]: r for r in monitor.collect(d, "m")}
    assert rows["chat-0"]["own"] == 9 and rows["chat-0"]["others"] == [8]
    assert rows["chat-1"]["flagged"] and rows["chat-1"]["human_mean"] == 4.5
    assert rows["chat-2"]["flagged"] and not rows["chat-0"]["flagged"]  # 3 unsupported statements flag it
    text = monitor.render(list(rows.values()), __import__("pathlib").Path("tasks/tasks.yaml"))
    assert "precision of the flag" in text and "1/2 (50%)" in text and "家庭" in text
    n = monitor.export_tasks(list(rows.values()), tmp_path / "draft.yaml")
    draft = (tmp_path / "draft.yaml").read_text(encoding="utf-8")
    assert n == 2 and "real-1" in draft and "怪" in draft
