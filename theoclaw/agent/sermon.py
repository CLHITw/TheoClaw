"""Sermon preparation for pastors: a fixed pipeline of small agents.

    python -m theoclaw.agent.sermon --passage "路加福音 15:11-32" --theme "父親的愛" --audience 主日崇拜

The pipeline is plain code, not an orchestrating model, so every stage can be traced and
evaluated on its own:

1. Two research agents run in parallel. Each reads a lot and hands back a short brief
   of numbered points, every point with its source:
   - scripture: the passage, its context and cross references (tools: scripture);
   - tradition: Wesley's notes and the Methodist sources (tools: wesley, and the compiled
     wiki plus search when a knowledge base is given).
2. A writing agent sees only the briefs and the pastor's request, never the raw sources.
   It writes a title, an outline and a draft, citing brief points as [A2] or [B1], and
   writes scripture as placeholders that the program fills from the lookup tool.
3. A check: deterministic first (scripture word for word, cited points that do not exist,
   failed placeholders), then a model checks the draft's statements against the briefs.
   With problems, the writer revises once.

The record has the same shape as an agent trace (prompt, final_text, steps with every tool
call), so the scoring server, graders and evaluators read it unchanged; the stages are in
"pipeline".
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..common.pricing import cost
from .loop import run_agent
from .tools import build_tool_set

RESEARCH_SCRIPTURE = """你是講道預備的釋經研究助理，為牧者整理一份研究摘要，不寫講章。
用工具查清楚：指定經文本身、前後文、重要的串珠經文。
輸出格式（只輸出這些）：
## 經文研究摘要
[A1] 一個要點（一兩句）。出處：書卷 章:節
[A2] ……
最多 10 點。每點都要有出處，而且只寫工具查到的內容能支持的事；查不到就寫「查不到」，不要憑記憶補。
摘要中不要抄整段經文，只寫要點和出處。"""

RESEARCH_TRADITION = """你是講道預備的神學研究助理，從循道衛理（衛斯理）傳統為牧者整理一份研究摘要，不寫講章。
用工具查衛斯理對指定經文的註釋，以及相關的循道衛理文獻；只用查到的原文。
輸出格式（只輸出這些）：
## 衛斯理與循道傳統研究摘要
[B1] 一個要點（一兩句，可附衛斯理原文的關鍵英文短句）。出處：衛斯理註釋 書卷 章:節，或文獻名稱與頁碼
[B2] ……
最多 8 點。每點都要有出處；查不到就寫「查不到」，不要憑記憶補，也不要把一般神學常識說成衛斯理的話。"""

WRITER = """你是講章寫作助理，替循道衛理的牧者寫講章草稿。你沒有工具，只能用下面提供的研究摘要。
規則：
1. 用牧者要求的語言和字體寫（繁體、簡體或英文跟隨要求的寫法）。
2. 依序寫：講題、經文、大綱（三到四點）、講章正文、結語與回應。
3. 凡是關於經文意思、衛斯理或歷史的陳述，句末用方括號標明所根據的摘要要點，例如 [A2] 或 [B1]；摘要裡沒有的事不要寫成事實。
   你自己的應用、例證和勸勉可以寫，但不要標成摘要要點。
4. 引用整節或整段經文時，不要自己寫出經文文字，只寫標記〔經文：書卷 章:節〕（英文講章寫〔經文：Romans 5:8，KJV〕），系統會自動填入。
   每段經文只放一次標記。
