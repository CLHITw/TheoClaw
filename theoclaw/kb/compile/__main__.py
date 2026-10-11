"""Command line for compiling knowledge bases (see theoclaw/kb/compile/__init__.py)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import LANGUAGES, PROFILES_FILE, compile_kb, describe_inputs, load_profiles, make_plan, prepare_inputs
from ...common.zh import pad
from .sources import find_source, pdf_outline


def _money(x) -> str:
    return f"${x:.2f}" if isinstance(x, (int, float)) else "–（價格表沒有這個模型）"


def cmd_profiles(profiles_file: Path, source_dir: str | None) -> None:
    cfg = load_profiles(profiles_file)
    src = Path(source_dir or cfg.get("source_dir") or ".")
    d = cfg.get("defaults") or {}
    from ...llm import role
    print(f"source folder: {src}{'' if src.is_dir() else '  (NOT FOUND)'}")
    print(f"defaults: compile model {role('compile').litellm_model} (config/llm.yaml), language {d.get('language')}\n")
    for name, p in (cfg.get("profiles") or {}).items():
        print(f"{name}: {p.get('description', '')}")
        for s in p.get("sources") or []:
            if s.get("wesley_nt_notes"):
                print("    ✓ Wesley NT notes (data/wesley_nt.json, parsed from the 03 PDF)")
                continue
            try:
                found = "✓" if src.is_dir() and find_source(src, s["file"]) else "✗"
            except FileNotFoundError:
                found = "✗ missing"
            extra = "".join(f" {k}={s[k]}" for k in ("pages", "outline", "to_text", "s2t", "name") if k in s)
            print(f"    {found} {s['file']}{extra}")
        print()


def cmd_outline(file: str, source_dir: str | None, profiles_file: Path) -> None:
    src = Path(source_dir or load_profiles(profiles_file).get("source_dir") or ".")
    path = Path(file) if Path(file).is_file() else find_source(src, file)
    entries, total = pdf_outline(path)
    print(f"{path.name}: {total} pages, {len(entries)} bookmarks")
    for level, title, page in entries:
        print(f"{'  ' * level}{title}  p.{page if page else '?'}")


def cmd_build(args) -> None:
    plan = make_plan(args.profile, model=args.model, language=args.language, name=args.name,
                     source_dir=args.source_dir, profiles_file=args.profiles)
    print(f"build {plan.name}\n  profile {plan.profile}: {plan.description}\n  compile model {plan.model} · "
          f"wiki language {plan.language} · sources from {plan.source_dir}\n  -> {plan.root}")
    plan.root.mkdir(parents=True, exist_ok=True)
    inputs = prepare_inputs(plan)
    counter = None
    if args.count_tokens is not None:
        from ...llm import token_counter
        counter, why_not = token_counter(args.count_tokens or None)
        args.count_tokens = counter.model if counter else None
        if why_not:
            print(why_not)
    rows = describe_inputs(inputs, counter)
    print(f"\n{'input':56} {'kind':5} {'pages':>6} {'chars':>9} {'tokens':>9}")
    for r in rows:
        print(f"{pad(r['file'][:40], 56)} {r['kind']:5} {r['pages'] or '':>6} {r['chars']:>9} {r['tokens'] if r['tokens'] is not None else '':>9}")
    total_chars = sum(r["chars"] for r in rows)
    total_tokens = sum(r["tokens"] or 0 for r in rows)
    print(f"{'total':56} {'':5} {'':>6} {total_chars:>9} {total_tokens if counter else '':>9}")
    if counter:
        print(f"(tokens counted with {args.count_tokens}'s tokenizer; OpenKB reads each input several times "
              f"while compiling, so the compile itself uses a multiple of this)")
    (plan.root / "inputs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.dry_run:
        print("\ndry run: inputs prepared, nothing compiled")
        return
    m = compile_kb(plan, inputs, to_traditional=not args.keep_simplified)
    last = m["runs"][-1]
    print(f"\ncompiled {plan.name}: {last['calls']} LLM calls this run, {last['duration_s']:.0f}s, cost {_money(last['cost_usd'])}")
    u = m["usage"]
    print(f"all runs: {m['calls']} calls · input {u.get('input_tokens', 0)} · cache write {u.get('cache_creation_input_tokens', 0)}"
          f" · cache read {u.get('cache_read_input_tokens', 0)} · output {u.get('output_tokens', 0)} tokens · {_money(m['cost_usd'])}")
    for f, t in last["per_input"].items():
        print(f"  {pad(f[:40], 56)} {t['calls']:>4} calls  {_money(t['cost_usd'])}")
    if last["failed_inputs"]:
        print(f"failed inputs: {[f['file'] for f in last['failed_inputs']]} (run the same command again to retry them)")
    tc = m.get("traditional_check")
    if tc and tc.get("checked"):
        print(f"繁體 check: {tc['pages_with_simplified']} pages had Simplified characters"
              + (f", converted {len(tc['converted'])}" if tc["converted"] else ""))
    wm = m.get("wiki_metrics")
    if wm:
        rate = lambda x: "–" if x is None else f"{100 * x:.0f}%"
        print(f"wiki: {wm['pages']['summaries']} summaries, {wm['pages']['concepts']} concepts, "
              f"{wm['pages']['entities']} entities · broken links {rate(wm['broken_link_rate'])} · "
              f"in index {rate(wm['index_coverage'])} · frontmatter ok {rate(wm['frontmatter_ok'])}")
    print(f"\nnext: python -m theoclaw.kb.query ls   |   python -m theoclaw.kb.query census {plan.name} --tokens")


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--profiles", default=str(PROFILES_FILE), help="profile file (default config/kb_profiles.yaml)")
    shared.add_argument("--source-dir", help="the Methodist folder (default: source_dir in the profile file)")
    ap = argparse.ArgumentParser(prog="theoclaw.kb.compile", description="compile Methodist sources into an OpenKB wiki")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("profiles", parents=[shared], help="list profiles and check their source files exist")
    p = sub.add_parser("outline", parents=[shared], help="print a PDF's bookmarks with page numbers (to pick pages or outline:)")
    p.add_argument("file")
    p = sub.add_parser("build", parents=[shared], help="prepare the inputs and compile them with OpenKB")
    p.add_argument("profile")
    p.add_argument("--model", help="compile model, e.g. qwen3.8-max or deepseek-flash "
                                   "(default: the compile role in config/llm.yaml)")
    p.add_argument("--language", choices=list(LANGUAGES), help="wiki language (default: from the profile file)")
    p.add_argument("--name", help="output folder name in knowledge/ (default <profile>.<language>.<model>)")
    p.add_argument("--dry-run", action="store_true", help="prepare and measure the inputs, compile nothing")
    p.add_argument("--count-tokens", nargs="?", const="", metavar="MODEL",
                   help="also count input tokens (free count_tokens; Claude models only)")
    p.add_argument("--keep-simplified", action="store_true",
                   help="do not convert Simplified characters in compiled zh-Hant pages to 繁體")
    args = ap.parse_args(argv)
    if args.cmd == "profiles":
        cmd_profiles(Path(args.profiles), args.source_dir)
    elif args.cmd == "outline":
        cmd_outline(args.file, args.source_dir, Path(args.profiles))
    else:
        cmd_build(args)


if __name__ == "__main__":
    main()
