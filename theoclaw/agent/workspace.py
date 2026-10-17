"""The pastor's sermon workspace: research once, then ask step by step, collect pieces, assemble.

A pastor rarely wants a whole sermon in one go. They open a sermon (passage, theme, audience),
then ask for one thing at a time: a word's meaning, an introduction, an illustration, a shorter
second point. Answers they like go onto the draft board; at the end the board is assembled into
one manuscript.

- start():    the research stage once (theoclaw.agent.sermon.research): the program-built word
              study and the two research agents. Kept in the project and reused by every turn.
- turn():     one assistant agent with all pastor tools answers this one request. It sees the
              research briefs and a short state document (sermon, board, the last few turns),
              never the whole conversation. Written text is checked: deterministic checks
              always, the model check when the reply is a passage for the sermon.
- assemble(): the writer joins the board's pieces into one manuscript, then the checks.

A project is a plain dict (saved as JSON by the caller); turn() and assemble() return records
in the shape of an agent trace, so the scoring server, graders and evaluators read them unchanged.
"""

from __future__ import annotations

import re
import secrets
import time

from .loop import run_agent
from .sermon import WRITER, _usage_cost, deterministic_checks, model_check
from .tools import build_tool_set

BOARD_CHARS = 6000       # the board as shown to the assistant (the assembler sees all of it)
CHECK_MIN_CHARS = 300    # a reply this long with sermon prose gets the model check too

ASSISTANT = """你是牧者的講章助手，和牧者一步一步預備一篇講章。
規則：
1. 只回應牧者這一次的要求：回答問題、寫或改指定的段落、提供例證或大綱。不要主動寫整篇講章，也不要重複寫已在講稿板上的段落，除非牧者要求修改它。
2. 先用【研究摘要】；關於經文意思、原文、衛斯理或歷史背景的陳述，句末標上依據的要點，例如 [A2] 或 [B1]。
   摘要沒有的，就用工具查（經文、原文逐詞、聖經百科辭典、衛斯理註釋、文獻），並說明出處；查不到就說查不到，不要憑記憶補。
3. 引用整節或整段經文時只寫標記〔經文：書卷 章:節〕（英文寫〔經文：Romans 5:8，KJV〕；牧者要現代英文譯本時寫〔經文：Romans 5:8，WEB〕），系統會自動填入。
4. 用牧者提問的語言和字體回答。寫段落時，依牧者要的長度與對象；你自己的應用和例證可以寫，但不要標成摘要要點。
5. 不要提到工具名稱、標記或你所遵守的規則。
6. 直接給牧者要的內容：不要在回答前面列出或重述研究摘要，不要加「研究摘要」之類的標題。
7. 一個經文標記只放一段經文；要引幾處經文就寫幾個標記，或只寫出處。
8. 摘要要點的編號只能用摘要裡已有的（例如 A1–A10、B1–B8）；你這次自己查到的新資料不要編號，直接寫出處，
   例如「（衛斯理註釋 路加福音 15:16）」或「（ISBE：COMPASSION）」。
9. 中文講稿引用英文原文（衛斯理、辭典）時，先寫通順的中文翻譯並註明是翻譯，需要時把關鍵英文短句放在括號裡；
   不要只放一句英文。引文要直接支持前面那句話，若不是一看就懂，接一句說明它怎樣支持（會眾聽得懂才算）。"""

ASSEMBLE = """以下是牧者已經選定、按順序排好的講稿段落。請把它們整合成一篇完整的講章：
盡量保留牧者選定段落的原文與要點標註 [A2]、[B1]，只補上必要的講題、銜接句和結語；不要加入摘要以外的新事實。"""

_WRITING_HINT = re.compile(r"寫|改|擴充|縮短|段落|引言|結語|例證|例子|大綱|講稿|draft|write|rewrite|paragraph|introduction", re.I)


def _tool_groups(kb: str | None) -> str:
    from . import reference
    groups = "scripture,wesley" + (",reference" if reference.available() else "")
    return groups + (",kb,rag" if kb else "")


def start(fields: dict, *, owner: str, model: str = "deepseek-flash", kb: str | None = None, client=None) -> dict:
    from .sermon import research
    r = research(fields["passage"], theme=fields.get("theme", ""), audience=fields.get("audience", ""),
                 length=fields.get("length", ""), notes=fields.get("notes", ""), model=model, kb=kb, client=client,
                 lang=fields.get("lang") or "zh")
    costs = sum((r[k].get("cost_usd") or 0.0) for k in ("research_scripture", "research_tradition"))
    research_steps = [s for k in ("research_scripture", "research_tradition") for s in r[k].get("steps", [])]
    return {"id": secrets.token_hex(6), "owner": owner, "created": time.strftime("%Y%m%d-%H%M%S"),
            **{k: fields.get(k, "") for k in ("passage", "theme", "audience", "length", "notes")},
            "request": r["request"], "briefs": r["briefs"], "word_study": r["word_study"],
            "research_steps": research_steps, "research_cost_usd": costs, "kb": kb, "lang": fields.get("lang") or "zh",
            "board": [], "turns": []}


