"""TheoClaw agent command line.

    python -m theoclaw ask "約翰福音 3:16 是什麼意思？"
    python -m theoclaw ask "衛斯理如何定義基督徒的完全？" --tools scripture,kb --kb wesley-core.en.qwen3.8-max

Every answer is saved to runs/ask/ so it can be scored later:
    python -m theoclaw.evals human rate runs/ask
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from ..common.paths import RUNS_DIR
from ..common.pricing import cost, prompt_tokens

ASK_LOG = RUNS_DIR / "ask"


def log_answer(record: dict) -> None:
    ASK_LOG.mkdir(parents=True, exist_ok=True)
    config = ASK_LOG / "config.json"
    if not config.exists():
        config.write_text(json.dumps({"kind": "ask-log", "n": 1}, indent=2), encoding="utf-8")
    with open(ASK_LOG / "traces.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp950/cp936
    ap = argparse.ArgumentParser(prog="theoclaw", description="TheoClaw, the assistant that answers questions of faith")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ask", help="ask one question; prints the answer, the tool calls and the cost")
    p.add_argument("question")
    p.add_argument("--model", help="default: the agent role in config/llm.yaml")
    p.add_argument("--effort", help='default: the agent role in config/llm.yaml; "none" to omit')
    p.add_argument("--tools", default="scripture,wesley", help="tool groups: scripture, wesley, kb")
    p.add_argument("--kb", help="compiled knowledge base: a folder name in knowledge/, or a path")
    p.add_argument("--no-log", action="store_true", help="do not save this answer to runs/ask/")
    args = ap.parse_args(argv)

    from ..llm import make_client, role
    from .loop import run_agent
    from .tools import build_tool_set

    r = role("agent", model=args.model, effort=args.effort)
    tool_set = build_tool_set(args.tools, args.kb)
    run = run_agent(make_client(provider=r.provider, params=r.params), args.question, model=r.model, handlers=tool_set.handlers,
                    tools=tool_set.defs, system=tool_set.system, effort=r.effort, max_tokens=r.max_tokens)
    for call in run.tool_calls:
        print(f"[工具] {call.name} {json.dumps(call.input, ensure_ascii=False)} -> {'錯誤' if call.is_error else '成功'}")
    print()
    print(run.final_text or f"（{run.outcome}：{run.error or run.stop_reason}）")
    if run.simplified_fixed:
        print(f"\n（模型寫了簡體字，已自動轉成繁體：{''.join(run.simplified_fixed)}）")
    usage = run.usage_total()
    c = cost(usage, r.model)
    print(f"\n— {len(run.steps)} 次模型呼叫，{run.latency_s:.1f} 秒，輸入 {prompt_tokens(usage)} tokens"
          f"（其中快取讀取 {usage.get('cache_read_input_tokens', 0)}）/ 輸出 {usage.get('output_tokens', 0)} tokens"
          + (f"，約 ${c:.4f}" if c is not None else ""))
    if not args.no_log:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        log_answer({"task_id": f"ask-{stamp}", "run_index": 0, "asked_at": stamp,
                    "toolset": tool_set.meta, "llm": r.describe(), **run.to_dict()})
        print(f"已存到 {ASK_LOG}；評分：python -m theoclaw.evals human rate runs/ask")


if __name__ == "__main__":
    main()
