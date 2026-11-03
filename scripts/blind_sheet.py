"""Blind grading sheets: answers from several runs, shuffled, with no run labels or knowledge-base
names, for a grader who checks each answer against what that answer retrieved.

    python scripts/blind_sheet.py <out_dir> <run_dir> [<run_dir> ...] [--seed 20261103]

Writes <out_dir>/sheet.md (one section per answer: question, reference points, the retrieved tool
outputs, the answer) and <out_dir>/key.json (answer id -> run and task). Open key.json only after
grading. Scores go in <out_dir>/scores.jsonl: {"id", "claims", "supported", "partly", "facts_hit", "facts_total"}.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

import yaml

TOOL_CHARS = 6000          # per tool output in the sheet
HIDE = re.compile(r"(methodist|lutheran|baptist|anglican|reformed)\.en\.[\w.-]+", re.I)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir")
    ap.add_argument("run_dirs", nargs="+")
    ap.add_argument("--seed", type=int, default=20261103)
    ap.add_argument("--tool-chars", type=int, default=TOOL_CHARS, help="characters kept of each tool output")
    ap.add_argument("--parts", type=int, default=1, help="split the sheet into this many files (sheet-1.md ...)")
    a = ap.parse_args(argv)
    items = []
    for d in map(Path, a.run_dirs):
        facts = {t["id"]: (t.get("expect") or {}).get("facts", [])
                 for t in yaml.safe_load((d / "tasks.yaml").read_text(encoding="utf-8"))}
        for line in (d / "traces.jsonl").read_text(encoding="utf-8").splitlines():
            t = json.loads(line)
            items.append({"run": d.name, "task_id": t["task_id"], "prompt": t["prompt"],
                          "facts": facts.get(t["task_id"], []), "answer": t.get("final_text") or "",
                          "tools": [(c["name"], json.dumps(c["input"], ensure_ascii=False), c.get("output") or "")
                                    for s in t.get("steps", []) for c in s["tool_calls"]
                                    if not c.get("is_error") and c["name"] != "fill_quote"]})
    random.Random(a.seed).shuffle(items)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    key, parts = {}, []
    for i, it in enumerate(items, 1):
        aid = f"A{i:02d}"
        key[aid] = {"run": it["run"], "task_id": it["task_id"]}
        tools = "\n\n".join(f"--- {n} {HIDE.sub('[kb]', inp)}\n{HIDE.sub('[kb]', o[:a.tool_chars])}"
                            + (" …(cut)" if len(o) > a.tool_chars else "") for n, inp, o in it["tools"])
        parts.append(f"# {aid}\n\n## Question\n{it['prompt']}\n\n## Reference points\n"
                     + "\n".join(f"{j}. {f}" for j, f in enumerate(it["facts"], 1))
                     + f"\n\n## Retrieved\n{tools or '(nothing retrieved)'}\n\n## Answer\n{HIDE.sub('[kb]', it['answer'])}\n")
    if a.parts == 1:
        (out / "sheet.md").write_text("\n\n".join(parts), encoding="utf-8")
    else:
        size = -(-len(parts) // a.parts)
        for k in range(a.parts):
            (out / f"sheet-{k + 1}.md").write_text("\n\n".join(parts[k * size:(k + 1) * size]), encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} answers -> {out / 'sheet.md'} (key in key.json; open it only after grading)")


if __name__ == "__main__":
    main()