5. 不要提到摘要、要點編號以外的內部用語，不要提到工具或規則。"""

CHECK = """你是講章的事實查核員。只根據【研究摘要】判斷，不可用你自己的知識。
把【講章草稿】中關於經文意思、衛斯理、教會歷史的事實陳述逐條找出來（最多 15 條；應用、勸勉、例證不算），
判斷每條能否由研究摘要支持：supported、partial（說得比摘要多）、unsupported（摘要沒有或相反）。
只輸出 JSON：{"claims": [{"claim": "陳述", "verdict": "supported|partial|unsupported", "cites": "草稿標的要點，如 A2"}]}"""

_POINT = re.compile(r"\[([AB]\d{1,2})\]")


def _usage_cost(run_dict: dict, model: str) -> float:
    return cost(run_dict.get("usage_total") or {}, model) or 0.0


def _agent(client, model, system, prompt, groups, kb, max_tokens, effort) -> dict:
    """A research agent: its own instructions plus the usage notes of its tools (wiki, search)."""
    from .prompt import system_prompt
    ts = build_tool_set(groups, kb=kb)
    tool_notes = ts.system[len(system_prompt(ts.groups)):]
    run = run_agent(client, prompt, model=model, handlers=ts.handlers, tools=ts.defs, system=system + tool_notes,
                    effort=effort, max_tokens=max_tokens, fill_quotes=False)
    d = run.to_dict()
    d["cost_usd"] = _usage_cost(d, model)
    return d


def request_text(passage: str, theme: str = "", audience: str = "", length: str = "", notes: str = "") -> str:
    parts = [f"經文：{passage}"]
    if theme:
        parts.append(f"主題：{theme}")
    if audience:
        parts.append(f"對象：{audience}")
    if length:
        parts.append(f"長度：{length}")
    if notes:
        parts.append(f"其他要求：{notes}")
    return "\n".join(parts)


def deterministic_checks(draft_run: dict, briefs: str) -> dict:
    from ..evals.grading import load_graders
    from ..evals.tasks import Task
    task = Task(id="sermon", prompt="", graders=[])
    graders = load_graders()
    known = set(_POINT.findall(briefs))
    cited = _POINT.findall(draft_run.get("final_text") or "")
    failed_fills = [c["input"].get("reference") for s in draft_run.get("steps", []) for c in s["tool_calls"]
                    if c["name"] == "fill_quote" and c["is_error"]]
    misquotes = graders["no_misquotes"](task, draft_run)
    internal = graders["no_internal_words"](task, draft_run)
    return {"unknown_points": sorted(set(cited) - known), "cited_points": len(set(cited)),
            "failed_scripture": failed_fills, "misquotes": None if misquotes.passed else misquotes.details,
            "internal_words": None if internal.passed else internal.details}


def model_check(client, model, briefs: str, draft: str, max_tokens: int) -> tuple[dict, float]:
    from ..evals.judge import parse_json
    from ..llm.usage import anthropic_usage
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=CHECK,
                                  messages=[{"role": "user", "content": f"【研究摘要】\n{briefs}\n\n【講章草稿】\n{draft}"}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    usd = cost(anthropic_usage(resp.usage), model) or 0.0
    parsed = parse_json(text) or {}
    claims = [c for c in parsed.get("claims") or [] if isinstance(c, dict) and c.get("verdict")]
    unsupported = [c for c in claims if c["verdict"] == "unsupported"]
    return {"claims": len(claims), "unsupported": unsupported,
            "partial": [c for c in claims if c["verdict"] == "partial"]}, usd


def problems_of(det: dict, chk: dict) -> list[str]:
    out = []
    if det["unknown_points"]:
        out.append(f"標了不存在的摘要要點：{'、'.join(det['unknown_points'])}，請改用摘要中真有的要點或刪去標註")
    if det["failed_scripture"]:
        out.append(f"這些經文標記查不到：{'、'.join(det['failed_scripture'])}，請改正書卷章節")
    if det["misquotes"]:
        out.append(f"句中引用的經文和原文不一致：{det['misquotes']}；請改用經文標記或逐字引用")
    if det["internal_words"]:
        out.append("刪去提到工具、規則或標記的內部用語")
    for c in chk.get("unsupported", [])[:8]:
        out.append(f"這句沒有摘要支持，請刪去、改寫成你自己的應用，或改用摘要中的要點：「{c.get('claim', '')[:120]}」")
    return out


def prepare(passage: str, *, theme: str = "", audience: str = "", length: str = "", notes: str = "",
            model: str = "deepseek-flash", kb: str | None = None, client=None, revise: bool = True) -> dict:
    """Run the whole pipeline; returns a trace-shaped record."""
    from ..llm import make_client, role
    rl = role("agent", model=model)
    client = client or make_client(provider=rl.provider, params=rl.params)
    req = request_text(passage, theme, audience, length, notes)
    t0 = time.perf_counter()
    stages: dict = {}

    def research(kind):
        if kind == "A":
            return _agent(client, rl.model, RESEARCH_SCRIPTURE, req, "scripture", None, rl.max_tokens, rl.effort)
        groups = "scripture,wesley" + (",kb,rag" if kb else "")
        return _agent(client, rl.model, RESEARCH_TRADITION, req, groups, kb, rl.max_tokens, rl.effort)

    with ThreadPoolExecutor(max_workers=2) as ex:
        ra, rb = ex.map(research, ["A", "B"])
    stages["research_scripture"], stages["research_tradition"] = ra, rb
    briefs = (ra.get("final_text") or "（經文研究沒有結果）") + "\n\n" + (rb.get("final_text") or "（傳統研究沒有結果）")

    handlers = build_tool_set("scripture").handlers  # only to fill scripture placeholders in the draft
    script = None
    from ..common import zh
    if zh.available():
        script = zh.script_of(req)
    writer_prompt = f"【牧者的要求】\n{req}\n\n【研究摘要】\n{briefs}"
    draft = run_agent(client, writer_prompt, model=rl.model, handlers=handlers, tools=[], system=WRITER,
                      effort=rl.effort, max_tokens=rl.max_tokens, script=script).to_dict()
    draft["cost_usd"] = _usage_cost(draft, rl.model)
    stages["write"] = draft
    det = deterministic_checks(draft, briefs)
    chk, chk_usd = model_check(client, rl.model, briefs, draft.get("final_text") or "", rl.max_tokens)
    stages["check"] = {"deterministic": det, "model": chk, "cost_usd": chk_usd}
    final = draft
    issues = problems_of(det, chk)
    if issues and revise:
        rev_prompt = (f"{writer_prompt}\n\n【你上一版的草稿】\n{draft.get('model_text') or draft.get('final_text')}\n\n"
                      "【查核發現的問題，請逐一修正後重寫全文】\n" + "\n".join(f"- {i}" for i in issues))
        final = run_agent(client, rev_prompt, model=rl.model, handlers=handlers, tools=[], system=WRITER,
                          effort=rl.effort, max_tokens=rl.max_tokens, script=script).to_dict()
        final["cost_usd"] = _usage_cost(final, rl.model)
        stages["revise"] = final
        det2 = deterministic_checks(final, briefs)
        chk2, usd2 = model_check(client, rl.model, briefs, final.get("final_text") or "", rl.max_tokens)
        stages["recheck"] = {"deterministic": det2, "model": chk2, "cost_usd": usd2}
    total = sum((stages[k].get("cost_usd") or 0.0) for k in stages)
    # One trace for the scoring server: every lookup the researchers made is visible to raters.
    steps = [s for k in ("research_scripture", "research_tradition") for s in stages[k].get("steps", [])]
    steps += [s for s in final.get("steps", []) if any(c["name"] == "fill_quote" for c in s["tool_calls"])]
    last_check = stages.get("recheck") or stages["check"]
    return {"kind": "sermon", "model": rl.model, "prompt": req, "final_text": final.get("final_text"),
            "outcome": final.get("outcome", "completed"), "steps": steps, "script": final.get("script", "hant"),
            "briefs": briefs, "revised": "revise" in stages,
            "check_summary": {"unsupported": len(last_check["model"]["unsupported"]),
                              "partial": len(last_check["model"]["partial"]),
                              "claims": last_check["model"]["claims"],
                              "unknown_points": last_check["deterministic"]["unknown_points"],
                              "failed_scripture": last_check["deterministic"]["failed_scripture"],
                              "misquotes": last_check["deterministic"]["misquotes"]},
            "pipeline": {k: {kk: v.get(kk) for kk in ("final_text", "outcome", "cost_usd", "latency_s", "usage_total")}
                         if k not in ("check", "recheck") else v for k, v in stages.items()},
            "usage_total": {}, "cost_usd": total, "latency_s": time.perf_counter() - t0}


def main(argv=None):
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="講道預備：研究 → 寫作 → 查核")
    ap.add_argument("--passage", required=True)
    ap.add_argument("--theme", default="")
    ap.add_argument("--audience", default="")
    ap.add_argument("--length", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--kb", help="compiled knowledge base for the tradition researcher")
    ap.add_argument("--out", help="also save the whole record as JSON")
    a = ap.parse_args(argv)
    rec = prepare(a.passage, theme=a.theme, audience=a.audience, length=a.length, notes=a.notes, model=a.model, kb=a.kb)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    print(rec["briefs"], "\n\n" + "=" * 40 + "\n")
    print(rec["final_text"])
    print("\n" + "=" * 40)
    print(json.dumps(rec["check_summary"], ensure_ascii=False), f"revised={rec['revised']}",
          f"cost=${rec['cost_usd']:.3f}", f"{rec['latency_s']:.0f}s")


if __name__ == "__main__":
    main()