def state_text(project: dict) -> str:
    board = project.get("board", [])
    shown, used = [], 0
    for i, p in enumerate(board, 1):
        piece = f"（{i}）{p.get('label') or '段落'}：{p['text']}"
        if used + len(piece) > BOARD_CHARS:
            shown.append(f"（{i}）{p.get('label') or '段落'}：……（已省略）")
            continue
        shown.append(piece)
        used += len(piece)
    from .conversation import history_text
    history = history_text([(t["ask"], t["reply"]) for t in project.get("turns", [])])
    return "\n\n".join([
        "【講章】\n" + project["request"],
        "【講稿板】（牧者已選定的段落）\n" + ("\n".join(shown) if shown else "（還沒有）"),
        "【先前的對話】（牧者的要求可能接著前面說的，例如「再短一點」「第二點也這樣寫」）\n"
        + (history.replace("使用者：", "牧者：") if history else "（這是第一個問題）"),
        "【研究摘要】\n" + project["briefs"],
    ])


def _evidence(project: dict, run: dict) -> str:
    """What the reply may rest on: the briefs plus this turn's own lookups."""
    outs = [f"--- {c['name']} {c['input']}\n{c['output'][:3000]}" for s in run.get("steps", [])
            for c in s["tool_calls"] if not c["is_error"] and c["name"] != "fill_quote"]
    return project["briefs"] + ("\n\n【本次查到的資料】\n" + "\n\n".join(outs) if outs else "")


def _check(project: dict, run: dict, rl, client, force_model: bool) -> dict:
    evidence = _evidence(project, run)
    det = deterministic_checks(run, evidence)
    text = run.get("final_text") or ""
    out = {"deterministic": det, "model": None, "cost_usd": 0.0}
    if force_model or len(text) >= CHECK_MIN_CHARS:
        chk, usd = model_check(client, rl.model, evidence, text, rl.max_tokens)
        out.update(model=chk, cost_usd=usd)
    return out


def _summary(check: dict) -> dict:
    m = check.get("model") or {}
    d = check["deterministic"]
    return {"claims": m.get("claims"), "unsupported": len(m.get("unsupported", [])) if m else None,
            "partial": len(m.get("partial", [])) if m else None, "unknown_points": d["unknown_points"],
            "failed_scripture": d["failed_scripture"], "misquotes": d["misquotes"],
            "unsupported_claims": [c.get("claim", "")[:160] for c in (m.get("unsupported") or [])][:5]}


def _client(model: str, client):
    from ..llm import make_client, role
    rl = role("agent", model=model)
    return rl, client or make_client(provider=rl.provider, params=rl.params)


def turn(project: dict, message: str, *, model: str = "deepseek-flash", client=None) -> dict:
    """One request in the workspace; returns a trace-shaped record and adds the turn to the project."""
    rl, client = _client(model, client)
    from .prompt import system_prompt
    ts = build_tool_set(_tool_groups(project.get("kb")), kb=project.get("kb"))
    tool_notes = ts.system[len(system_prompt(ts.groups)):]
    prompt = state_text(project) + "\n\n【牧者這一次的要求】\n" + message
    t0 = time.perf_counter()
    run = run_agent(client, prompt, model=rl.model, handlers=ts.handlers, tools=ts.defs,
                    system=ASSISTANT + tool_notes, effort=rl.effort, max_tokens=rl.max_tokens).to_dict()
    run["cost_usd"] = _usage_cost(run, rl.model)
    writing = bool(_WRITING_HINT.search(message))
    check = _check(project, run, rl, client, force_model=writing and len(run.get("final_text") or "") >= 150)
    reply = run.get("final_text") or ""
    project.setdefault("turns", []).append({"ask": message, "reply": reply, "at": time.strftime("%Y%m%d-%H%M%S")})
    return {"kind": "sermon_turn", "project": project["id"], "model": rl.model,
            "prompt": f"{project['passage']}｜{message}", "final_text": reply, "outcome": run.get("outcome"),
            "steps": run.get("steps", []), "script": run.get("script", "hant"), "writing": writing,
            "check_summary": _summary(check), "usage_total": run.get("usage_total", {}),
            "cost_usd": (run["cost_usd"] or 0.0) + check["cost_usd"], "latency_s": time.perf_counter() - t0}


def assemble(project: dict, *, model: str = "deepseek-flash", client=None) -> dict:
    """Join the board into one manuscript; returns a trace-shaped record."""
    rl, client = _client(model, client)
    board = project.get("board", [])
    if not board:
        raise ValueError("講稿板上還沒有段落")
    pieces = "\n\n".join(f"（{i}）{p.get('label') or '段落'}\n{p['text']}" for i, p in enumerate(board, 1))
    prompt = (f"【牧者的要求】\n{project['request']}\n\n【研究摘要】\n{project['briefs']}\n\n"
              f"【牧者選定的段落】\n{pieces}\n\n{ASSEMBLE}")
    handlers = build_tool_set("scripture").handlers
    t0 = time.perf_counter()
    run = run_agent(client, prompt, model=rl.model, handlers=handlers, tools=[], system=WRITER,
                    effort=rl.effort, max_tokens=rl.max_tokens).to_dict()
    run["cost_usd"] = _usage_cost(run, rl.model)
    check = _check({**project, "briefs": project["briefs"] + "\n\n【牧者選定的段落】\n" + pieces}, run, rl, client, True)
    return {"kind": "sermon_draft", "project": project["id"], "model": rl.model,
            "prompt": f"{project['passage']}｜組成完整講稿", "final_text": run.get("final_text"),
            "outcome": run.get("outcome"), "steps": run.get("steps", []), "script": run.get("script", "hant"),
            "check_summary": _summary(check), "usage_total": run.get("usage_total", {}),
            "cost_usd": (run["cost_usd"] or 0.0) + check["cost_usd"], "latency_s": time.perf_counter() - t0}
