"""Groundedness evaluation modelled on RAGAS faithfulness and FActScore: check an answer
against what the agent actually retrieved, statement by statement, instead of asking a
rater to look things up.

A simplified implementation, not the ragas library: one model call per answer extracts
the statements and judges them together (RAGAS uses two steps), "partly supported"
scores 0.5, and statements are checked against the retrieved text rather than the whole
source (FActScore checks against the full knowledge source). Not covered: TruLens'
context relevance, and ALCE-style checks that a cited passage supports its sentence.

    python -m theoclaw.evals ground score runs/<a> runs/<b> [--model deepseek-flash]
    python -m theoclaw.evals ground report runs/<a> runs/<b> [--out file.md]

For each answer one model call (the judge role, or --model) returns:

faithfulness      share of the answer's factual statements supported by the retrieved
                  text (RAGAS faithfulness; FActScore's atomic facts): supported = 1,
                  partly = 0.5, not supported = 0. Uses only the tool outputs, never the
                  model's own knowledge.
fact recall       share of the task's reference facts (expect.facts) the answer states
                  (answer correctness against a reference, as in RAGAS answer correctness).
context recall    share of the reference facts present in the retrieved text (RAGAS
                  context recall): did retrieval find what the answer needed?
relevance         0-10, does the answer address the question (RAGAS answer relevancy,
                  TruLens' answer relevance).

Results go to runs/<dir>/ground-<model>.jsonl, one line per answer.
"""

from __future__ import annotations

import json
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .human import Item, load_items
from .judge import parse_json

CONTEXT_CHARS = 120_000   # about 30k tokens; longer retrieved text is cut and the record says so
SKIP_TOOLS = {"cross_references"}  # verse lists, not evidence for statements about the book
MAX_CLAIMS = 15
MAX_TOKENS = 16_000  # thinking models spend much of this before the JSON; 8k cut some answers off

SYSTEM = ("你是嚴謹的事實查核員。你只根據提供的【檢索到的資料】判斷，不可以用你自己的知識補充或判斷真假。"
          "資料可能是英文，回答是中文；意思相同就算有依據。")


def _context(trace: dict) -> tuple[str, bool]:
    seen, parts = set(), []
    for c in (c for s in trace["steps"] for c in s["tool_calls"]):
        if c["name"] in SKIP_TOOLS or c["is_error"] or not c["output"]:
            continue
        key = (c["name"], json.dumps(c["input"], sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"--- {c['name']} {json.dumps(c['input'], ensure_ascii=False)}\n{c['output']}")
    text = "\n\n".join(parts)
    if len(text) > CONTEXT_CHARS:
        return text[:CONTEXT_CHARS] + "\n……（以下省略）", True
    return text or "（沒有檢索到任何資料）", False


def prompt(item: Item, facts: list[str]) -> tuple[str, bool]:
    ctx, cut = _context(item.trace)
    fact_lines = [f"{i}. {f}" for i, f in enumerate(facts, 1)] or ["（沒有參考要點）"]
    text = "\n".join([
        "【題目】", item.trace["prompt"], "",
        "【檢索到的資料】（助手回答時用工具查到的全部內容）", ctx, "",
        "【回答】", item.trace.get("final_text") or "（沒有回答）", "",
        "【參考要點】（從原書整理的標準答案要點）", *fact_lines, "",
        "請做三件事：",
        f"1. 把回答拆成獨立的事實陳述（關於書的內容、衛斯理的說法、歷史、經文的陳述；不包括應用建議、"
        f"問候和段落標題），最多 {MAX_CLAIMS} 條，挑最重要的。逐條判斷能否由【檢索到的資料】支持："
        "supported（資料明確支持）、partial（部分支持或說得比資料更多）、unsupported（資料中找不到或相矛盾）。",
        "2. 對每一條參考要點判斷：in_answer（回答有沒有講到：yes / partial / no），"
        "in_context（【檢索到的資料】裡有沒有這個內容：yes / no）。",
        "3. relevance：回答切合題目的程度，0–10 分。",
        "只輸出一個 JSON 物件，不要其他文字：",
        '{"claims": [{"claim": "陳述", "verdict": "supported|partial|unsupported"}], '
        '"facts": [{"i": 1, "in_answer": "yes|partial|no", "in_context": "yes|no"}], "relevance": 0}',
    ])
    return text, cut


_CLAIM = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0}
_ANS = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def summarize(parsed: dict, n_facts: int) -> dict | None:
    claims = [c for c in parsed.get("claims") or [] if isinstance(c, dict) and c.get("verdict") in _CLAIM]
    facts = {f.get("i"): f for f in parsed.get("facts") or [] if isinstance(f, dict)}
    rel = parsed.get("relevance")
    if not isinstance(rel, (int, float)) or not 0 <= rel <= 10:
        return None
    if n_facts and len(facts) < n_facts:
        return None
    return {
        "faithfulness": (sum(_CLAIM[c["verdict"]] for c in claims) / len(claims)) if claims else None,
        "fact_recall": (sum(_ANS.get(str(facts[i].get("in_answer")), 0.0) for i in range(1, n_facts + 1)) / n_facts)
        if n_facts else None,
        "context_recall": (sum(str(facts[i].get("in_context")) == "yes" for i in range(1, n_facts + 1)) / n_facts)
        if n_facts else None,
        "relevance": float(rel),
        "n_claims": len(claims),
        "unsupported": [c.get("claim", "")[:200] for c in claims if c["verdict"] == "unsupported"],
    }


