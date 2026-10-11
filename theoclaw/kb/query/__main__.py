"""Command line for compiled knowledge bases.

    python -m theoclaw.kb.query ls                         list knowledge/ with compile model, language, cost
    python -m theoclaw.kb.query census <kb> --tokens       size of the wiki per folder, in chars and tokens
    python -m theoclaw.kb.query metrics <kb> [<kb> ...] [--facts F]   pages, broken links, fact coverage
    python -m theoclaw.kb.query ask <kb> "問題"             answer from the wiki alone (no scripture tools)

The query model (the kb_query role in config/llm.yaml, or --model) is independent of
the model that compiled the wiki. Tokens are counted with the tokenizer role's model.
"""

from __future__ import annotations

import argparse
import json
import sys

from ...common.pricing import cost, prompt_tokens
from ...common.zh import pad

QUERY_PROMPT = """你是循道衛理文獻知識庫的查詢助手。
1. 一律使用繁體中文回答，不得使用簡體字。
2. 只根據知識庫的內容回答；知識庫裡找不到的，要直接說明找不到，不要憑記憶補上。
3. 引用原話時必須出自 sources/ 底下的原文，並註明文件名稱與頁碼；英文原文可以翻譯，但要註明是翻譯。
"""


def _fmt_money(x) -> str:
    return f"${x:.2f}" if isinstance(x, (int, float)) else "–"


def cmd_ls() -> None:
    from .kb import list_knowledge_bases
    kbs = list_knowledge_bases()
    if not kbs:
        print("knowledge/ is empty; build one with python -m theoclaw.kb.compile build <profile>")
        return
    print(f"{'name':48} {'compile model':32} {'language':20} {'calls':>6} {'cost':>8}  built")
    for kb in kbs:
        m = kb.manifest
        print(f"{pad(kb.name, 48)} {str(m.get('model', '?')):32} {str(m.get('language', '?')):20} "
              f"{m.get('calls', 0):>6} {_fmt_money(m.get('cost_usd')):>8}  {m.get('finished', '?')}")


def cmd_census(kb_ref: str, model: str | None) -> None:
    """model: count tokens with this model's tokenizer ("" = the tokenizer role); None = characters only."""
    from .census import census
    from .kb import KnowledgeBase
    kb = KnowledgeBase.open(kb_ref)
    counter = None
    if model is not None:
        from ...llm import token_counter
        counter, why_not = token_counter(model or None)
        model = counter.model if counter else None
        if why_not:
            print(why_not)
    rows = census(kb.wiki, counter)
    print(f"{kb.name} ({kb.wiki})" + (f", tokens counted for {model}" if model else ""))
    print(f"{'folder':16} {'files':>6} {'chars':>10} {'tokens':>10} {'tokens/char':>12}")
    total = {"files": 0, "chars": 0, "tokens": 0}
    for folder, r in sorted(rows.items()):
        ratio = f"{r['tokens'] / r['chars']:.2f}" if r["tokens"] and r["chars"] else "–"
        print(f"{folder:16} {r['files']:>6} {r['chars']:>10} {r['tokens'] if r['tokens'] is not None else '–':>10} {ratio:>12}")
        for k in total:
            total[k] += r[k] or 0
    print(f"{'total':16} {total['files']:>6} {total['chars']:>10} {total['tokens'] if model else '–':>10}")
    if model and kb.root:
        out = kb.root / "census" / f"{model.split('/')[-1]}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"model": model, "folders": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {out}")


