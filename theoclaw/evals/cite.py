"""Two follow-ups to the groundedness evaluation (theoclaw.evals.ground).

    python -m theoclaw.evals ground cite runs/<a> ...      # ALCE-style citation check
    python -m theoclaw.evals ground recheck runs/<a> ...   # unsupported statements against the whole book

cite     Answers cite their sources as 「段落 N」 (a rag_search passage) or 「第 N 頁」 (a page
         of the source PDF). For every sentence with such a citation, the cited passage
         is looked up deterministically (the run's own search index, or the page text)
         and a model judges whether it supports the sentence: citation precision, as in
         ALCE (Gao et al., 2023). Citations to Wesley's own section numbers (「第 N 節」)
         cannot be resolved to a passage and are counted apart, as are labels that do
         not exist (a page past the end of the book).
recheck  `ground score` checks statements only against what the agent retrieved in that
         run. Statements it marked unsupported are checked again against the whole
         source, as FActScore checks against the full knowledge source: supported by
         the book (right, but not retrieved), contradicted, or not in the book at all.
         The whole book goes first in every call, so the provider's prompt cache makes
         the repeated prefix cheap.

Results go to runs/<dir>/cite-<model>.jsonl and runs/<dir>/recheck-<model>.jsonl.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .ground import _load as load_ground
from .human import load_items
from .judge import parse_json

MAX_CITES = 8           # citations judged per answer (the first ones), to bound the cost
PASSAGE_CHARS = 3000    # per cited passage
MAX_TOKENS = 16_000

_PARA = re.compile(r"段落\s*(\d+)(?:\s*[–\-—~至到]\s*(\d+))?")
_PAGE = re.compile(r"(?:第\s*(\d+)(?:\s*[–\-—~至到]\s*(\d+))?\s*頁|頁\s*(\d+)(?:\s*[–\-—~至到]\s*(\d+))?)")
_SECTION = re.compile(r"第\s*\d+\s*[節段]")
_SENT = re.compile(r"[^。！？\n]+[。！？]?")


# ------------------------------------------------------------------ the book

def _wiki(run_dir: Path) -> Path | None:
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    kb = (cfg.get("toolset") or {}).get("kb") or cfg.get("kb")
    if not kb:
        return None
    from ..kb.query import KnowledgeBase
    return KnowledgeBase.open(kb).wiki


def book_pages(wiki: Path) -> dict[int, str]:
    """Page number -> text, from a PageIndex .json source or a converted .md with '## Page N'."""
    src = wiki / "sources"
    pages: dict[int, str] = {}
    for p in sorted(src.glob("*.json")):
        for e in json.loads(p.read_text(encoding="utf-8")):
            pages[int(e["page"])] = e.get("content", "")
    for p in sorted(src.glob("*.md")):
        parts = re.split(r"^## Page (\d+)\s*$", p.read_text(encoding="utf-8"), flags=re.M)
        for i in range(1, len(parts) - 1, 2):
            pages.setdefault(int(parts[i]), parts[i + 1])
    return pages


def book_text(wiki: Path) -> str:
    pages = book_pages(wiki)
    return "\n\n".join(f"[Page {n}]\n{pages[n].strip()}" for n in sorted(pages))


# ------------------------------------------------------------------ citations

def _range(a: str, b: str | None) -> list[int]:
    lo, hi = int(a), int(b) if b else int(a)
    return list(range(lo, min(hi, lo + 2) + 1)) if hi >= lo else [lo]


def extract(answer: str) -> tuple[list[dict], int]:
    """Sentences with a passage or page citation, and the number of section-only citations."""
    cites, sections = [], 0
    for m in _SENT.finditer(answer):
        s = m.group(0).strip()
        paras = [n for a, b in _PARA.findall(s) for n in _range(a, b)]
        pages = [n for g in _PAGE.findall(s) for n in (_range(g[0], g[1]) if g[0] else _range(g[2], g[3]))]
        if paras or pages:
            cites.append({"sentence": s[:400], "paras": paras, "pages": pages})
        elif _SECTION.search(s):
            sections += 1
    return cites, sections


def resolve(cite: dict, chunks: list | None, pages: dict[int, str]) -> str | None:
    parts = []
    for n in cite["paras"]:
        if chunks and 1 <= n <= len(chunks):
            parts.append(f"[段落 {n}] {chunks[n - 1].text}")
    for n in cite["pages"]:
        if n in pages:
            parts.append(f"[第 {n} 頁] {pages[n]}")
    if not parts:
        return None
    return "\n".join(p[:PASSAGE_CHARS] for p in parts)


CITE_SYSTEM = ("你是嚴謹的引用查核員。只根據每條所附的【被引用的原文】判斷該句是否得到支持，"
               "不可用你自己的知識。原文是英文，句子是中文；意思相同就算支持。")


def cite_prompt(items: list[dict]) -> str:
    lines = ["下面每一條是回答中的一句話，以及它所標出處的原文。判斷原文是否支持這句話：",
             "supported（原文明確支持）、partial（只支持一部分，或句子說得比原文多）、not（原文不支持或無關）。", ""]
    for i, it in enumerate(items, 1):
        lines += [f"### {i}", "【句子】" + it["sentence"], "【被引用的原文】", it["passage"], ""]
    lines.append('只輸出 JSON：{"verdicts": [{"i": 1, "verdict": "supported|partial|not"}]}')
    return "\n".join(lines)


_V = {"supported": 1.0, "partial": 0.5, "not": 0.0}


def _out(run_dir: Path, kind: str, model: str) -> Path:
    return Path(run_dir) / f"{kind}-{model}.jsonl"


def _loaded(run_dir: Path, kind: str, model: str) -> list[dict]:
    p = _out(run_dir, kind, model)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def cite(run_dirs, model: str | None = None, *, workers: int = 4, budget_usd: float | None = None, client=None) -> dict:
    from ..kb.query import rag
    from ..llm import complete, role
    name = role("judge", model=model).model
    lock = threading.Lock()
    total = {"model": name, "answers": 0, "judged": 0, "cost": 0.0, "unparsed": 0, "api_errors": 0}
    jobs = []
    for d in map(Path, run_dirs):
        wiki = _wiki(d)
        pages = book_pages(wiki) if wiki else {}
        uses_rag = "rag" in (json.loads((d / "config.json").read_text(encoding="utf-8")).get("toolset") or {}).get("tools", [])
        chunks = rag.index_wiki_sources(wiki).chunks if (wiki and uses_rag) else None
        done = {(r["task_id"], r["run_index"]) for r in _loaded(d, "cite", name)}
        for it in load_items([d]):
            if it.key not in done:
                jobs.append((d, it, pages, chunks))

    import random
    random.Random(0).shuffle(jobs)  # a budget stop then thins every arm alike

    def one(job):
        d, item, pages, chunks = job
        cites, sections = extract(item.trace.get("final_text") or "")
        resolved, missing = [], 0
        for c in cites[:MAX_CITES]:
            passage = resolve(c, chunks, pages)
            if passage is None:
                missing += 1
            else:
                resolved.append({**c, "passage": passage})
        verdicts, usd = [], 0.0
        if resolved:
            with lock:
                if budget_usd is not None and total["cost"] >= budget_usd:
                    return
            try:
                c = complete(cite_prompt(resolved), role="judge", model=model, system=CITE_SYSTEM,
                             client=client, max_tokens=MAX_TOKENS)
            except Exception as e:  # rerun to fill gaps
                with lock:
                    total["api_errors"] += 1
                    total["last_error"] = str(e)[:200]
                return
            usd = c.cost_usd or 0.0
            parsed = parse_json(c.text) or {}
            got = {v.get("i"): v.get("verdict") for v in parsed.get("verdicts") or [] if isinstance(v, dict)}
            if any(got.get(i) not in _V for i in range(1, len(resolved) + 1)):
                with lock:
                    total["cost"] += usd
                    total["unparsed"] += 1
                return
            verdicts = [got[i] for i in range(1, len(resolved) + 1)]
        rec = {"task_id": item.key[0], "run_index": item.key[1], "model": name, "cost_usd": usd,
               "citations": len(cites), "judged": len(resolved), "unresolvable": missing, "section_only": sections,
               "precision": (sum(_V[v] for v in verdicts) / len(verdicts)) if verdicts else None,
               "items": [{"sentence": r["sentence"], "paras": r["paras"], "pages": r["pages"], "verdict": v}
                         for r, v in zip(resolved, verdicts)]}
        with lock:
            total["cost"] += usd
            total["answers"] += 1
            total["judged"] += len(resolved)
            with open(_out(d, "cite", name), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    return total


# ------------------------------------------------------------------ recheck against the whole book

RECHECK_INTRO = ("你是嚴謹的事實查核員。下面是衛斯理《A Plain Account of Christian Perfection》的全文（英文，按頁標示）。"
                 "之後會給你一些中文陳述，你只根據這本書判斷，不可用你自己的知識。\n\n【全書】\n")


def recheck(run_dirs, source_wiki: str, model: str | None = None, *, workers: int = 4,
            budget_usd: float | None = None, client=None) -> dict:
    from ..kb.query import KnowledgeBase
    from ..llm import complete, role
    name = role("judge", model=model).model
    system = RECHECK_INTRO + book_text(KnowledgeBase.open(source_wiki).wiki)  # identical in every call: cached
    lock = threading.Lock()
    total = {"model": name, "answers": 0, "statements": 0, "cost": 0.0, "unparsed": 0, "api_errors": 0}
    jobs = []
    for d in map(Path, run_dirs):
        done = {(r["task_id"], r["run_index"]) for r in _loaded(d, "recheck", name)}
        for g in load_ground(d, name):
            if g["unsupported"] and (g["task_id"], g["run_index"]) not in done:
                jobs.append((d, g))

    def one(job):
        d, g = job
        with lock:
            if budget_usd is not None and total["cost"] >= budget_usd:
                return
        stmts = g["unsupported"]
        prompt = "\n".join(["以下陳述在助手當次查到的資料裡找不到依據。請對照全書逐條判斷：",
                            "supported（書中有，意思相同）、contradicted（書中說法相反或不同）、not_in_book（書中沒有提到）。",
                            "並給出支持或矛盾的頁碼（沒有就填 null）。", "",
                            *[f"{i}. {s}" for i, s in enumerate(stmts, 1)], "",
                            '只輸出 JSON：{"verdicts": [{"i": 1, "verdict": "supported|contradicted|not_in_book", "page": 12}]}'])
        try:
            c = complete(prompt, role="judge", model=model, system=system, client=client, max_tokens=MAX_TOKENS)
        except Exception as e:
            with lock:
                total["api_errors"] += 1
                total["last_error"] = str(e)[:200]
            return
        parsed = parse_json(c.text) or {}
        got = {v.get("i"): v for v in parsed.get("verdicts") or [] if isinstance(v, dict)}
        ok = all(got.get(i, {}).get("verdict") in ("supported", "contradicted", "not_in_book") for i in range(1, len(stmts) + 1))
        with lock:
            total["cost"] += c.cost_usd or 0.0
            if not ok:
                total["unparsed"] += 1
                return
            rec = {"task_id": g["task_id"], "run_index": g["run_index"], "model": name, "cost_usd": c.cost_usd,
                   "usage": c.usage, "items": [{"statement": s, "verdict": got[i]["verdict"], "page": got[i].get("page")}
                                               for i, s in enumerate(stmts, 1)]}
            with open(_out(d, "recheck", name), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            total["answers"] += 1
            total["statements"] += len(stmts)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, jobs))
    return total


# ------------------------------------------------------------------ report

def report(run_dirs, model: str | None = None) -> str:
    from ..llm import role
    name = role("judge", model=model).model
    lines = ["# Citations and unsupported statements, evaluator `" + name + "`", "",
             "Citation check (ALCE-style citation precision): each sentence citing 「段落 N」 or 「第 N 頁」 against the cited passage.", "",
             "| arm | answers | citations | judged | precision | not supported | label not found | section-only citations |",
             "|---|---|---|---|---|---|---|---|"]
    for d in map(Path, run_dirs):
        rs = _loaded(d, "cite", name)
        items = [i for r in rs for i in r["items"]]
        prec = (sum(_V[i["verdict"]] for i in items) / len(items)) if items else None
        lines.append(f"| {d.name.split('_')[-1]} | {len(rs)} | {sum(r['citations'] for r in rs)} | {len(items)} | "
                     f"{'–' if prec is None else f'{prec:.0%}'} | {sum(i['verdict'] == 'not' for i in items)} | "
                     f"{sum(r['unresolvable'] for r in rs)} | {sum(r['section_only'] for r in rs)} |")
    lines += ["", "Statements unsupported by the retrieved text, rechecked against the whole book (FActScore-style):", "",
              "| arm | statements | supported by the book (not retrieved) | contradicted | not in the book |", "|---|---|---|---|---|"]
    for d in map(Path, run_dirs):
        items = [i for r in _loaded(d, "recheck", name) for i in r["items"]]
        n = len(items) or 1
        cnt = {k: sum(i["verdict"] == k for i in items) for k in ("supported", "contradicted", "not_in_book")}
        lines.append(f"| {d.name.split('_')[-1]} | {len(items)} | {cnt['supported']} ({cnt['supported'] / n:.0%}) | "
                     f"{cnt['contradicted']} ({cnt['contradicted'] / n:.0%}) | {cnt['not_in_book']} ({cnt['not_in_book'] / n:.0%}) |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ checking the checker

SPOT_COLS = ["編號", "句子（助手的回答）", "被引用的原文（英文）", "你的判斷：支持 / 部分 / 不支持", "備註"]
_HUMAN = {"支持": "supported", "部分": "partial", "不支持": "not"}


def spotcheck_make(run_dirs, out: str | Path, model: str | None = None, n: int = 20, seed: int = 0) -> Path:
    """A blind sheet of the citation checker's verdicts for a person to judge; the
    checker's verdicts go to a key file next to it."""
    import csv
    import random
    from ..kb.query import rag
    from ..llm import role
    name = role("judge", model=model).model
    pool = []
    for d in map(Path, run_dirs):
        wiki = _wiki(d)
        pages = book_pages(wiki)
        uses_rag = "rag" in (json.loads((d / "config.json").read_text(encoding="utf-8")).get("toolset") or {}).get("tools", [])
        chunks = rag.index_wiki_sources(wiki).chunks if uses_rag else None
        for r in _loaded(d, "cite", name):
            for it in r["items"]:
                pool.append({**it, "passage": resolve(it, chunks, pages)})
    rng = random.Random(seed)
    want = {"not": n * 2 // 5, "partial": n // 5}
    want["supported"] = n - sum(want.values())
    picked = []
    for v, k in want.items():
        cand = [p for p in pool if p["verdict"] == v and p["passage"]]
        picked += rng.sample(cand, min(k, len(cand)))
    rng.shuffle(picked)
    out = Path(out)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(SPOT_COLS)
        for i, p in enumerate(picked, 1):
            w.writerow([i, p["sentence"], p["passage"][:PASSAGE_CHARS], "", ""])
    out.with_suffix(".key.json").write_text(json.dumps({str(i): p["verdict"] for i, p in enumerate(picked, 1)}),
                                            encoding="utf-8")
    return out


def spotcheck_score(sheet: str | Path) -> str:
    """Agreement of the checker with the person who filled in the sheet."""
    import csv
    sheet = Path(sheet)
    key = json.loads(sheet.with_suffix(".key.json").read_text(encoding="utf-8"))
    with open(sheet, encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f)][1:]
    pairs = [(_HUMAN[r[3].strip()], key[r[0]]) for r in rows if r and r[3].strip() in _HUMAN]
    if not pairs:
        return "no judgments filled in yet"
    exact = sum(h == m for h, m in pairs)
    binary = sum((h == "not") == (m == "not") for h, m in pairs)
    lines = [f"judged by the person: {len(pairs)} of {len(rows)}",
             f"same verdict (supported / partial / not): {exact}/{len(pairs)} ({exact / len(pairs):.0%})",
             f"same on 'not supported' vs the rest: {binary}/{len(pairs)} ({binary / len(pairs):.0%})", "",
             "person vs checker | supported | partial | not", "---|---|---|---"]
    for h in ("supported", "partial", "not"):
        lines.append(f"{h} | " + " | ".join(str(sum(1 for a, b in pairs if a == h and b == m)) for m in ("supported", "partial", "not")))
    return "\n".join(lines)
