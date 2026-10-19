"""Human scoring: every answer can be scored by a person against a rubric
(config/human_rubric.yaml), and the scores are compared with the automatic graders.

    python -m theoclaw.evals human rate runs/<dir> [runs/<dir2> ...] --rater lorenz [--blind]
    python -m theoclaw.evals human export runs/<dir> [...] --out sheet.csv [--blind]   (for Excel)
    python -m theoclaw.evals human import sheet.csv --rater 某某弟兄
    python -m theoclaw.evals human report runs/<dir>

Scores are stored next to the traces, one file per rater: runs/<dir>/human/<rater>.jsonl
(appended; the latest score for an answer wins). --blind hides the model, the tool set
and the task id and shuffles answers from several runs together, so a rater comparing
two configurations cannot tell which is which.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Callable

import yaml

from ..common.paths import CONFIG_DIR

RUBRIC_FILE = CONFIG_DIR / "human_rubric.yaml"


def load_rubric(path: Path | str = RUBRIC_FILE) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    rubric = yaml.safe_load(text)
    rubric["sha"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return rubric


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _safe_name(rater: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\s]+', "_", rater.strip())
    if not name:
        raise SystemExit("--rater must not be empty")
    return name


@dataclass
class Item:
    run_dir: Path
    trace: dict

    @property
    def key(self) -> tuple[str, int]:
        return self.trace["task_id"], self.trace["run_index"]

    @property
    def item_id(self) -> str:
        raw = f"{self.run_dir.resolve()}|{self.key[0]}|{self.key[1]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def load_items(run_dirs: list[str | Path]) -> list[Item]:
    items = []
    for d in run_dirs:
        d = Path(d)
        traces = _read_jsonl(d / "traces.jsonl")
        if not traces:
            raise SystemExit(f"no traces in {d}")
        items += [Item(d, t) for t in traces if t.get("outcome") != "api_error"]
    return items


def load_ratings(run_dir: Path) -> list[dict]:
    """Latest rating per (rater, task, run index)."""
    latest: dict[tuple, dict] = {}
    for path in sorted((Path(run_dir) / "human").glob("*.jsonl")):
        for r in _read_jsonl(path):
            latest[(r["rater"], r["task_id"], r["run_index"])] = r
    return list(latest.values())


FAST_MAX_S = 2.0     # a rating sooner than this after the answer appeared: too fast to have read it
SAME_STREAK = 3      # this many identical 0-10 scores in a row by one rater: likely not reading


def confidence_marks(ratings: list[dict]) -> dict[tuple, set[str]]:
    """Suspicion flags per (rater, task_id, run_index): 'too_fast' and/or 'same_streak'.
    Analysis only — the stored records are never changed or dropped."""
    def key(r: dict) -> tuple:
        return r.get("rater", ""), r.get("task_id", ""), r.get("run_index", 0)

    marks: dict[tuple, set[str]] = {}
    by_rater: dict[str, list[dict]] = defaultdict(list)
    for r in ratings:
        by_rater[r.get("rater", "")].append(r)
    for rs in by_rater.values():
        rs.sort(key=lambda r: str(r.get("rated_at", "")))
        run: list[dict] = []
        last: object = object()
        for r in rs + [None]:                      # None flushes the final run
            overall = None if r is None else (r.get("scores") or {}).get("overall")
            if r is None or overall != last:
                if len(run) >= SAME_STREAK:
                    for x in run:
                        marks.setdefault(key(x), set()).add("same_streak")
                run = []
                last = overall
            if r is not None and overall is not None:
                run.append(r)
            e = None if r is None else r.get("elapsed_s")
            if isinstance(e, (int, float)) and not isinstance(e, bool) and e < FAST_MAX_S:
                marks.setdefault(key(r), set()).add("too_fast")
    return marks


def rating_record(item: Item, rater: str, scores: dict, verdict: bool | None, comment: str, *,
                  blind: bool, rubric: dict, extra: dict | None = None) -> dict:
    """One rating as stored, in a human/<rater>.jsonl file or the online server's database."""
    return {"task_id": item.key[0], "run_index": item.key[1], "rater": rater, "scores": scores,
            "verdict": verdict, "comment": comment, "blind": blind, "rubric_sha": rubric["sha"],
            "lang": item.trace.get("lang") or "zh",  # the language the rated answer was given in
            "rated_at": time.strftime("%Y-%m-%d %H:%M:%S"), **(extra or {})}


