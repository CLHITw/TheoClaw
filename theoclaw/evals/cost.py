"""Token and cost comparison across runs that differ in one setting (wiki language,
compile model, query model, tool set), with the one-time compile cost included.

    python -m theoclaw.evals cost runs/<baseline> runs/<arm2> [runs/<arm3> ...]

For every arm against the first (the baseline), per answer:
- prompt tokens, output tokens and cost, as a relative change with a 95% bootstrap
  confidence interval over tasks (paired: the same tasks in both runs). If the
  interval contains 0%, the runs do not show a real difference.
- quality next to it (pass rate, human verdict), because a cheaper arm that answers
  worse is not cheaper per useful answer: cost per passed answer is shown too.
- total cost = compile cost + questions x cost per question, at several volumes, and
  the break-even volume where a dearer compile pays for itself through cheaper answers.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path

from .report import read_jsonl, trace_metrics

METRICS = ("prompt_tokens", "output_tokens", "cost")


def load_arm(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    ts = config.get("toolset") or {}
    per_task: dict[str, list[dict]] = defaultdict(list)
    for t in read_jsonl(run_dir / "traces.jsonl"):
        if t["outcome"] != "api_error":
            per_task[t["task_id"]].append(trace_metrics(t, config["model"]))
    grades = read_jsonl(run_dir / "grades.jsonl")
    valid = [g for g in grades if g["status"] in ("pass", "fail")]
    from .human import human_summary
    human = human_summary(run_dir)
    label = config.get("label") or ts.get("kb") or "+".join(ts.get("tools", [])) or run_dir.name
    return {
        "dir": run_dir, "label": label, "model": config["model"], "toolset": ts,
        "compile": ts.get("compile") or {}, "per_task": dict(per_task),
        "passes": sum(g["status"] == "pass" for g in valid) if valid else None, "graded": len(valid),
        "human_yes": human["verdict_yes"] if human else None,
        "human_mean": (sum(d["mean"] for d in human["dimensions"].values() if d["mean"] is not None)
                       / max(1, sum(d["mean"] is not None for d in human["dimensions"].values()))) if human else None,
    }


def _task_means(arm: dict, metric: str) -> dict[str, float]:
    out = {}
    for task, runs in arm["per_task"].items():
        vals = [r[metric] for r in runs if r[metric] is not None]
        if vals:
            out[task] = sum(vals) / len(vals)
    return out


def paired_change(base: dict, arm: dict, metric: str, n_boot: int = 2000, seed: int = 0) -> dict | None:
    """Relative change of the per-answer mean, arm vs base, over shared tasks, with a
    percentile bootstrap CI that resamples tasks (each task weighted equally)."""
    a, b = _task_means(base, metric), _task_means(arm, metric)
    tasks = sorted(set(a) & set(b))
    if not tasks:
        return None
    base_mean = sum(a[t] for t in tasks) / len(tasks)
    arm_mean = sum(b[t] for t in tasks) / len(tasks)

    def rel(sample):
        sa = sum(a[t] for t in sample)
        return (sum(b[t] for t in sample) - sa) / sa if sa else 0.0

    rng = random.Random(seed)
    boots = sorted(rel([rng.choice(tasks) for _ in tasks]) for _ in range(n_boot))
    return {"tasks": len(tasks), "base": base_mean, "arm": arm_mean, "change": rel(tasks),
            "ci": (boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1])}


def per_question_cost(arm: dict) -> float | None:
    means = _task_means(arm, "cost")
    return sum(means.values()) / len(means) if means else None


def break_even(compile_a: float, per_q_a: float, compile_b: float, per_q_b: float) -> float | None:
    """Questions after which arm B (dearer to compile, cheaper per answer) costs less in total."""
    if per_q_a == per_q_b:
        return None
    n = (compile_b - compile_a) / (per_q_a - per_q_b)
    return n if n > 0 else None


def _pct(x: float) -> str:
    return f"{100 * x:+.0f}%"


def _money(x) -> str:
    return "–" if x is None else f"${x:.4f}" if x < 1 else f"${x:.2f}"


def compare_costs(run_dirs: list[str | Path], volumes=(100, 1000, 10000)) -> str:
    arms = [load_arm(d) for d in run_dirs]
    base = arms[0]
    lines = ["## Arms", "", "| arm | query model | tools | wiki compiled by | wiki language | compile cost | "
             "cost / answer | pass rate | cost / passed answer | human: usable | human: mean |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        pq = per_question_cost(a)
        rate = a["passes"] / a["graded"] if a["graded"] else None
        per_pass = (pq / rate) if pq is not None and rate else None
        c = a["compile"]
        rate_txt = "–" if rate is None else f"{100 * rate:.0f}%"
        yes_txt = "–" if a["human_yes"] is None else f"{100 * a['human_yes']:.0f}%"
        mean_txt = "–" if a["human_mean"] is None else f"{a['human_mean']:.2f}"
        lines.append(f"| {a['label']} | {a['model']} | {'+'.join(a['toolset'].get('tools', []))} | {c.get('model') or '–'} | "
                     f"{c.get('language') or '–'} | {_money(c.get('cost_usd'))} | {_money(pq)} | "
                     f"{rate_txt} | {_money(per_pass)} | {yes_txt} | {mean_txt} |")
    lines += ["", f"## Per answer, against the baseline ({base['label']})", "",
              "| arm | tasks | prompt tokens | output tokens | cost |", "|---|---|---|---|---|"]
    for a in arms[1:]:
        cells = []
        for m in METRICS:
            ch = paired_change(base, a, m)
            if ch is None:
                cells.append("–")
                continue
            lo, hi = ch["ci"]
            clear = "" if lo <= 0 <= hi else " **"
            cells.append(f"{_pct(ch['change'])} [{_pct(lo)}, {_pct(hi)}]{clear}")
        n = (paired_change(base, a, "prompt_tokens") or {}).get("tasks", 0)
        lines.append(f"| {a['label']} | {n} | " + " | ".join(cells) + " |")
    lines += ["", "Change in the mean per answer, 95% bootstrap interval over tasks in brackets; "
              "** = the interval excludes 0, so the difference is unlikely to be noise. "
              "With few tasks the intervals are wide; that is the honest answer, not a defect."]
    pq_base = per_question_cost(base)
    unpriced = sorted({a["model"] for a in arms if per_question_cost(a) is None})
    if unpriced:
        lines += ["", f"No price for {', '.join(unpriced)} in the models table of config/llm.yaml, so no costs for those arms."]
    if pq_base is not None:
        lines += ["", "## Total cost = compile + questions × cost per answer", "",
                  "| arm | " + " | ".join(f"{v:,} questions" for v in volumes) + " | break-even vs baseline |",
                  "|---|" + "---|" * (len(volumes) + 1)]
        for a in arms:
            pq, comp = per_question_cost(a), a["compile"].get("cost_usd") or 0.0
            if pq is None:
                continue
            totals = " | ".join(_money(comp + v * pq) for v in volumes)
            be = "baseline" if a is base else break_even(base["compile"].get("cost_usd") or 0.0, pq_base, comp, pq)
            be_txt = be if isinstance(be, str) else ("never" if be is None else f"after {be:,.0f} questions")
            lines.append(f"| {a['label']} | {totals} | {be_txt} |")
    return "\n".join(lines)
