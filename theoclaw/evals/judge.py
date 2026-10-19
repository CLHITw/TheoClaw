"""LLM judge: score answers with the human rubric, and measure how far to trust it.

    python -m theoclaw.evals judge score runs/<a> runs/<b> --model qwen3.8-max [--limit N]
    python -m theoclaw.evals judge pair runs/<a> runs/<b> --model qwen3.8-max
    python -m theoclaw.evals judge analyze runs/<a> runs/<b> --human claude

score    gives every answer the same view a blind human rater gets (question, tool calls
         with their outputs, answer) and saves the result as a rater named
         judge-<model>, next to the human scores, so `human report` compares them too.
pair     shows the two runs' answers to the same task and run index side by side and
         asks which is better, once in each order (position bias).
analyze  compares the judges with a human rater: agreement on the verdict, score gaps
         per run (does a judge favour its own model's answers?), and whether the judge
         rewards length beyond what the human score explains.
"""

from __future__ import annotations

import json
import math
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .human import Item, load_items, load_ratings, load_rubric, save_rating

SYSTEM = ("你是嚴謹的評審，替香港循道衛理聯合教會的查經與講道預備助手的回答評分。"
          "依照評分標準逐項打分，只根據你看到的題目、工具結果和回答，不要猜測回答來自哪個模型。"
          "工具結果是可信的資料來源：回答裡的經文若和工具結果逐字不符，或工具沒有回傳卻寫出經文，就是經文問題；"
          "說是衛斯理的話卻不見於工具回傳的註釋，就是捏造。")


def _rubric_text(rubric: dict) -> str:
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    lines = [f"評分：每項 {lo}–{hi} 分（{hi} 最好），不適用填 null。"]
    lines += [f"- {d['key']}（{d['name']}）：{d['question']}" for d in rubric["dimensions"]]
    lines.append(f"- verdict：{rubric['verdict']['question']}")
    return "\n".join(lines)


def _tools(trace: dict, width: int) -> list[str]:
    """Tool calls with their outputs. Scripture and Wesley outputs are what the answer is
    checked against, so they are shown up to `width` characters each; cutting them short
    makes the judge call a correct quotation invented."""
    lines = []
    for i, c in enumerate((c for s in trace["steps"] for c in s["tool_calls"]), 1):
        cap = 300 if c["name"] == "cross_references" else width
        out = c["output"] if len(c["output"]) <= cap else c["output"][:cap] + "……（以下省略）"
        lines.append(f"  {i}. {c['name']} {json.dumps(c['input'], ensure_ascii=False)} → "
                     f"{'錯誤：' if c['is_error'] else ''}{out}")
    return lines or ["  （沒有呼叫工具）"]


def score_prompt(item: Item, rubric: dict, tool_width: int = 3000) -> str:
    keys = ", ".join(f'"{d["key"]}": 分數' for d in rubric["dimensions"])
    return "\n".join([
        _rubric_text(rubric), "",
        "【題目】", item.trace["prompt"], "",
        "【工具呼叫與結果】", *_tools(item.trace, tool_width), "",
        "【回答】", item.trace.get("final_text") or "（沒有回答）", "",
        "只輸出一個 JSON 物件，不要其他文字：",
        f'{{"scores": {{{keys}}}, "verdict": "y 或 n", "comment": "一句繁體中文理由"}}',
    ])


def pair_prompt(first: Item, second: Item, rubric: dict, tool_width: int = 3000) -> str:
    def block(name, it):
        return [f"【回答 {name} 的工具呼叫與結果】", *_tools(it.trace, tool_width), "",
                f"【回答 {name}】", it.trace.get("final_text") or "（沒有回答）", ""]
    return "\n".join([
        "兩個助手回答了同一個題目。依照下列標準整體比較，哪一個對查經或講道預備更好？", _rubric_text(rubric), "",
        "【題目】", first.trace["prompt"], "", *block("A", first), *block("B", second),
        '只輸出一個 JSON 物件：{"better": "A" 或 "B" 或 "tie", "reason": "一句繁體中文理由"}',
    ])


def parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _call(prompt: str, model: str | None, client) -> tuple[dict | None, float | None, str]:
    from ..llm import complete
    c = complete(prompt, role="judge", model=model, system=SYSTEM, client=client)
    return parse_json(c.text), c.cost_usd, c.text


def judge_name(model: str | None) -> str:
    from ..llm import role
    return f"judge-{role('judge', model=model).model}"