def save_rating(item: Item, rater: str, scores: dict, verdict: bool | None, comment: str, *,
                blind: bool, rubric: dict, extra: dict | None = None) -> dict:
    rec = rating_record(item, rater, scores, verdict, comment, blind=blind, rubric=rubric, extra=extra)
    folder = item.run_dir / "human"
    folder.mkdir(exist_ok=True)
    with open(folder / f"{_safe_name(rater)}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def tool_summary(trace: dict, full: bool = False, width: int = 160) -> list[str]:
    lines = []
    calls = [c for s in trace["steps"] for c in s["tool_calls"]]
    for i, c in enumerate(calls, 1):
        out = c["output"] if full else c["output"].replace("\n", " ")[:width]
        status = "錯誤：" if c["is_error"] else ""
        lines.append(f"  {i}. {c['name']} {json.dumps(c['input'], ensure_ascii=False)} → {status}{out}")
    return lines or ["  （沒有呼叫工具）"]


def _header(item: Item, blind: bool, index: int, total: int) -> list[str]:
    lines = [f"\n{'═' * 20} 第 {index}/{total} 個回答 {'═' * 20}"]
    if not blind:
        ts = item.trace.get("toolset") or {}
        lines.append(f"{item.run_dir.name} · {item.key[0]} #{item.key[1]} · 模型 {item.trace.get('model')} · "
                     f"工具 {'+'.join(ts.get('tools', []))}" + (f" · 知識庫 {ts['kb']}" if ts.get("kb") else ""))
    lines += ["", "【問題】", item.trace["prompt"], "", "【工具呼叫】", *tool_summary(item.trace), "",
              "【回答】", item.trace.get("final_text") or f"（沒有回答：{item.trace.get('outcome')}）", ""]
    return lines


def _ask_score(dim: dict, scale: dict, ask: Callable[[str], str], out: Callable[[str], None]):
    lo, hi = scale["min"], scale["max"]
    while True:
        raw = ask(f"{dim['name']} [{lo}-{hi}，n=不適用，?=說明，s=略過此題，q=結束]：").strip().lower()
        if raw in ("q", "s"):
            return raw
        if raw == "?":
            out(f"  {dim['question']}")
            continue
        if raw == "n":
            return None
        if raw.isdigit() and lo <= int(raw) <= hi:
            return int(raw)
        out(f"  請輸入 {lo} 到 {hi} 之間的數字，或 n / s / q")


def rate(run_dirs: list[str | Path], rater: str, *, blind: bool = False, redo: bool = False,
         only: list[str] | None = None, rubric: dict | None = None,
         ask: Callable[[str], str] = input, out: Callable[[str], None] = print) -> int:
    """Interactive scoring in the terminal; returns how many answers were scored."""
    rubric = rubric or load_rubric()
    items = load_items(run_dirs)
    if only:
        items = [i for i in items if i.key[0] in set(only)]
    if not redo:
        done = {(Path(d).resolve(), r["task_id"], r["run_index"]) for d in run_dirs
                for r in load_ratings(Path(d)) if r["rater"] == rater}
        items = [i for i in items if (i.run_dir.resolve(), *i.key) not in done]
    if blind:
        random.Random(rater).shuffle(items)
    out(f"{len(items)} 個回答待評分（評分人：{rater}{'，盲評' if blind else ''}）。每題評完即存檔，可隨時輸入 q 結束。")
    scored = 0
    for n, item in enumerate(items, 1):
        out("\n".join(_header(item, blind, n, len(items))))
        scores: dict = {}
        action = None
        for dim in rubric["dimensions"]:
            value = _ask_score(dim, rubric["scale"], ask, out)
            if value in ("q", "s"):
                action = value
                break
            scores[dim["key"]] = value
        if action == "q":
            break
        if action == "s":
            continue
        verdict = None
        while verdict is None:
            raw = ask(f"{rubric['verdict']['question']} ").strip().lower()
            verdict = True if raw in ("y", "yes", "是") else False if raw in ("n", "no", "否") else None
        comment = ask("備註（可留空）：").strip()
        save_rating(item, rater, scores, verdict, comment, blind=blind, rubric=rubric)
        scored += 1
    out(f"\n已評 {scored} 個回答。")
    return scored


# ---------------------------------------------------------------- spreadsheet round trip

def calibration_sample(items: list[Item], n: int, rater: str | None = None, seed: int = 0) -> list[Item]:
    """n answers for a second rater: the same number from every run directory, spread over
    the tasks, and (when rater is given) a quarter of them answers that rater flagged
    (verdict no, or any score <= 3), so disagreements on the hard cases can be measured."""
    rng = random.Random(seed)
    by_dir: dict[Path, list[Item]] = {}
    for it in items:
        by_dir.setdefault(it.run_dir, []).append(it)
    per_dir = max(1, n // len(by_dir))
    picked: list[Item] = []
    for d, its in by_dir.items():
        flagged: set[tuple] = set()
        if rater:
            for r in load_ratings(d):
                vals = [v for v in r["scores"].values() if v is not None]
                if r["rater"] == rater and (r.get("verdict") is False or (vals and min(vals) <= 3)):
                    flagged.add((r["task_id"], r["run_index"]))
        hard = [it for it in its if it.key in flagged]
        rng.shuffle(hard)
        chosen = hard[: per_dir // 4]
        rest = [it for it in its if it not in chosen]
        rng.shuffle(rest)
        tasks_used = {it.key[0] for it in chosen}
        for it in rest:  # one answer per task first, then fill
            if len(chosen) >= per_dir:
                break
            if it.key[0] not in tasks_used:
                chosen.append(it); tasks_used.add(it.key[0])
        chosen += [it for it in rest if it not in chosen][: per_dir - len(chosen)]
        picked += chosen
    return picked


def export_csv(run_dirs: list[str | Path], out_path: str | Path, *, blind: bool = False,
               rubric: dict | None = None, sample: int | None = None, flagged_by: str | None = None) -> Path:
    """A sheet for raters who prefer Excel: one row per answer, empty score columns.
    A key file next to it maps each row back to its run (kept away from blind raters).
    sample=n exports a calibration sample instead of every answer (see calibration_sample)."""
    rubric = rubric or load_rubric()
    items = load_items(run_dirs)
    if sample:
        items = calibration_sample(items, sample, flagged_by)
    if blind:
        random.Random(str(out_path)).shuffle(items)
    out_path = Path(out_path)
    dims = rubric["dimensions"]
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    head = ["編號"] + ([] if blind else ["執行", "任務", "第幾次", "模型"]) + ["問題", "工具呼叫", "回答"]
    head += [f"{d['name']}（{lo}-{hi}，n=不適用）" for d in dims] + ["總評（y/n）", "備註"]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel reads the Chinese
        w = csv.writer(f)
        w.writerow(head)
        for it in items:
            meta = [] if blind else [it.run_dir.name, it.key[0], it.key[1], it.trace.get("model")]
            w.writerow([it.item_id, *meta, it.trace["prompt"], "\n".join(tool_summary(it.trace, width=300)),
                        it.trace.get("final_text") or ""] + [""] * (len(dims) + 2))
    key = {"rubric_sha": rubric["sha"], "dimensions": [d["key"] for d in dims], "blind": blind,
           "items": {it.item_id: {"run_dir": str(it.run_dir.resolve()), "task_id": it.key[0], "run_index": it.key[1]}
                     for it in items}}
    out_path.with_suffix(".key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def import_csv(sheet: str | Path, rater: str, rubric: dict | None = None) -> int:
    rubric = rubric or load_rubric()
    sheet = Path(sheet)
    key = json.loads(sheet.with_suffix(".key.json").read_text(encoding="utf-8"))
    if key["rubric_sha"] != rubric["sha"]:
        print("warning: the rubric changed since this sheet was exported")
    dims = key["dimensions"]
    lo, hi = rubric["scale"]["min"], rubric["scale"]["max"]
    imported, problems = 0, []
    with open(sheet, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    for lineno, row in enumerate(rows[1:], 2):
        if not row or not row[0].strip():
            continue
        ref = key["items"].get(row[0].strip())
        if ref is None:
            problems.append(f"row {lineno}: unknown id {row[0]!r}")
            continue
        tail = row[-(len(dims) + 2):]
        raw_scores, raw_verdict, comment = tail[:len(dims)], tail[-2].strip().lower(), tail[-1].strip()
        if not any(x.strip() for x in raw_scores) and not raw_verdict:
            continue  # not scored yet
        scores, ok = {}, True
        for dim, raw in zip(dims, raw_scores):
            raw = raw.strip().lower()
            if raw in ("", "n"):
                scores[dim] = None
            elif raw.isdigit() and lo <= int(raw) <= hi:
                scores[dim] = int(raw)
            else:
                problems.append(f"row {lineno}: {dim}={raw!r} is not {lo}-{hi} or n")
                ok = False
        verdict = True if raw_verdict in ("y", "yes", "是") else False if raw_verdict in ("n", "no", "否") else None
        if not ok:
            continue
        item = Item(Path(ref["run_dir"]), {"task_id": ref["task_id"], "run_index": ref["run_index"]})
        save_rating(item, rater, scores, verdict, comment, blind=key["blind"], rubric=rubric)
        imported += 1
    for p in problems:
        print(p)
    return imported


# ---------------------------------------------------------------- agreement and summary

def cohen_kappa(a: list[bool], b: list[bool]) -> float | None:
    """Agreement between two yes/no label lists beyond chance (1 = perfect, 0 = chance)."""
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else (po - pe) / (1 - pe)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def human_summary(run_dir: str | Path, rubric: dict | None = None) -> dict | None:
    run_dir = Path(run_dir)
    ratings = load_ratings(run_dir)
    if not ratings:
        return None
    try:
        rubric = rubric or load_rubric()
        names = {d["key"]: d["name"] for d in rubric["dimensions"]}
    except FileNotFoundError:
        names = {}
    dims = sorted({k for r in ratings for k in r["scores"]}, key=lambda k: list(names).index(k) if k in names else 99)
    grades = {(g["task_id"], g["run_index"]): g for g in _read_jsonl(run_dir / "grades.jsonl")}
    n_traces = len(_read_jsonl(run_dir / "traces.jsonl"))

    def overall(r):
        return _mean(list(r["scores"].values()))

    per_task: dict[str, list] = defaultdict(list)
    for r in ratings:
        per_task[r["task_id"]].append(r)
    summary = {
        "raters": sorted({r["rater"] for r in ratings}), "ratings": len(ratings), "answers": n_traces,
        "dimensions": {k: {"name": names.get(k, k), "mean": _mean([r["scores"].get(k) for r in ratings]),
                           "n": sum(r["scores"].get(k) is not None for r in ratings)} for k in dims},
        "verdict_yes": _mean([float(r["verdict"]) for r in ratings if r["verdict"] is not None]),
        "per_task": {t: {"n": len(rs), "mean": _mean([overall(r) for r in rs]),
                         "verdict_yes": _mean([float(r["verdict"]) for r in rs if r["verdict"] is not None]),
                         "category": (grades.get((t, rs[0]["run_index"])) or {}).get("category")}
                     for t, rs in sorted(per_task.items())},
    }
    # Human verdict vs automatic grade: where they disagree, one of them is wrong.
    pairs = [(r["verdict"], grades[(r["task_id"], r["run_index"])]["status"] == "pass") for r in ratings
             if r["verdict"] is not None and (r["task_id"], r["run_index"]) in grades
             and grades[(r["task_id"], r["run_index"])]["status"] in ("pass", "fail")]
    if pairs:
        summary["vs_graders"] = {
            "n": len(pairs), "kappa": cohen_kappa([h for h, _ in pairs], [a for _, a in pairs]),
            "both_pass": sum(h and a for h, a in pairs), "both_fail": sum(not h and not a for h, a in pairs),
            "grader_too_lenient": sum(a and not h for h, a in pairs),   # graders pass, person says no
            "grader_too_strict": sum(h and not a for h, a in pairs),    # graders fail, person says yes
        }
    by_rater: dict[str, dict] = defaultdict(dict)
    for r in ratings:
        by_rater[r["rater"]][(r["task_id"], r["run_index"])] = r
    inter = []
    for a, b in combinations(sorted(by_rater), 2):
        common = sorted(set(by_rater[a]) & set(by_rater[b]))
        if not common:
            continue
        va = [(by_rater[a][k]["verdict"], by_rater[b][k]["verdict"]) for k in common]
        va = [(x, y) for x, y in va if x is not None and y is not None]
        diffs = {d: _mean([abs(by_rater[a][k]["scores"][d] - by_rater[b][k]["scores"][d]) for k in common
                           if by_rater[a][k]["scores"].get(d) is not None and by_rater[b][k]["scores"].get(d) is not None])
                 for d in dims}
        inter.append({"raters": [a, b], "n": len(common), "verdict_kappa": cohen_kappa([x for x, _ in va], [y for _, y in va]),
                      "mean_abs_diff": diffs})
    if inter:
        summary["inter_rater"] = inter
    return summary


def _f(x, digits=2):
    return "–" if x is None else f"{x:.{digits}f}"


def render_human(s: dict) -> str:
    lines = ["## Human scores", "",
             f"{s['ratings']} scores of {s['answers']} answers by {', '.join(s['raters'])}; "
             f"usable as is (verdict yes): {_f(100 * s['verdict_yes'], 0) + '%' if s['verdict_yes'] is not None else '–'}", "",
             "| dimension | mean | scored |", "|---|---|---|"]
    for d in s["dimensions"].values():
        lines.append(f"| {d['name']} | {_f(d['mean'])} | {d['n']} |")
    lines += ["", "| task | scores | mean | verdict yes |", "|---|---|---|---|"]
    for t, r in s["per_task"].items():
        vy = f"{100 * r['verdict_yes']:.0f}%" if r["verdict_yes"] is not None else "–"
        lines.append(f"| {t} | {r['n']} | {_f(r['mean'])} | {vy} |")
    g = s.get("vs_graders")
    if g:
        lines += ["", f"Human verdict vs automatic grade ({g['n']} answers): Cohen's kappa {_f(g['kappa'])}; "
                      f"both pass {g['both_pass']}, both fail {g['both_fail']}, "
                      f"graders pass but the person says no {g['grader_too_lenient']}, "
                      f"graders fail but the person says yes {g['grader_too_strict']}."]
    for ir in s.get("inter_rater", []):
        diffs = ", ".join(f"{k} {_f(v)}" for k, v in ir["mean_abs_diff"].items())
        lines.append(f"Raters {ir['raters'][0]} vs {ir['raters'][1]} ({ir['n']} shared answers): "
                     f"verdict kappa {_f(ir['verdict_kappa'])}; mean score difference {diffs}.")
    return "\n".join(lines)
