"""Metrics and the markdown report.

pass@k  = probability that at least one of k runs passes  (the "demo" number)
pass^k  = probability that all k runs pass                (the "production" number)
Both use the unbiased estimators over n runs with c passes:
    pass@k = 1 - C(n-c, k) / C(n, k)        pass^k = C(c, k) / C(n, k)
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

from ..common import zh
from ..common.pricing import cost as usage_cost
from ..common.pricing import prompt_tokens


def pass_at_k(n: int, c: int, k: int) -> float:
    if n < k:
        raise ValueError("n < k")
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    if n < k:
        raise ValueError("n < k")
    return comb(c, k) / comb(n, k)


def run_cost(usage: dict, model: str) -> float | None:
    return usage_cost(usage, model)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return values[idx]


def read_jsonl(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def trace_metrics(t: dict, model: str) -> dict:
    """Per-run numbers the cost comparison and the report share."""
    u = t["usage_total"]
    calls = [c for s in t["steps"] for c in s["tool_calls"]]
    bad = zh.simplified_chars(t.get("model_text") or t.get("final_text") or "")  # the model's own words
    return {
        "prompt_tokens": prompt_tokens(u), "output_tokens": u.get("output_tokens", 0),
        "cache_read_tokens": u.get("cache_read_input_tokens", 0),
        "cost": run_cost(u, t.get("model") or model), "latency": t["latency_s"],
        "tool_calls": len(calls), "tool_output_chars": sum(len(c["output"]) for c in calls),
        "answer_chars": len(t.get("final_text") or ""),
        "simplified": None if bad is None else len(bad),
    }


def summarize(run_dir: str | Path, k: int | None = None) -> dict:
    run_dir = Path(run_dir)
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    traces = {(t["task_id"], t["run_index"]): t for t in read_jsonl(run_dir / "traces.jsonl")}
    grades = read_jsonl(run_dir / "grades.jsonl")
    k = k or config["n"]
    model = config["model"]
    metrics = {key: trace_metrics(t, model) for key, t in traces.items()}

    per_task: dict[str, list] = defaultdict(list)
    for g in grades:
        per_task[g["task_id"]].append(g)

    tasks_out = []
    for task_id, rows in sorted(per_task.items()):
        valid = [r for r in rows if r["status"] in ("pass", "fail")]
        c, n = sum(r["status"] == "pass" for r in valid), len(valid)
        ms = [metrics[(task_id, r["run_index"])] for r in rows if (task_id, r["run_index"]) in metrics]
        costs = [m["cost"] for m in ms]
        tasks_out.append({
            "task_id": task_id, "category": rows[0]["category"], "fault": rows[0]["fault"], "n": n, "c": c,
            "pass_rate": c / n if n else None,
            "pass_at_k": pass_at_k(n, c, k) if n >= k else None,
            "pass_hat_k": pass_hat_k(n, c, k) if n >= k else None,
            "infra_errors": sum(r["status"] == "infra_error" for r in rows),
            "grader_errors": sum(r["status"] == "grader_error" for r in rows),
            "mean_cost": statistics.mean(costs) if costs and None not in costs else None,
            "mean_latency": _mean([m["latency"] for m in ms]),
            "mean_tool_calls": _mean([m["tool_calls"] for m in ms]),
            "mean_prompt_tokens": _mean([m["prompt_tokens"] for m in ms]),
            "mean_output_tokens": _mean([m["output_tokens"] for m in ms]),
            "failures": [(r["run_index"], name, g["details"]) for r in rows if r["status"] != "pass"
                         for name, g in r["grades"].items() if not g["passed"]],
        })

    def agg(items: list[dict]) -> dict:
        scored = [t for t in items if t["pass_at_k"] is not None]
        return {
            "tasks": len(items),
            "pass_rate": _mean([t["pass_rate"] for t in items]),
            "pass_at_k": _mean([t["pass_at_k"] for t in scored]),
            "pass_hat_k": _mean([t["pass_hat_k"] for t in scored]),
        }

    all_traces = list(traces.values())
    ok = [metrics[key] for key, t in traces.items() if t["outcome"] != "api_error"]
    costs = [m["cost"] for m in metrics.values()]
    usage: dict[str, dict] = defaultdict(lambda: {"calls": 0, "errors": 0})
    kb_folders: Counter = Counter()
    for t in all_traces:
        for step in t["steps"]:
            for c in step["tool_calls"]:
                usage[c["name"]]["calls"] += 1
                usage[c["name"]]["errors"] += bool(c["is_error"])
                if c["name"] == "kb_read_file":
                    folder = c["input"].get("path", "").replace("\\", "/").lstrip("/").split("/")[0]
                    kb_folders["index" if folder == "index.md" else folder] += 1
    by_cat: dict[str, list] = defaultdict(list)
    for t in tasks_out:
        by_cat[t["category"]].append(t)
    simplified = [m["simplified"] for m in metrics.values()]
    from .human import human_summary
    return {
        "config": config, "k": k,
        "overall": agg(tasks_out),
        "no_fault": agg([t for t in tasks_out if not t["fault"]]),
        "with_fault": agg([t for t in tasks_out if t["fault"]]),
        "by_category": {c: agg(v) for c, v in sorted(by_cat.items())},
        "outcomes": dict(Counter(t["outcome"] for t in all_traces)),
        "statuses": dict(Counter(g["status"] for g in grades)),
        "latency_p50": _pct([m["latency"] for m in ok], 0.5), "latency_p95": _pct([m["latency"] for m in ok], 0.95),
        "tokens": {"mean_prompt": _mean([m["prompt_tokens"] for m in ok]),
                   "mean_output": _mean([m["output_tokens"] for m in ok]),
                   "mean_cache_read": _mean([m["cache_read_tokens"] for m in ok]),
                   "mean_tool_output_chars": _mean([m["tool_output_chars"] for m in ok])},
        "total_cost": sum(costs) if costs and None not in costs else None,
        "simplified_answers": None if None in simplified else sum(1 for s in simplified if s),
        "simplified_fixed": sum(1 for t in all_traces if t.get("simplified_fixed")),
        "tool_usage": {name: {**u, "per_run": u["calls"] / max(1, len(all_traces))}
                       for name, u in sorted(usage.items())},
        "kb_reads_by_folder": dict(kb_folders),
        "human": human_summary(run_dir),
        "tasks": tasks_out,
    }


def _f(x, pct=True) -> str:
    if x is None:
        return "–"
    return f"{100 * x:.0f}%" if pct else f"{x:.2f}"


def _n(x) -> str:
    return "–" if x is None else f"{x:,.0f}"


def render_markdown(s: dict) -> str:
    cfg, k = s["config"], s["k"]
    ts = cfg.get("toolset") or {}
    comp = ts.get("compile") or {}
    tok = s["tokens"]
    lines = [
        f"# Eval report: {cfg['model']}",
        "",
        f"- started {cfg['started']} · {len(cfg['task_ids'])} tasks × n={cfg['n']} runs · effort={cfg['effort']}",
        f"- tools: {', '.join(ts.get('tools', []))}"
        + (f" · knowledge base {ts['kb']} (wiki {ts.get('wiki_fingerprint')}; compiled by {comp.get('model')}, "
           f"language {comp.get('language')}, compile cost {_money(comp.get('cost_usd'))})" if ts.get("kb") else ""),
        f"- task set sha {cfg['tasks_sha']} · system prompt sha {cfg['system_prompt_sha']} · tools sha {cfg['tools_sha']}",
        f"- run outcomes: {s['outcomes']} · grading: {s['statuses']}",
        f"- latency per run p50 {s['latency_p50']:.1f}s · p95 {s['latency_p95']:.1f}s"
        + (f" · total cost ${s['total_cost']:.2f}" if s["total_cost"] is not None else ""),
        f"- tokens per run: prompt {_n(tok['mean_prompt'])} (cache read {_n(tok['mean_cache_read'])}) · "
        f"output {_n(tok['mean_output'])} · tool output {_n(tok['mean_tool_output_chars'])} chars",
        "- answers where the model wrote Simplified characters: "
        + ("not checked (opencc not installed)" if s["simplified_answers"] is None else str(s["simplified_answers"]))
        + (f" (converted to 繁體 before grading: {s['simplified_fixed']})" if s.get("simplified_fixed") else ""),
        "",
        f"| slice | tasks | pass rate | pass@{k} | pass^{k} |",
        "|---|---|---|---|---|",
    ]
    rows = [("all", s["overall"]), ("no fault", s["no_fault"]), ("fault injected", s["with_fault"])]
    rows += [(f"category: {c}", v) for c, v in s["by_category"].items()]
    for name, a in rows:
        lines.append(f"| {name} | {a['tasks']} | {_f(a['pass_rate'])} | {_f(a['pass_at_k'])} | {_f(a['pass_hat_k'])} |")
    lines += ["", "## Tool usage", "", "| tool | calls | per run | errors |", "|---|---|---|---|"]
    for name, u in s["tool_usage"].items():
        lines.append(f"| {name} | {u['calls']} | {u['per_run']:.1f} | {u['errors']} |")
    if s["kb_reads_by_folder"]:
        reads = ", ".join(f"{k} {v}" for k, v in sorted(s["kb_reads_by_folder"].items()))
        lines += ["", f"kb_read_file by folder: {reads} (only sources/ holds the original words)"]
    lines += [
        "",
        "## Per task",
        "",
        f"| task | category | fault | passes | pass^{k} | tool calls | prompt tok | output tok | latency | cost |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in s["tasks"]:
        cost = f"${t['mean_cost']:.4f}" if t["mean_cost"] is not None else "–"
        flags = (f" ⚠ {t['infra_errors']} infra" if t["infra_errors"] else "") + \
                (f" ⚠ {t['grader_errors']} grader" if t["grader_errors"] else "")
        lines.append(f"| {t['task_id']} | {t['category']} | {t['fault'] or ''} | {t['c']}/{t['n']}{flags} | "
                     f"{_f(t['pass_hat_k'])} | {t['mean_tool_calls']:.1f} | {_n(t['mean_prompt_tokens'])} | "
                     f"{_n(t['mean_output_tokens'])} | {t['mean_latency']:.1f}s | {cost} |")
    failures = [(t["task_id"], *f) for t in s["tasks"] for f in t["failures"]]
    if failures:
        lines += ["", "## Failures", ""]
        for task_id, run_index, grader_name, details in failures:
            lines.append(f"- `{task_id}` run {run_index} · `{grader_name}`: {details[:300]}")
    if s["human"]:
        from .human import render_human
        lines += ["", render_human(s["human"])]
    lines += [
        "",
        "## What these numbers do not say",
        "",
        "_Fill in by hand: what each grader actually checks, what it cannot see, "
        "and which biases make these numbers look better than the agent is._",
        "",
    ]
    return "\n".join(lines)


def _money(x) -> str:
    return f"${x:.2f}" if isinstance(x, (int, float)) else "–"


def write_report(run_dir: str | Path, k: int | None = None) -> Path:
    s = summarize(run_dir, k)
    path = Path(run_dir) / "report.md"
    path.write_text(render_markdown(s), encoding="utf-8")
    (Path(run_dir) / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def compare(base_dir: str | Path, new_dir: str | Path) -> str:
    """Per-task pass-rate change between two graded runs (a minimal regression check)."""
    a, b = summarize(base_dir), summarize(new_dir)

    def label(s):
        ts = s["config"].get("toolset") or {}
        return f"{s['config']['model']} tools={'+'.join(ts.get('tools', []))}" + (f" kb={ts['kb']}" if ts.get("kb") else "")
    lines = [f"base: {label(a)}\nnew:  {label(b)}\n", "| task | base | new | change |", "|---|---|---|---|"]
    ta = {t["task_id"]: t for t in a["tasks"]}
    for t in b["tasks"]:
        old = ta.get(t["task_id"])
        if old is None or old["pass_rate"] is None or t["pass_rate"] is None:
            continue
        delta = t["pass_rate"] - old["pass_rate"]
        mark = " ⬇" if delta < 0 else (" ⬆" if delta > 0 else "")
        lines.append(f"| {t['task_id']} | {old['c']}/{old['n']} | {t['c']}/{t['n']} | {delta:+.0%}{mark} |")
    lines.append("")
    for cat in sorted(set(a["by_category"]) | set(b["by_category"])):
        pa, pb = a["by_category"].get(cat, {}), b["by_category"].get(cat, {})
        lines.append(f"category {cat}: pass rate {_f(pa.get('pass_rate'))} -> {_f(pb.get('pass_rate'))}, "
                     f"pass^k {_f(pa.get('pass_hat_k'))} -> {_f(pb.get('pass_hat_k'))}")
    lines.append(f"overall pass rate {_f(a['overall']['pass_rate'])} -> {_f(b['overall']['pass_rate'])}, "
                 f"pass^k {_f(a['overall']['pass_hat_k'])} -> {_f(b['overall']['pass_hat_k'])}")
    lines.append("(token and cost differences with confidence intervals: python -m theoclaw.evals cost <run dirs>)")
    return "\n".join(lines)
