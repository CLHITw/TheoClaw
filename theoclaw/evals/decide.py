"""Is there enough evidence to replace one configuration with another (a model, a prompt)?

    python -m theoclaw.evals decide runs/<current> runs/<candidate> [--rater claude]

The question is a non-inferiority one: switch if the candidate is cheaper (or faster)
and not worse on quality by more than a margin you choose in advance. For every metric
it prints the difference candidate - current with a 95% interval from a two-stage
bootstrap (tasks resampled, then the runs within each task), so both the spread
between tasks and the model's run-to-run randomness are in the interval.

Then two questions about the evidence itself:
- sequential: using only the first 1, 2, ... runs per task, when would the same
  decision have been reached? (later runs cost money; if the answer is "after 2", the
  next comparison can stop earlier)
- sample size: with T tasks x r runs drawn like the ones observed, how often does the
  rule reach a decision? (a plan for the next comparison, not a property of this one)

Quality metrics, per answer: human mean score (mean of the rubric dimensions scored),
human "usable" verdict, "clear flaw" (any dimension <= 3 or verdict no), and the rule
graders' pass. Human metrics need scores from --rater on both runs.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

from .report import read_jsonl, trace_metrics

# metric: (label, higher is better, default non-inferiority margin, unit)
METRICS = {
    "human_mean": ("human mean score (1-5)", True, 0.2, ""),
    "usable": ("human: usable as is", True, 0.05, "%"),
    "flaw": ("human: answer with a clear flaw", False, 0.05, "%"),
    "rule_pass": ("rule graders pass", True, 0.05, "%"),
    "cost": ("cost per answer (USD)", False, None, "$"),
    "latency": ("time per answer (s)", False, None, "s"),
}


def load_outcomes(run_dir: str | Path, rater: str | None) -> dict[str, dict[int, dict]]:
    """{task: {run_index: {metric: value}}} for one run directory."""
    run_dir = Path(run_dir)
    model = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["model"]
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for t in read_jsonl(run_dir / "traces.jsonl"):
        if t["outcome"] == "api_error":
            continue
        m = trace_metrics(t, model)
        out[t["task_id"]][t["run_index"]] = {"cost": m["cost"], "latency": m["latency"]}
    for g in read_jsonl(run_dir / "grades.jsonl"):
        if g["status"] in ("pass", "fail") and g["run_index"] in out.get(g["task_id"], {}):
            out[g["task_id"]][g["run_index"]]["rule_pass"] = float(g["status"] == "pass")
    if rater:
        path = run_dir / "human" / f"{rater}.jsonl"
        for r in read_jsonl(path) if path.exists() else []:
            row = out.get(r["task_id"], {}).get(r["run_index"])
            if row is None:
                continue
            scores = [v for v in r["scores"].values() if v is not None]
            if scores:
                row["human_mean"] = sum(scores) / len(scores)
            if r.get("verdict") is not None:
                row["usable"] = float(r["verdict"])
                row["flaw"] = float(not r["verdict"] or (bool(scores) and min(scores) <= 3))
    return dict(out)


def _values(outcomes, task, metric, runs=None):
    rows = outcomes.get(task, {})
    return [rows[i][metric] for i in sorted(rows) if (runs is None or i in runs)
            and rows[i].get(metric) is not None]


def _shared_tasks(a, b, metric, runs=None):
    return sorted(t for t in set(a) & set(b) if _values(a, t, metric, runs) and _values(b, t, metric, runs))


def _mean(xs):
    return sum(xs) / len(xs)


def difference(a, b, metric, runs=None, n_boot=2000, seed=0) -> dict | None:
    """Candidate (b) minus current (a): mean of per-task means, and a two-stage bootstrap
    95% interval (resample tasks, then runs within each task for each arm)."""
    tasks = _shared_tasks(a, b, metric, runs)
    if not tasks:
        return None
    va = {t: _values(a, t, metric, runs) for t in tasks}
    vb = {t: _values(b, t, metric, runs) for t in tasks}
    point = _mean([_mean(vb[t]) - _mean(va[t]) for t in tasks])
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        diffs = []
        for t in (rng.choice(tasks) for _ in tasks):
            ra = [rng.choice(va[t]) for _ in va[t]]
            rb = [rng.choice(vb[t]) for _ in vb[t]]
            diffs.append(_mean(rb) - _mean(ra))
        boots.append(_mean(diffs))
    boots.sort()
    return {"tasks": len(tasks), "answers": (sum(map(len, va.values())), sum(map(len, vb.values()))),
            "current": _mean([_mean(va[t]) for t in tasks]), "candidate": _mean([_mean(vb[t]) for t in tasks]),
            "diff": point, "ci": (boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot) - 1])}


def verdict(metric: str, d: dict | None, margin: float | None) -> str:
    """'better', 'not worse' (non-inferior within the margin), 'worse', or 'unclear'."""
    if d is None:
        return "no data"
    _, higher_better, _, _ = METRICS[metric]
    lo, hi = d["ci"] if higher_better else (-d["ci"][1], -d["ci"][0])  # oriented: positive = better
    if lo > 0:
        return "better"
    if margin is not None and lo > -margin:
        return "not worse"
    if hi < 0 and (margin is None or hi < -margin):
        return "worse"
    return "unclear"


def decide(a, b, margins: dict, runs=None, seed=0) -> dict:
    rows = {m: difference(a, b, m, runs, seed=seed) for m in METRICS}
    verdicts = {m: verdict(m, rows[m], margins.get(m)) for m in METRICS}
    quality = [m for m in ("human_mean", "usable", "flaw", "rule_pass") if rows[m] is not None]
    cheaper = verdicts["cost"] == "better" or verdicts["latency"] == "better"
    ok = cheaper and quality and all(verdicts[m] in ("better", "not worse") for m in quality)
    return {"rows": rows, "verdicts": verdicts, "switch": bool(ok), "quality_metrics": quality}


def sequential(a, b, margins: dict) -> list[tuple[int, bool, dict]]:
    """The decision using only runs 0..k-1 of every task, for k = 1..max runs."""
    n = max((len(r) for o in (a, b) for r in o.values()), default=0)
    out = []
    for k in range(1, n + 1):
        d = decide(a, b, margins, runs=set(range(k)))
        out.append((k, d["switch"], d["verdicts"]))
    return out


def sample_size(a, b, metric: str, margin: float, tasks=(27, 54, 108), runs=(1, 3, 5, 10),
                sims=400, seed=0) -> dict:
    """Share of simulated comparisons (tasks drawn from the observed ones, answers from
    each task's observed answers) in which the metric comes out non-inferior within the
    margin. Normal approximation of the interval over task differences, for speed."""
    shared = _shared_tasks(a, b, metric)
    if not shared:
        return {}
    _, higher_better, _, _ = METRICS[metric]
    rng = random.Random(seed)
    table = {}
    for T in tasks:
        for r in runs:
            hits = 0
            for _ in range(sims):
                diffs = []
                for t in (rng.choice(shared) for _ in range(T)):
                    va, vb = _values(a, t, metric), _values(b, t, metric)
                    d = _mean([rng.choice(vb) for _ in range(r)]) - _mean([rng.choice(va) for _ in range(r)])
                    diffs.append(d if higher_better else -d)
                m = _mean(diffs)
                se = statistics.pstdev(diffs) / math.sqrt(T) if T > 1 else 0.0
                hits += (m - 1.96 * se) > -margin
            table[(T, r)] = hits / sims
    return table


def _fmt(metric: str, x: float) -> str:
    unit = METRICS[metric][3]
    if unit == "%":
        return f"{x * 100:+.1f} pp" if x < 0 or x > 0 else "0.0 pp"
    if unit == "$":
        return f"{x:+.4f}"
    if unit == "s":
        return f"{x:+.1f}"
    return f"{x:+.2f}"


def _level(metric: str, x: float) -> str:
    unit = METRICS[metric][3]
    return f"{x * 100:.1f}%" if unit == "%" else f"${x:.4f}" if unit == "$" else f"{x:.1f}" if unit == "s" else f"{x:.2f}"


def render(a_dir, b_dir, rater: str | None, margins: dict | None = None) -> str:
    margins = {m: v[2] for m, v in METRICS.items()} | (margins or {})
    a, b = load_outcomes(a_dir, rater), load_outcomes(b_dir, rater)
    d = decide(a, b, margins)
    L = [f"# Decision: replace `{Path(a_dir).name}` with `{Path(b_dir).name}`?", "",
         f"Rule (fixed before looking): switch if the candidate is cheaper or faster (interval below 0) "
         f"and every quality metric is better or not worse by more than its margin. Human scores: rater `{rater}`.", "",
         "| metric | current | candidate | difference [95% interval] | margin | verdict |", "|---|---|---|---|---|---|"]
    for m, (label, _, _, _) in METRICS.items():
        r = d["rows"][m]
        if r is None:
            L.append(f"| {label} | – | – | – | – | no data |")
            continue
        mg = margins.get(m)
        mg_s = "–" if mg is None else (f"{mg * 100:.0f} pp" if METRICS[m][3] == "%" else f"{mg}")
        L.append(f"| {label} | {_level(m, r['current'])} | {_level(m, r['candidate'])} | "
                 f"{_fmt(m, r['diff'])} [{_fmt(m, r['ci'][0])}, {_fmt(m, r['ci'][1])}] | {mg_s} | {d['verdicts'][m]} |")
    r0 = next(r for r in d["rows"].values() if r)
    L += ["", f"{r0['tasks']} tasks; answers per arm {r0['answers'][0]} / {r0['answers'][1]}. "
          f"Two-stage bootstrap: tasks resampled, then runs within each task.", "",
          f"**Decision: {'switch' if d['switch'] else 'do not switch yet (not enough evidence)'}.**", ""]

    seq = sequential(a, b, margins)
    L += ["## When would the evidence have been enough?", "",
          "| runs per task used | decision | " + " | ".join(METRICS[m][0] for m in d["quality_metrics"]) + " |",
          "|---|---|" + "---|" * len(d["quality_metrics"])]
    for k, sw, v in seq:
        L.append(f"| {k} | {'switch' if sw else 'wait'} | " + " | ".join(v[m] for m in d["quality_metrics"]) + " |")
    first = next((k for k, sw, _ in seq if sw and all(s for kk, s, _ in seq if kk >= k)), None)
    L += ["", f"First number of runs from which the decision stays 'switch': {first if first else 'none'}.", ""]

    L += ["## Planning the next comparison", "",
          "Share of simulated comparisons that would show non-inferiority, if the two arms differ as they did here "
          "(tasks resampled from these ones; answers from each task's observed answers):", ""]
    for m in d["quality_metrics"]:
        tab = sample_size(a, b, m, margins[m])
        if not tab:
            continue
        T_vals, r_vals = sorted({T for T, _ in tab}), sorted({r for _, r in tab})
        L += [f"**{METRICS[m][0]}**, margin {margins[m] * 100:.0f} pp" if METRICS[m][3] == "%"
              else f"**{METRICS[m][0]}**, margin {margins[m]}", "",
              "| tasks \\ runs | " + " | ".join(str(r) for r in r_vals) + " |", "|---|" + "---|" * len(r_vals)]
        for T in T_vals:
            L.append(f"| {T} | " + " | ".join(f"{tab[(T, r)] * 100:.0f}%" for r in r_vals) + " |")
        L.append("")
    L += ["Caveats: the human metrics are only as good as the rater (one rater here unless stated); "
          "tasks are not a random sample of real questions, so the interval covers this task set, not all use."]
    return "\n".join(L)
