"""Print saved runs in full: the question, every model step and tool call, the answer,
the grades and the tokens. For reading what the agent actually did."""

from __future__ import annotations

import json
from pathlib import Path

from ..common.pricing import cost, prompt_tokens
from .report import read_jsonl


def _clip(text: str, full: bool, width: int = 400) -> str:
    text = text or ""
    return text if full or len(text) <= width else text[:width] + f" …（共 {len(text)} 字元，--full 顯示全部）"


def render_trace(t: dict, grade: dict | None, full: bool = False) -> str:
    u = t["usage_total"]
    c = cost(u, t.get("model", ""))
    status = grade["status"] if grade else "not graded"
    out = [f"{'━' * 70}", f"{t['task_id']} #{t['run_index']} · {status} · outcome {t['outcome']} · "
           f"{len(t['steps'])} steps · {t['latency_s']:.1f}s · prompt {prompt_tokens(u)} / output "
           f"{u.get('output_tokens', 0)} tokens" + (f" · ${c:.4f}" if c is not None else "")]
    if t.get("faults"):
        out.append(f"injected faults: {t['faults']}")
    out += ["", "【問題】", t["prompt"]]
    for s in t["steps"]:
        texts = [b.get("text", "") for b in s["content"] if b.get("type") == "text" and b.get("text")]
        if texts and s["stop_reason"] == "tool_use":
            out.append(f"\n[step {s['index']}] " + _clip(" ".join(texts), full, 200))
        for call in s["tool_calls"]:
            flag = "ERROR " if call["is_error"] else ""
            out.append(f"  → {call['name']} {json.dumps(call['input'], ensure_ascii=False)}")
            out.append("    " + flag + _clip(call["output"], full).replace("\n", "\n    "))
            if call.get("exception"):
                out.append(f"    (handler crashed: {call['exception']})")
    out += ["", "【回答】", t.get("final_text") or f"（{t.get('error') or t.get('stop_reason')}）"]
    if grade:
        out.append("")
        for name, g in grade["grades"].items():
            out.append(f"  {'✓' if g['passed'] else '✗'} {name}: {g['details']}")
    return "\n".join(out)


def show(run_dir: str | Path, task: str | None = None, run_index: int | None = None,
         failed: bool = False, full: bool = False) -> str:
    run_dir = Path(run_dir)
    grades = {(g["task_id"], g["run_index"]): g for g in read_jsonl(run_dir / "grades.jsonl")}
    parts = []
    for t in sorted(read_jsonl(run_dir / "traces.jsonl"), key=lambda t: (t["task_id"], t["run_index"])):
        g = grades.get((t["task_id"], t["run_index"]))
        if task and t["task_id"] != task or run_index is not None and t["run_index"] != run_index:
            continue
        if failed and (g is None or g["status"] == "pass"):
            continue
        parts.append(render_trace(t, g, full))
    return "\n".join(parts) if parts else "no matching runs"