def out_file(run_dir: Path, model: str) -> Path:
    return Path(run_dir) / f"ground-{model}.jsonl"


def _load(run_dir: Path, model: str) -> list[dict]:
    p = out_file(run_dir, model)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _facts(run_dir: Path) -> dict[str, list[str]]:
    import yaml
    path = Path(run_dir) / "tasks.yaml"
    if not path.exists():  # real questions (runs/pastor-chat) have no reference facts
        return {}
    tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {t["id"]: list((t.get("expect") or {}).get("facts") or []) for t in tasks}


def score(run_dirs, model: str | None = None, *, workers: int = 4, limit: int | None = None,
          budget_usd: float | None = None, client=None) -> dict:
    from ..llm import complete, role
    name = role("judge", model=model).model
    lock = threading.Lock()
    total = {"model": name, "scored": 0, "unparsed": 0, "api_errors": 0, "cost": 0.0, "skipped_budget": 0}
    jobs = []
    for d in run_dirs:
        d = Path(d)
        done = {(r["task_id"], r["run_index"]) for r in _load(d, name)}
        facts = _facts(d)
        jobs += [(d, it, facts.get(it.key[0], [])) for it in load_items([d]) if it.key not in done]
    random.Random(0).shuffle(jobs)
    jobs = jobs[:limit] if limit else jobs

    def one(job):
        d, item, facts = job
        with lock:
            if budget_usd is not None and total["cost"] >= budget_usd:
                total["skipped_budget"] += 1
                return
        text, cut = prompt(item, facts)
        try:
            c = complete(text, role="judge", model=model, system=SYSTEM, client=client, max_tokens=MAX_TOKENS)
        except Exception as e:  # one failed call must not stop the batch; rerun to fill gaps
            with lock:
                total["api_errors"] += 1
                total["last_error"] = str(e)[:200]
            return
        parsed = parse_json(c.text)
        s = summarize(parsed, len(facts)) if parsed else None
        with lock:
            total["cost"] += c.cost_usd or 0.0
            if s is None:  # kept for inspection; the answer is retried on the next run
                total["unparsed"] += 1
                with open(Path(d) / f"ground-{name}.failed.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"task_id": item.key[0], "run_index": item.key[1], "stop_reason": c.stop_reason,
                                        "usage": c.usage, "text": c.text[-3000:]}, ensure_ascii=False) + "\n")
                return
            rec = {"task_id": item.key[0], "run_index": item.key[1], "model": name, "context_cut": cut,
                   "answer_chars": len(item.trace.get("final_text") or ""), "cost_usd": c.cost_usd, **s,
                   "claims": parsed.get("claims"), "facts": parsed.get("facts")}
            with open(out_file(d, name), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total["scored"] += 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    return total


METRICS = ("faithfulness", "fact_recall", "context_recall", "relevance")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _boot_diff(a: dict, b: dict, metric: str, reps: int = 2000, seed: int = 0):
    """Paired over tasks: per task, mean of the runs; resample tasks."""
    tasks = sorted(set(a) & set(b))
    pairs = [( _mean([r[metric] for r in a[t]]), _mean([r[metric] for r in b[t]])) for t in tasks]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if not pairs:
        return None, None, None
    point = sum(y - x for x, y in pairs) / len(pairs)
    rng = random.Random(seed)
    ds = sorted(sum(y - x for x, y in (rng.choice(pairs) for _ in pairs)) / len(pairs) for _ in range(reps))
    return point, ds[int(0.025 * reps)], ds[int(0.975 * reps) - 1]


def report(run_dirs, model: str | None = None) -> str:
    from ..llm import role
    name = role("judge", model=model).model
    arms = []
    for d in run_dirs:
        d = Path(d)
        recs = _load(d, name)
        cats = {}
        import yaml
        tasks_file = d / "tasks.yaml"  # real questions and ad-hoc runs have none
        for t in (yaml.safe_load(tasks_file.read_text(encoding="utf-8")) if tasks_file.exists() else []):
            cats[t["id"]] = t.get("category", "")
        by_task: dict[str, list[dict]] = {}
        for r in recs:
            by_task.setdefault(r["task_id"], []).append(r)
        arms.append((d.name, recs, by_task, cats))
    fmt = lambda v, pct=True: "–" if v is None else (f"{v:.0%}" if pct else f"{v:.1f}")
    lines = [f"# Groundedness (simplified, modelled on RAGAS faithfulness and FActScore), evaluator `{name}`", "",
             "| arm | answers | faithfulness | fact recall | context recall | relevance (0–10) | unsupported statements |",
             "|---|---|---|---|---|---|---|"]
    for n, recs, _, _ in arms:
        lines.append(f"| {n} | {len(recs)} | {fmt(_mean([r['faithfulness'] for r in recs]))} | "
                     f"{fmt(_mean([r['fact_recall'] for r in recs]))} | {fmt(_mean([r['context_recall'] for r in recs]))} | "
                     f"{fmt(_mean([r['relevance'] for r in recs]), False)} | {sum(len(r['unsupported']) for r in recs)} |")
    cats = sorted({c for *_, cs in arms for c in cs.values()})
    lines += ["", "By category (fact recall / faithfulness):", "",
              "| category | " + " | ".join(n for n, *_ in arms) + " |", "|---|" + "---|" * len(arms)]
    for c in cats:
        cells = []
        for _, recs, _, cs in arms:
            rs = [r for r in recs if cs.get(r["task_id"]) == c]
            cells.append(f"{fmt(_mean([r['fact_recall'] for r in rs]))} / {fmt(_mean([r['faithfulness'] for r in rs]))}")
        lines.append(f"| {c} | " + " | ".join(cells) + " |")
    if len(arms) == 2:
        (na, _, a, _), (nb, _, b, _) = arms
        lines += ["", f"Difference {nb} − {na}, paired over tasks, 95% bootstrap interval:", "",
                  "| metric | difference | 95% interval |", "|---|---|---|"]
        for m in METRICS:
            p, lo, hi = _boot_diff(a, b, m)
            pct = m != "relevance"
            f2 = (lambda v: f"{v * 100:+.1f} pp") if pct else (lambda v: f"{v:+.2f}")
            lines.append(f"| {m} | {'–' if p is None else f2(p)} | "
                         f"{'–' if p is None else f'[{f2(lo)}, {f2(hi)}]'} |")
    return "\n".join(lines) + "\n"
