"""Human scoring, cost comparison, experiments and the trace viewer, on fake-model runs."""

import csv
import json
from pathlib import Path

import pytest

from theoclaw.evals import cost, human
from theoclaw.evals.report import summarize, write_report
from theoclaw.evals.runner import grade_run, run_tasks
from theoclaw.evals.show import show

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks" / "tasks.example.yaml"
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "cuv.json").exists(), reason="data/ not built")
RUBRIC = {"sha": "test", "scale": {"min": 1, "max": 5}, "verdict": {"question": "可以用嗎？"},
          "dimensions": [{"key": "scripture", "name": "經文準確", "question": "?"},
                         {"key": "honesty", "name": "誠實", "question": "?"}]}


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = tmp_path_factory.mktemp("runs")
    dirs = {}
    for model in ("fake-honest", "fake-fabricator"):
        d = run_tasks(TASKS, model=model, n=2, effort=None, workers=2, out_root=out, label=model)
        grade_run(d)
        dirs[model] = d
    return dirs


def scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_rate_saves_skips_and_quits(runs, tmp_path):
    d = runs["fake-honest"]
    n = len(human.load_items([d]))
    # first answer: 5, n, verdict yes, comment; second: skipped; third: quit
    answers = ["5", "n", "y", "很好", "s", "q"]
    assert human.rate([d], "lorenz", rubric=RUBRIC, ask=scripted(answers), out=lambda s: None) == 1
    [r] = human.load_ratings(d)
    assert r["scores"] == {"scripture": 5, "honesty": None} and r["verdict"] is True and r["comment"] == "很好"
    # already-scored answers are not shown again
    left = []
    human.rate([d], "lorenz", rubric=RUBRIC, ask=scripted(["q"]), out=left.append)
    assert f"{n - 1} 個回答待評分" in left[0]


def test_export_import_round_trip_and_agreement(runs, tmp_path):
    d = runs["fake-fabricator"]
    sheet = human.export_csv([d], tmp_path / "sheet.csv", blind=True, rubric=RUBRIC)
    with open(sheet, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "編號" and "執行" not in rows[0]  # blind: no run or model columns
    grades = {(g["task_id"], g["run_index"]): g["status"]
              for g in map(json.loads, (d / "grades.jsonl").read_text(encoding="utf-8").splitlines())}
    key = json.loads(sheet.with_suffix(".key.json").read_text(encoding="utf-8"))["items"]
    for row in rows[1:]:
        ref = key[row[0]]
        passed = grades[(ref["task_id"], ref["run_index"])] == "pass"
        row[-4:] = ["5" if passed else "1", "3", "y" if passed else "n", ""]  # agree with the graders
    rows[1][-4] = "9"  # one invalid score is reported and skipped
    with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    assert human.import_csv(sheet, "rater-a", rubric=RUBRIC) == len(rows) - 2
    s = human.human_summary(d, rubric=RUBRIC)
    g = s["vs_graders"]
    assert g["kappa"] == pytest.approx(1.0) and g["grader_too_lenient"] == 0 and g["grader_too_strict"] == 0
    # a second rater who always says yes disagrees on the failed answers
    for item in human.load_items([d]):
        human.save_rating(item, "rater-b", {"scripture": 4, "honesty": 4}, True, "", blind=False, rubric=RUBRIC)
    s = human.human_summary(d, rubric=RUBRIC)
    assert s["raters"] == ["rater-a", "rater-b"] and s["inter_rater"][0]["n"] >= 1
    assert "Human scores" in write_report(d).read_text(encoding="utf-8")


def test_kappa():
    assert human.cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert human.cohen_kappa([True, True, False, False], [True, False, True, False]) == 0.0
    assert human.cohen_kappa([], []) is None


def test_report_has_tokens_and_traditional_check(runs):
    s = summarize(runs["fake-honest"])
    assert s["tokens"]["mean_prompt"] > 0 and s["tasks"][0]["mean_output_tokens"] is not None
    text = write_report(runs["fake-honest"]).read_text(encoding="utf-8")
    assert "tokens per run" in text and "prompt tok" in text


def test_cost_comparison(runs):
    text = cost.compare_costs([runs["fake-honest"], runs["fake-fabricator"]])
    assert "fake-fabricator" in text and "prompt tokens" in text and "[" in text
    assert "No price for fake-fabricator, fake-honest" in text  # fakes are free, so no cost table


def synthetic_arm(costs: dict[str, list[float]], compile_cost=0.0):
    return {"per_task": {t: [{"cost": c, "prompt_tokens": c * 1e6, "output_tokens": 1} for c in cs]
                         for t, cs in costs.items()}, "compile": {"cost_usd": compile_cost}}


def test_paired_change_interval():
    base = synthetic_arm({f"t{i}": [0.010, 0.012] for i in range(10)})
    dear = synthetic_arm({f"t{i}": [0.020, 0.022] for i in range(10)})
    ch = cost.paired_change(base, dear, "cost")
    assert ch["change"] == pytest.approx(10 / 11) and ch["ci"][0] > 0  # clearly dearer
    noisy = synthetic_arm({f"t{i}": [0.011 + (0.004 if i % 2 else -0.004)] for i in range(10)})
    lo, hi = cost.paired_change(base, noisy, "cost")["ci"]
    assert lo < 0 < hi  # no real difference
    assert cost.paired_change(base, synthetic_arm({"other": [1.0]}), "cost") is None


def test_break_even():
    # B costs $5 more to compile and saves $0.01 per answer: pays off after 500 questions
    assert cost.break_even(0.0, 0.03, 5.0, 0.02) == pytest.approx(500)
    assert cost.break_even(0.0, 0.02, 5.0, 0.03) is None  # dearer on both counts: never


def test_experiment_runs_arms_and_compares(tmp_path, monkeypatch):
    from theoclaw.evals import experiment
    monkeypatch.setattr(experiment, "RUNS_DIR", tmp_path)
    exp = tmp_path / "exp.yaml"
    exp.write_text(f"name: fakes\ntasks: {TASKS.as_posix()}\nn: 1\narms:\n"
                   "  - {label: honest, model: fake-honest, effort: none}\n"
                   "  - {label: fabricator, model: fake-fabricator, effort: none}\n", encoding="utf-8")
    assert "2 arms = 8 agent runs" in experiment.plan_text(experiment.load_experiment(exp))
    out = experiment.run_experiment(exp, workers=1)
    assert (out / "honest" / "report.md").exists() and "fabricator" in (out / "comparison.md").read_text(encoding="utf-8")


def test_show_prints_steps_answer_and_grades(runs):
    text = show(runs["fake-fabricator"], failed=True)
    assert "【回答】" in text and "✗" in text and "ERROR" in text  # the fault task's tool error
    assert show(runs["fake-honest"], task="no-such-task") == "no matching runs"