def cmd_metrics(kb_refs: list[str], facts_path: str | None) -> None:
    from .kb import KnowledgeBase
    from .metrics import load_facts, wiki_metrics
    facts = load_facts(facts_path) if facts_path else None
    kbs = [KnowledgeBase.open(r) for r in kb_refs]
    rows = [wiki_metrics(kb.wiki, facts) for kb in kbs]
    pct = lambda x: "–" if x is None else f"{100 * x:.0f}%"
    table = [("compile model", [str(kb.manifest.get("model", "?")) for kb in kbs]),
             ("wiki language", [str(kb.manifest.get("language", "?")) for kb in kbs]),
             ("compile cost", [_fmt_money(kb.manifest.get("cost_usd")) for kb in kbs]),
             ("summary pages", [str(r["pages"]["summaries"]) for r in rows]),
             ("concept pages", [str(r["pages"]["concepts"]) for r in rows]),
             ("entity pages", [str(r["pages"]["entities"]) for r in rows]),
             ("compiled chars", [f"{r['compiled_chars']:,}" for r in rows]),
             ("broken links", [pct(r["broken_link_rate"]) for r in rows]),
             ("in index.md", [pct(r["index_coverage"]) for r in rows]),
             ("frontmatter ok", [pct(r["frontmatter_ok"]) for r in rows])]
    if facts:
        table.append(("fact coverage", [pct(r.get("fact_coverage")) for r in rows]))
    width = max(24, *(len(kb.name) + 2 for kb in kbs))
    print(" " * 16 + "".join(pad(kb.name, width) for kb in kbs))
    for label, cells in table:
        print(f"{label:16}" + "".join(pad(c, width) for c in cells))
    for kb, r in zip(kbs, rows):
        if r.get("facts_missing"):
            print(f"\n{kb.name} is missing: " + "; ".join(r["facts_missing"][:10]))


def cmd_ask(kb_ref: str, question: str, model: str | None, effort: str | None) -> None:
    from ...agent.loop import run_agent
    from ...llm import make_client, role
    from . import tools
    from .kb import KnowledgeBase
    kb = KnowledgeBase.open(kb_ref)
    r = role("kb_query", model=model, effort=effort)
    model = r.model
    run = run_agent(make_client(provider=r.provider, params=r.params), question, model=model, handlers=tools.make_handlers(kb.wiki),
                    tools=tools.TOOL_DEFS, system=QUERY_PROMPT + tools.system_addendum(kb.wiki), effort=r.effort,
                    max_tokens=r.max_tokens)
    for call in run.tool_calls:
        print(f"[讀取] {call.name} {json.dumps(call.input, ensure_ascii=False)} "
              f"-> {'錯誤：' + call.output if call.is_error else f'{len(call.output)} 字元'}")
    print()
    print(run.final_text or f"（{run.outcome}：{run.error or run.stop_reason}）")
    if run.simplified_fixed:
        print(f"\n（模型寫了簡體字，已自動轉成繁體：{''.join(run.simplified_fixed)}）")
    usage = run.usage_total()
    c = cost(usage, model)
    print(f"\n— 查詢模型 {model}，編譯模型 {kb.manifest.get('model', '?')}；輸入 {prompt_tokens(usage)} tokens / "
          f"輸出 {usage.get('output_tokens', 0)} tokens" + (f"，約 ${c:.4f}" if c is not None else ""))


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="theoclaw.kb.query", description="list, measure and query compiled wikis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ls", help="list the knowledge bases in knowledge/")
    p = sub.add_parser("census", help="characters (and tokens, with --tokens or --model) per wiki folder")
    p.add_argument("kb")
    p.add_argument("--tokens", action="store_true", help="count tokens with the tokenizer role's model (free count_tokens API)")
    p.add_argument("--model", help="count tokens with this model's tokenizer instead")
    p = sub.add_parser("metrics", help="structural quality of one or more wikis, side by side (no model calls)")
    p.add_argument("kbs", nargs="+")
    p.add_argument("--facts", help="YAML of phrases each source's wiki pages must contain")
    p = sub.add_parser("ask", help="answer a question from the wiki alone")
    p.add_argument("kb")
    p.add_argument("question")
    p.add_argument("--model", help="default: the kb_query role in config/llm.yaml")
    p.add_argument("--effort", help='default: the kb_query role; "none" to omit')
    args = ap.parse_args(argv)
    if args.cmd == "ls":
        cmd_ls()
    elif args.cmd == "metrics":
        cmd_metrics(args.kbs, args.facts)
    elif args.cmd == "census":
        cmd_census(args.kb, args.model if args.model else ("" if args.tokens else None))
    else:
        cmd_ask(args.kb, args.question, args.model, args.effort)


if __name__ == "__main__":
    main()
