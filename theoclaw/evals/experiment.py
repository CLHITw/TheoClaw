"""Run several arms of one experiment on the same tasks, then compare them.

    python -m theoclaw.evals experiment experiments/wiki-language.yaml --dry-run
    python -m theoclaw.evals experiment experiments/wiki-language.yaml

An experiment file names the tasks, n, the query model (default: the agent role in
config/llm.yaml), and the arms; each arm may change the tool set, the knowledge base,
the model or the effort:

    name: wiki-language
    tasks: tasks/kb.example.yaml
    only: [kbx-topic-general-rules]     # optional: a subset of the task ids
    n: 3
    model: qwen3.8-max                  # optional; default: the agent role in config/llm.yaml
    arms:
      - {label: no-wiki, tools: "scripture,wesley"}
      - {label: wiki-en, tools: "scripture,kb", kb: wesley-core.en.qwen3.8-max}

Results go to runs/<name>/<timestamp>/<label>/ plus comparison.md for the whole set.
"""

from __future__ import annotations

import time
from pathlib import Path

import yaml

from ..common.paths import ROOT, RUNS_DIR
from .cost import compare_costs
from .report import write_report
from .runner import agent_role, grade_run, run_tasks
from .tasks import load_tasks


def load_experiment(path: str | Path) -> dict:
    exp = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key in ("name", "tasks", "arms"):
        if key not in exp:
            raise SystemExit(f"{path}: missing {key!r}")
    labels = [a.get("label") for a in exp["arms"]]
    if None in labels or len(set(labels)) != len(labels):
        raise SystemExit(f"{path}: every arm needs a unique label")
    tasks = Path(exp["tasks"])
    exp["tasks"] = tasks if tasks.is_absolute() else ROOT / tasks
    return exp


def plan_text(exp: dict) -> str:
    from ..agent.tools import build_tool_set
    tasks = load_tasks(exp["tasks"])
    n_tasks = len([t for t in tasks if not exp.get("only") or t.id in exp["only"]])
    n = exp.get("n", 3)
    lines = [f"experiment {exp['name']}: {n_tasks} tasks × n={n} × {len(exp['arms'])} arms "
             f"= {n_tasks * n * len(exp['arms'])} agent runs"]
    for arm in exp["arms"]:
        ts = build_tool_set(arm.get("tools"), arm.get("kb"))  # fails early if a knowledge base is missing
        comp = ts.meta.get("compile") or {}
        r = agent_role(arm.get("model", exp.get("model")), arm.get("effort", exp.get("effort")))
        lines.append(f"  {arm['label']}: model {r.model} ({r.provider.name}, effort {r.effort or '–'}) · tools "
                     f"{'+'.join(ts.groups)}" + (f" · kb {ts.meta['kb']} (compiled by {comp.get('model')}, "
                                                  f"{comp.get('language')})" if ts.meta.get("kb") else ""))
    lines.append("tip: run once with n: 1 to measure the cost of one pass before the full experiment")
    return "\n".join(lines)


def run_experiment(path: str | Path, *, workers: int = 4, only: list[str] | None = None) -> Path:
    exp = load_experiment(path)
    out = RUNS_DIR / exp["name"] / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    run_dirs = []
    for arm in exp["arms"]:
        if only and arm["label"] not in only:
            continue
        print(f"\n=== arm {arm['label']} ===")
        d = run_tasks(exp["tasks"], model=arm.get("model", exp.get("model")), n=exp.get("n", 3),
                      effort=arm.get("effort", exp.get("effort")), workers=workers,
                      label=arm["label"], tools=arm.get("tools"), kb=arm.get("kb"), run_dir=out / arm["label"],
                      max_steps=exp.get("max_steps", 12), only=exp.get("only"))
        grade_run(d)
        write_report(d)
        run_dirs.append(d)
    text = compare_costs(run_dirs)
    (out / "comparison.md").write_text(f"# Experiment {exp['name']}\n\n{text}\n", encoding="utf-8")
    print("\n" + text + f"\n\nsaved {out / 'comparison.md'}")
    return out