def score(run_dirs, model: str | None = None, *, limit: int | None = None, workers: int = 4,
          client=None, seed: int = 0, rubric_path=None, tool_width: int = 3000, tag: str | None = None) -> dict:
    """Score answers not yet scored by this judge; saves as rater judge-<model> (plus the tag,
    so the same judge can be run twice to measure its own consistency). rubric_path selects the
    scoring standard, e.g. the live site's 0-10 rubric; with auto_min the verdict is derived
    from the score, exactly as the site derives it."""
    rubric = load_rubric(rubric_path) if rubric_path else load_rubric()
    rater = judge_name(model) + (f"-{tag}" if tag else "")
    items = load_items(run_dirs)
    done = {(Path(d).resolve(), r["task_id"], r["run_index"]) for d in run_dirs
            for r in load_ratings(Path(d)) if r["rater"] == rater}
    items = [i for i in items if (i.run_dir.resolve(), *i.key) not in done]
    random.Random(seed).shuffle(items)
    items = items[:limit] if limit else items
    keys = [d["key"] for d in rubric["dimensions"]]
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    auto = rubric["verdict"].get("auto_min")
    lock, total = threading.Lock(), {"scored": 0, "unparsed": 0, "cost": 0.0}

    total["api_errors"] = 0

    def one(item: Item):
        try:
            parsed, usd, raw = _call(score_prompt(item, rubric, tool_width), model, client)
        except Exception as e:  # one failed call (quota, timeout) must not stop the batch; rerun to fill gaps
            with lock:
                total["api_errors"] += 1
                total["last_error"] = str(e)[:200]
            return
        with lock:
            total["cost"] += usd or 0.0
            if not parsed or not isinstance(parsed.get("scores"), dict):
                total["unparsed"] += 1
                return
            scores = {}
            for k in keys:
                v = parsed["scores"].get(k)
                scores[k] = int(v) if isinstance(v, (int, float)) and lo <= v <= hi else None
            v = str(parsed.get("verdict", "")).strip().lower()
            verdict = True if v.startswith("y") else False if v.startswith("n") else None
            if auto is not None and scores.get(keys[0]) is not None:
                verdict = scores[keys[0]] >= auto  # the site derives the verdict from the score
            save_rating(item, rater, scores, verdict, str(parsed.get("comment", ""))[:300], blind=True, rubric=rubric)
            total["scored"] += 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, items))
    return {"rater": rater, **total}


def _pairs(run_a, run_b):
    a = {i.key: i for i in load_items([run_a])}
    b = {i.key: i for i in load_items([run_b])}
    return [(a[k], b[k]) for k in sorted(set(a) & set(b))]


