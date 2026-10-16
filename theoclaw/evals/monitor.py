"""Monitoring real questions: the answers the Bible-study group asked for and scored.

    python -m theoclaw.evals monitor runs/pastor-chat [--budget 0.5] [--out report.md]
    python -m theoclaw.evals monitor runs/pastor-chat --no-llm          # free: rule graders and scores only
    python -m theoclaw.evals monitor runs/pastor-chat --export-tasks tasks/from_chat.yaml

For every answer in the folder (traces.jsonl, written by human_scoring/human_server.py):

- automatic checks: the always-on rule graders, and groundedness against what the agent
  looked up (theoclaw.evals.ground; a model call per answer, skipped with --no-llm);
- human scores: the asker's own score and the other members' scores (0-10);
- question type: each question is put in one of the regression suite's categories, or
  "other" with a short label (a model call per batch of questions, cached).

The report answers three questions:
1. Do the automatic flags find the answers people score low (precision and recall of
   the monitor against the human verdict)?
2. Do the raters agree with each other (answers scored by two or more people)?
3. How far is the regression suite from what people ask (coverage by category)?

--export-tasks writes the low-scored or flagged answers as draft regression tasks
(prompt, category, the raters' comments as notes), to be completed by hand.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .grading import ALWAYS_ON, load_graders
from .human import load_items, load_ratings
from .judge import parse_json
from .tasks import Task, load_tasks

FAITH_MIN = 0.8        # an answer is flagged below this faithfulness ...
UNSUPPORTED_MAX = 3    # ... or with this many unsupported statements, or a failed rule grader
USABLE = 7             # a human score of 7 or more counts as usable


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def rule_checks(trace: dict) -> dict[str, bool]:
    registry = load_graders()
    task = Task(id=trace["task_id"], prompt=trace.get("prompt", ""), graders=[])
    out = {}
    for name in ALWAYS_ON:
        try:
            out[name] = bool(registry[name](task, trace).passed)
        except Exception:
            out[name] = False
    return out


def classify(chat_dir: Path, suite: Path, model: str | None = None, client=None) -> dict[str, dict]:
    """task_id -> {"category", "label"}; cached in categories-<model>.jsonl."""
    from ..llm import complete, role
    name = role("judge", model=model).model
    cache_path = chat_dir / f"categories-{name}.jsonl"
    cached = {r["task_id"]: r for r in _jsonl(cache_path)}
    todo = [it for it in load_items([chat_dir]) if it.key[0] not in cached]
    tasks = load_tasks(suite)
    cats: dict[str, list[str]] = {}
    for t in tasks:
        cats.setdefault(t.category, []).append(t.prompt[:60])
    guide = "\n".join(f"- {c}：例如「{ex[0]}」" for c, ex in cats.items())
    for i in range(0, len(todo), 20):
        batch = todo[i:i + 20]
        prompt = "\n".join(["把下面每個查經問題歸入一個類別。類別與例子：", guide,
                            "- other：都不合適時用，並給一個 2–6 字的主題標籤。", "",
                            *[f"{k}. {it.trace['prompt'][:300]}" for k, it in enumerate(batch, 1)], "",
                            '只輸出 JSON：{"items": [{"i": 1, "category": "類別", "label": "主題標籤"}]}'])
        try:
            c = complete(prompt, role="judge", model=model, client=client, max_tokens=8000)
        except Exception:
            continue
        got = {v.get("i"): v for v in (parse_json(c.text) or {}).get("items") or [] if isinstance(v, dict)}
        with open(cache_path, "a", encoding="utf-8") as f:
            for k, it in enumerate(batch, 1):
                v = got.get(k) or {}
                cat = v.get("category") if v.get("category") in cats else "other"
                rec = {"task_id": it.key[0], "category": cat, "label": str(v.get("label") or "")[:20]}
                cached[it.key[0]] = rec
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return cached


def collect(chat_dir: Path, model_name: str | None) -> list[dict]:
    ground = {r["task_id"]: r for r in _jsonl(chat_dir / f"ground-{model_name}.jsonl")} if model_name else {}
    cats = {r["task_id"]: r for r in _jsonl(chat_dir / f"categories-{model_name}.jsonl")} if model_name else {}
    ratings: dict[str, dict[str, dict]] = {}
    for r in load_ratings(chat_dir):  # the latest rating of each rater counts
        ratings.setdefault(r["task_id"], {})[r["rater"]] = r
    rows = []
    for it in load_items([chat_dir]):
        t = it.trace
        tid = t["task_id"]
        asker = t.get("asked_by", "")
        rs = ratings.get(tid, {})
        score = lambda r: (r.get("scores") or {}).get("overall")
        own = score(rs[asker]) if asker in rs else None
        others = [score(r) for name, r in rs.items() if name != asker and score(r) is not None]
        g = ground.get(tid)
        rules = rule_checks(t) if t.get("final_text") else {}
        flagged = (not all(rules.values())) if rules else False
        if g:
            flagged = flagged or (g["faithfulness"] is not None and g["faithfulness"] < FAITH_MIN) \
                or len(g["unsupported"]) >= UNSUPPORTED_MAX
        all_scores = [s for s in [own, *others] if s is not None]
        rows.append({"task_id": tid, "asker": asker, "asked_at": t.get("asked_at", ""), "prompt": t.get("prompt", ""),
                     "own": own, "others": others, "scores": all_scores,
                     "human_mean": (sum(all_scores) / len(all_scores)) if all_scores else None,
                     "comments": [r.get("comment") for r in rs.values() if r.get("comment")],
                     "rules": rules, "faithfulness": g["faithfulness"] if g else None,
                     "unsupported": g["unsupported"] if g else [], "flagged": flagged,
                     "category": (cats.get(tid) or {}).get("category"), "label": (cats.get(tid) or {}).get("label"),
                     "cost_usd": t.get("cost_usd")})
    return rows


def _pct(a, b):
    return "–" if not b else f"{a}/{b} ({a / b:.0%})"


def _corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx, my = sum(p[0] for p in pairs) / len(pairs), sum(p[1] for p in pairs) / len(pairs)
    sx = sum((p[0] - mx) ** 2 for p in pairs) ** 0.5
    sy = sum((p[1] - my) ** 2 for p in pairs) ** 0.5
    return None if not sx or not sy else sum((p[0] - mx) * (p[1] - my) for p in pairs) / (sx * sy)


def render(rows: list[dict], suite: Path) -> str:
    n = len(rows)
    scored = [r for r in rows if r["human_mean"] is not None]
    low = [r for r in scored if r["human_mean"] < USABLE]
    lines = ["# Monitoring real questions", "",
             f"{n} answers · {len({r['asker'] for r in rows})} askers · {len(scored)} scored by someone · "
             f"{sum(len(r['scores']) for r in rows)} scores in all · cost ${sum(r['cost_usd'] or 0 for r in rows):.2f}", ""]
    if scored:
        allx = [s for r in scored for s in r["scores"]]
        lines += ["## 1. Human scores", "",
                  f"- mean {sum(allx) / len(allx):.1f} / 10; usable (≥ {USABLE}) {_pct(sum(s >= USABLE for s in allx), len(allx))}",
                  f"- answers below {USABLE} on average: {len(low)}", ""]
    multi = [r for r in rows if len(r["scores"]) >= 2]
    lines += ["## 2. Do raters agree?", ""]
    if multi:
        diffs = [max(r["scores"]) - min(r["scores"]) for r in multi]
        agree = sum(len({s >= USABLE for s in r["scores"]}) == 1 for r in multi)
        lines += [f"- answers scored by two or more people: {len(multi)}",
                  f"- spread between highest and lowest score: mean {sum(diffs) / len(diffs):.1f} points",
                  f"- all raters on the same side of {USABLE} (usable or not): {_pct(agree, len(multi))}", ""]
    else:
        lines += ["- no answer has two raters yet", ""]
    lines += ["## 3. Do the automatic checks find what people score low?", "",
              f"Flag = a rule grader fails, faithfulness below {FAITH_MIN:.0%}, or {UNSUPPORTED_MAX}+ unsupported statements.", ""]
    both = [r for r in scored if r["faithfulness"] is not None or r["rules"]]
    if both:
        tp = sum(r["flagged"] and r["human_mean"] < USABLE for r in both)
        fp = sum(r["flagged"] and r["human_mean"] >= USABLE for r in both)
        fn = sum(not r["flagged"] and r["human_mean"] < USABLE for r in both)
        tn = len(both) - tp - fp - fn
        c = _corr([r["faithfulness"] for r in both], [r["human_mean"] for r in both])
        lines += ["| | people: below 7 | people: 7 or more |", "|---|---|---|",
                  f"| flagged | {tp} | {fp} |", f"| not flagged | {fn} | {tn} |", "",
                  f"- precision of the flag (flagged answers people also scored low): {_pct(tp, tp + fp)}",
                  f"- recall (low-scored answers the flag caught): {_pct(tp, tp + fn)}",
                  f"- correlation of faithfulness with the human score: {'–' if c is None else f'{c:+.2f}'}", ""]
    else:
        lines += ["- not enough scored and checked answers yet", ""]
    suite_cats: dict[str, int] = {}
    for t in load_tasks(suite):
        suite_cats[t.category] = suite_cats.get(t.category, 0) + 1
    real: dict[str, int] = {}
    for r in rows:
        if r["category"]:
            real[r["category"]] = real.get(r["category"], 0) + 1
    lines += ["## 4. Coverage: what people ask vs the regression suite", "",
              "| category | real questions | suite tasks |", "|---|---|---|"]
    for c in sorted(set(real) | set(suite_cats), key=lambda c: -real.get(c, 0)):
        lines.append(f"| {c} | {real.get(c, 0)} | {suite_cats.get(c, 0)} |")
    others = [r["label"] for r in rows if r["category"] == "other" and r["label"]]
    if others:
        lines += ["", "Topics outside the suite's categories: " + "、".join(sorted(set(others)))]
    if low:
        lines += ["", "## 5. Low-scored answers (regression-task candidates)", ""]
        for r in sorted(low, key=lambda r: r["human_mean"]):
            lines.append(f"- `{r['task_id']}` {r['human_mean']:.1f} · flagged: {'yes' if r['flagged'] else 'no'} · "
                         f"{r['prompt'][:60]}" + (f" — 「{'；'.join(r['comments'])[:120]}」" if r["comments"] else ""))
    return "\n".join(lines) + "\n"


def export_tasks(rows: list[dict], path: Path) -> int:
    import yaml
    picked = [r for r in rows if (r["human_mean"] is not None and r["human_mean"] < USABLE) or r["flagged"]]
    tasks = [{"id": f"real-{r['task_id'].removeprefix('chat-')}", "category": r["category"] or "real",
              "prompt": r["prompt"], "graders": [],
              "notes": "；".join(filter(None, [f"人工平均 {r['human_mean']:.1f}" if r["human_mean"] is not None else "",
                                              *r["comments"], *(f"沒有依據：{u}" for u in r["unsupported"][:3])])),
              "expect": {"facts": []}} for r in picked]
    header = ("# 從真實提問整理出的回歸測試草稿：補上 expect.facts（參考要點）和 graders 後，併入正式任務集。\n"
              "# Draft regression tasks from real questions: fill in expect.facts and graders, then merge.\n")
    path.write_text(header + yaml.safe_dump(tasks, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return len(tasks)


def monitor(chat_dir: str | Path, *, suite: str | Path = "tasks/tasks.yaml", model: str | None = None,
            llm: bool = True, budget_usd: float | None = None, client=None) -> tuple[str, list[dict]]:
    chat_dir, suite = Path(chat_dir), Path(suite)
    name = None
    if llm:
        from . import ground
        from ..llm import role
        name = role("judge", model=model).model
        ground.score([chat_dir], model, budget_usd=budget_usd, client=client)
        classify(chat_dir, suite, model, client=client)
    rows = collect(chat_dir, name)
    return render(rows, suite), rows
