"""Run every task N times and save the traces; grade saved traces separately.

Running and grading are separate steps on purpose: you can change a grader and
re-grade yesterday's traces without paying for new model calls.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..agent.loop import effective_effort, run_agent
from ..agent.tools import DEFAULT_TOOLS, build_tool_set
from ..common.paths import RUNS_DIR
from ..llm import Provider, Role, load_llm_config, role as get_role
from .faults import FaultInjector
from .grading import ALWAYS_ON, load_graders
from .tasks import Task, load_tasks

FAKE_MODELS = {"fake-honest": "honest", "fake-fabricator": "fabricator"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def agent_role(model: str | None = None, effort: str | None = None) -> Role:
    """The agent role from config/llm.yaml with overrides; the fake models need no provider."""
    if model in FAKE_MODELS:
        return Role("agent", model, Provider("fake", api="fake"), None if effort in (None, "none") else effort)
    return get_role("agent", model=model, effort=effort)


def make_client(r: Role):
    """The real API client, or a deterministic fake model (free, for testing graders)."""
    if r.model in FAKE_MODELS:
        from .fake import FakeClient
        return FakeClient(behaviour=FAKE_MODELS[r.model])
    from ..llm import make_client as real_client
    return real_client(provider=r.provider, params=r.params)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_tasks(tasks_path: str | Path, *, model: str | None = None, n: int, effort: str | None = None, workers: int = 4,
              out_root: str | Path = RUNS_DIR, label: str = "", only: list[str] | None = None,
              max_steps: int = 12, resume: str | Path | None = None,
              tools: str | list[str] | None = None, kb: str | None = None, run_dir: str | Path | None = None) -> Path:
    """model and effort default to the agent role in config/llm.yaml; effort "none" omits it."""
    tasks = load_tasks(tasks_path)
    tool_set = build_tool_set(tools, kb)
    system = tool_set.system
    r = agent_role(model, effort)
    model = r.model
    effort = effective_effort(model, r.effort)
    if only:
        tasks = [t for t in tasks if t.id in set(only)]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if resume:
        run_dir = Path(resume)
    else:
        groups = tool_set.groups
        parts = ["+".join(groups) if groups != list(DEFAULT_TOOLS) and not kb else "", tool_set.meta.get("kb", ""), label]
        run_dir = Path(run_dir) if run_dir else Path(out_root) / (f"{stamp}_{model}" + "".join(f"_{x}" for x in parts if x))
        run_dir.mkdir(parents=True)
        shutil.copy(tasks_path, run_dir / "tasks.yaml")  # the exact task set this run used
        config = {
            "model": model, "effort": effort, "n": n, "max_steps": max_steps, "max_tokens": r.max_tokens,
            "llm": {**r.describe(), "effort": effort, "config_sha": None if model in FAKE_MODELS else load_llm_config().sha},
            "tasks_file": str(tasks_path), "tasks_sha": _sha(Path(tasks_path).read_text(encoding="utf-8")),
            "system_prompt_sha": _sha(system), "tools_sha": _sha(json.dumps(tool_set.defs, ensure_ascii=False)),
            "toolset": tool_set.meta, "label": label,
            "task_ids": [t.id for t in tasks], "started": stamp,
        }
        (run_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    traces_path = run_dir / "traces.jsonl"
    done = {(r["task_id"], r["run_index"]) for r in _read_jsonl(traces_path)}
    jobs = [(t, i) for t in tasks for i in range(n) if (t.id, i) not in done]
    client = make_client(r)
    lock = threading.Lock()

    def one(task: Task, i: int) -> dict:
        injector = FaultInjector([task.fault]) if task.fault else None
        run = run_agent(client, task.prompt, model=model, handlers=tool_set.handlers, injector=injector,
                        system=system, tools=tool_set.defs, effort=effort, max_tokens=r.max_tokens,
                        max_steps=max_steps)
        return {"task_id": task.id, "run_index": i, "toolset": tool_set.meta, **run.to_dict()}

    print(f"{len(jobs)} runs ({len(tasks)} tasks x {n}) -> {run_dir}")
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool, open(traces_path, "a", encoding="utf-8") as f:
        futures = {pool.submit(one, t, i): (t.id, i) for t, i in jobs}
        for k, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            with lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            print(f"[{k}/{len(jobs)}] {rec['task_id']}#{rec['run_index']} {rec['outcome']} "
                  f"{rec['latency_s']:.1f}s {len(rec['steps'])} steps")
    return run_dir


def grade_run(run_dir: str | Path, tasks_path: str | Path | None = None) -> Path:
    run_dir_p = Path(run_dir)
    tasks = {t.id: t for t in load_tasks(tasks_path or run_dir_p / "tasks.yaml")}
    registry = load_graders()
    unknown = {g for t in tasks.values() for g in t.graders} - set(registry)
    if unknown:
        raise SystemExit(f"graders not found in graders/: {sorted(unknown)}")
    out = []
    for rec in _read_jsonl(run_dir_p / "traces.jsonl"):
        task = tasks.get(rec["task_id"])
        if task is None:
            continue
        row = {"task_id": task.id, "run_index": rec["run_index"], "category": task.category,
               "fault": task.fault.mode if task.fault else None, "outcome": rec["outcome"], "grades": {}}
        if rec["outcome"] == "api_error":
            row["status"] = "infra_error"  # not the agent's failure; excluded from pass rates
        else:
            for name in [*task.graders, *(g for g in ALWAYS_ON if g not in task.graders)]:
                try:
                    g = registry[name](task, rec)
                    row["grades"][name] = {"passed": bool(g.passed), "details": g.details}
                except Exception as e:
                    row["grades"][name] = {"passed": False, "details": f"GRADER ERROR {type(e).__name__}: {e}",
                                           "grader_error": True}
            if any(g.get("grader_error") for g in row["grades"].values()):
                row["status"] = "grader_error"
            else:
                row["status"] = "pass" if all(g["passed"] for g in row["grades"].values()) else "fail"
        out.append(row)
    path = run_dir_p / "grades.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for row in sorted(out, key=lambda r: (r["task_id"], r["run_index"])):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"graded {len(out)} runs -> {path}")
    return path


def read_jsonl(path: Path) -> list[dict]:
    return _read_jsonl(Path(path))