def pair(run_a, run_b, model: str | None = None, *, limit: int | None = None, workers: int = 4,
         out_dir: str | Path = "runs/calibration", client=None) -> dict:
    """Each pair judged twice, a first and b first; one line per judgment."""
    rubric = load_rubric()
    rater = judge_name(model)
    out = Path(out_dir) / f"pairs_{Path(run_a).name}__{Path(run_b).name}__{rater}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {(r["task_id"], r["run_index"], r["order"]) for r in map(json.loads, out.read_text(encoding="utf-8").splitlines())}
    pairs = _pairs(run_a, run_b)
    random.Random(0).shuffle(pairs)  # a limit takes a random sample of pairs, each in both orders
    pairs = pairs[:limit] if limit else pairs
    jobs = [(x, y, order) for x, y in pairs for order in ("ab", "ba") if (x.key[0], x.key[1], order) not in done]
    lock, total = threading.Lock(), {"judged": 0, "unparsed": 0, "cost": 0.0}

    total["api_errors"] = 0

    def one(job):
        x, y, order = job
        first, second = (x, y) if order == "ab" else (y, x)
        try:
            parsed, usd, _ = _call(pair_prompt(first, second, rubric), model, client)
        except Exception as e:
            with lock:
                total["api_errors"] += 1
                total["last_error"] = str(e)[:200]
            return
        better = str((parsed or {}).get("better", "")).strip().upper()
        with lock:
            total["cost"] += usd or 0.0
            if better not in ("A", "B", "TIE"):
                total["unparsed"] += 1
                return
            winner = "tie" if better == "TIE" else ("a" if (better == "A") == (order == "ab") else "b")
            rec = {"task_id": x.key[0], "run_index": x.key[1], "order": order, "said": better, "winner": winner,
                   "reason": str((parsed or {}).get("reason", ""))[:200], "rater": rater}
            with open(out, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total["judged"] += 1

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    return {"file": str(out), **total}


# ---------------------------------------------------------------- analysis

def _ratings(run_dir, rater) -> dict:
    return {(r["task_id"], r["run_index"]): r for r in load_ratings(Path(run_dir)) if r["rater"] == rater}


def _mean_score(r):
    vals = [v for v in r["scores"].values() if v is not None]
    return sum(vals) / len(vals) if vals else None


def _kappa(a: list[bool], b: list[bool]) -> float | None:
    from .human import cohen_kappa
    return cohen_kappa(a, b)


def _corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else None


def analyze(run_dirs, human: str, judges: list[str] | None = None, pair_dir: str | Path = "runs/calibration") -> str:
    run_dirs = [Path(d) for d in run_dirs]
    if judges is None:
        judges = sorted({r["rater"] for d in run_dirs for r in load_ratings(d) if r["rater"].startswith("judge-")})
    L = [f"# How far to trust the LLM judges (reference rater: `{human}`)", ""]
    L += ["## Agreement with the reference rater", "",
          "| judge | run | answers | verdict agreement | kappa | judge says usable / reference | "
          "mean score: judge / reference | judge − reference |", "|---|---|---|---|---|---|---|---|"]
    lengths = {}
    for d in run_dirs:
        for it in load_items([d]):
            lengths[(d.name, *it.key)] = len(it.trace.get("final_text") or "")
    bias_rows = []
    for j in judges:
        for d in run_dirs:
            h, g = _ratings(d, human), _ratings(d, j)
            keys = [k for k in h if k in g and h[k]["verdict"] is not None and g[k]["verdict"] is not None]
            if not keys:
                continue
            hv, gv = [h[k]["verdict"] for k in keys], [g[k]["verdict"] for k in keys]
            agree = sum(x == y for x, y in zip(hv, gv)) / len(keys)
            hm = [m for k in keys if (m := _mean_score(h[k])) is not None]
            gm = [m for k in keys if (m := _mean_score(g[k])) is not None]
            kap = _kappa(hv, gv)
            L.append(f"| {j} | {d.name} | {len(keys)} | {agree * 100:.0f}% | {'–' if kap is None else f'{kap:.2f}'} | "
                     f"{sum(gv) / len(gv) * 100:.0f}% / {sum(hv) / len(hv) * 100:.0f}% | "
                     f"{sum(gm) / len(gm):.2f} / {sum(hm) / len(hm):.2f} | {sum(gm) / len(gm) - sum(hm) / len(hm):+.2f} |")
            for k in keys:
                a, b = _mean_score(g[k]), _mean_score(h[k])
                if a is not None and b is not None:
                    bias_rows.append((j, d.name, a - b, lengths.get((d.name, *k), 0)))
    L += ["", "Self-preference shows as a judge whose gap (judge − reference) is larger on its own model's run "
          "than on the other run.", ""]
    L += ["## Length", "", "Correlation between answer length and the judge's excess score (judge − reference); "
          "positive means the judge rewards length that the reference rater did not.", "",
          "| judge | answers | correlation |", "|---|---|---|"]
    for j in judges:
        rows = [(x, n) for jj, _, x, n in bias_rows if jj == j]
        c = _corr([n for _, n in rows], [x for x, _ in rows])
        L.append(f"| {j} | {len(rows)} | {'–' if c is None else f'{c:+.2f}'} |")
    files = sorted(Path(pair_dir).glob("pairs_*.jsonl")) if Path(pair_dir).exists() else []
    if files:
        L += ["", "## Pairwise comparisons, both orders", "",
              "| file | pairs judged both ways | same winner both ways | first position wins | a wins | b wins | ties |",
              "|---|---|---|---|---|---|---|"]
        for f in files:
            recs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            by = {}
            for r in recs:
                by.setdefault((r["task_id"], r["run_index"]), {})[r["order"]] = r
            both = [v for v in by.values() if "ab" in v and "ba" in v]
            same = sum(v["ab"]["winner"] == v["ba"]["winner"] for v in both)
            first = sum(r["said"] == "A" for r in recs) / len(recs) if recs else 0
            w = [r["winner"] for r in recs]
            L.append(f"| {f.stem} | {len(both)} | {same / len(both) * 100 if both else 0:.0f}% | {first * 100:.0f}% | "
                     f"{w.count('a')} | {w.count('b')} | {w.count('tie')} |")
        L += ["", "Without position bias, 'same winner both ways' is high and 'first position wins' is near 50% "
              "(apart from ties).", "",
              "Length or self-preference? Judgments split by which answer was longer:", "",
              "| file | judgments | longer answer wins | a wins when a is longer | a wins when b is longer |",
              "|---|---|---|---|---|"]
        for f in files:
            name_a, name_b = f.stem[len("pairs_"):].split("__")[:2]
            recs = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            rows = []
            for r in recs:
                la, lb = lengths.get((name_a, r["task_id"], r["run_index"])), lengths.get((name_b, r["task_id"], r["run_index"]))
                if la is None or lb is None or la == lb or r["winner"] == "tie":
                    continue
                rows.append((la > lb, r["winner"] == "a"))
            if not rows:
                continue
            longer = sum(a_longer == a_won for a_longer, a_won in rows) / len(rows)
            al = [a_won for a_longer, a_won in rows if a_longer]
            bl = [a_won for a_longer, a_won in rows if not a_longer]
            pct = lambda xs: f"{sum(xs) / len(xs) * 100:.0f}% ({len(xs)})" if xs else "–"
            L.append(f"| {f.stem} | {len(rows)} | {longer * 100:.0f}% | {pct(al)} | {pct(bl)} |")
        L += ["", "If 'a' keeps winning even when b is longer, that is preference for a's model, not for length."]
    return "\n".join(L)
