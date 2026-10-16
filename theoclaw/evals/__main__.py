"""Eval command line. Results are printed in full; everything is also saved under runs/.

    python -m theoclaw.evals run --tasks tasks/tasks.yaml --n 5          run, grade, print the report
    python -m theoclaw.evals run --tasks tasks/tasks.example.yaml --model fake-fabricator --n 2   (free)
    python -m theoclaw.evals grade runs/<dir>                           re-grade saved traces (no API calls)
    python -m theoclaw.evals report runs/<dir>
    python -m theoclaw.evals show runs/<dir> [--task ID] [--failed] [--full]
    python -m theoclaw.evals compare runs/<before> runs/<after>         per-task pass-rate change
    python -m theoclaw.evals cost runs/<baseline> runs/<arm> ...        tokens and cost, with intervals
    python -m theoclaw.evals experiment experiments/<file>.yaml         several arms, then cost
    python -m theoclaw.evals human rate|export|import|report ...        human scoring
    python -m theoclaw.evals decide runs/<current> runs/<candidate>      enough evidence to switch?
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..common.paths import RUNS_DIR, TASKS_DIR


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp950/cp936
    ap = argparse.ArgumentParser(prog="theoclaw.evals", description="run, grade and compare the agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="run every task n times, grade, print the report")
    p.add_argument("--tasks", default=str(TASKS_DIR / "tasks.yaml"))
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--model", help="default: the agent role in config/llm.yaml; fake-honest or fake-fabricator are free")
    p.add_argument("--effort", help='default: the agent role in config/llm.yaml; "none" to omit')
    p.add_argument("--tools", default="scripture,wesley", help="tool groups: scripture, wesley, kb")
    p.add_argument("--kb", help="compiled knowledge base for the kb tools: a name in knowledge/ or a path")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--out", default=str(RUNS_DIR))
    p.add_argument("--label", default="")
    p.add_argument("--only", nargs="*", help="task ids to run")
    p.add_argument("--resume", help="continue an interrupted run directory")
    p.add_argument("--no-grade", action="store_true", help="only save the traces")

    p = sub.add_parser("grade", help="grade saved traces with the graders in graders/, print the report")
    p.add_argument("run_dir")
    p.add_argument("--tasks", help="grade against an edited task file instead of the run's snapshot")

    p = sub.add_parser("report", help="write and print report.md for a graded run")
    p.add_argument("run_dir")
    p.add_argument("--k", type=int)

    p = sub.add_parser("show", help="print runs in full: steps, tool calls, answer, grades, tokens")
    p.add_argument("run_dir")
    p.add_argument("--task")
    p.add_argument("--run", type=int, dest="run_index")
    p.add_argument("--failed", action="store_true", help="only runs that did not pass")
    p.add_argument("--full", action="store_true", help="do not shorten tool outputs")

    p = sub.add_parser("compare", help="per-task pass-rate change between two graded runs")
    p.add_argument("base")
    p.add_argument("new")

    p = sub.add_parser("cost", help="tokens and cost per answer across runs, against the first, with intervals")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--volumes", default="100,1000,10000", help="question counts for the total-cost table")

    p = sub.add_parser("experiment", help="run the arms of an experiment file, then compare cost and quality")
    p.add_argument("file")
    p.add_argument("--dry-run", action="store_true", help="check the arms and print the plan")
    p.add_argument("--only", nargs="*", help="arm labels to run")
    p.add_argument("--workers", type=int, default=4)

    p = sub.add_parser("decide", help="is there enough evidence to replace one run's setting with another's?")
    p.add_argument("current")
    p.add_argument("candidate")
    p.add_argument("--rater", default="claude", help="human scores to use (runs/<dir>/human/<rater>.jsonl)")
    p.add_argument("--margin", action="append", default=[], metavar="METRIC=VALUE",
                   help="non-inferiority margin, e.g. human_mean=0.2 usable=0.05")
    p.add_argument("--out", help="also write the report to this file")

    jg = sub.add_parser("judge", help="LLM judge with the human rubric, and how far to trust it").add_subparsers(dest="jcmd", required=True)
    p = jg.add_parser("score", help="score answers; saved as rater judge-<model>")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--model", help="default: the judge role in config/llm.yaml")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=4)
    p = jg.add_parser("pair", help="the two runs' answers side by side, judged in both orders")
    p.add_argument("run_a")
    p.add_argument("run_b")
    p.add_argument("--model")
    p.add_argument("--limit", type=int, help="number of pairs (each judged in both orders), sampled at random")
    p.add_argument("--workers", type=int, default=4)
    p = jg.add_parser("analyze", help="judges against a human rater: agreement, self-preference, length, position")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--human", default="claude")
    p.add_argument("--out")

    gr = sub.add_parser("ground", help="groundedness against the retrieved text (simplified, modelled on RAGAS faithfulness and FActScore)").add_subparsers(dest="gcmd", required=True)
    p = gr.add_parser("score", help="faithfulness, fact recall, context recall, relevance per answer")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--model", help="default: the judge role in config/llm.yaml")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--budget", type=float, help="stop starting new calls once this many USD are spent")
    p = gr.add_parser("cite", help="ALCE-style: does the cited passage or page support the sentence?")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--model")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--budget", type=float)
    p = gr.add_parser("recheck", help="statements unsupported by the retrieved text, checked against the whole book")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--source", required=True, help="knowledge base whose sources/ hold the whole book")
    p.add_argument("--model")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--budget", type=float)
    p = gr.add_parser("spotcheck", help="a blind sheet of the citation checker's verdicts for a person; --score to compare")
    p.add_argument("paths", nargs="+", help="run folders (to make the sheet) or the filled-in sheet (with --score)")
    p.add_argument("--out", help="where to write the sheet (CSV)")
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--model")
    p.add_argument("--score", action="store_true")
    p = gr.add_parser("cite-report", help="citation precision and recheck results per arm")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--model")
    p.add_argument("--out")
    p = gr.add_parser("report", help="per-arm means, by category, and the paired difference of two arms")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--model")
    p.add_argument("--out")

    p = sub.add_parser("monitor", help="real questions: automatic checks vs human scores, rater agreement, coverage")
    p.add_argument("chat_dir", nargs="?", default="runs/pastor-chat")
    p.add_argument("--suite", default="tasks/tasks.yaml", help="the regression suite to compare coverage with")
    p.add_argument("--model", help="default: the judge role in config/llm.yaml")
    p.add_argument("--no-llm", action="store_true", help="free: no groundedness check, no categories")
    p.add_argument("--budget", type=float, help="stop starting groundedness calls once this many USD are spent")
    p.add_argument("--out", help="also write the report to this file")
    p.add_argument("--export-tasks", help="write low-scored or flagged answers as draft regression tasks (YAML)")

    h = sub.add_parser("human", help="human scoring of answers").add_subparsers(dest="hcmd", required=True)
    p = h.add_parser("rate", help="score answers in the terminal")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--rater", required=True)
    p.add_argument("--blind", action="store_true", help="hide model, tools and task ids; shuffle")
    p.add_argument("--redo", action="store_true", help="also show answers this rater already scored")
    p.add_argument("--only", nargs="*", help="task ids")
    p = h.add_parser("export", help="write a CSV sheet (opens in Excel) for scoring outside the terminal")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--blind", action="store_true")
    p.add_argument("--sample", type=int, help="only n answers, the same number per run, spread over the tasks")
    p.add_argument("--flagged-by", help="with --sample: a quarter of each run's answers from those this rater flagged")
    p = h.add_parser("import", help="read a filled-in CSV sheet back")
    p.add_argument("sheet")
    p.add_argument("--rater", required=True)
    p = h.add_parser("report", help="mean scores, agreement with the graders and between raters")
    p.add_argument("run_dir")

    args = ap.parse_args(argv)

    if args.cmd == "run":
        from .report import write_report
        from .runner import grade_run, run_tasks
        run_dir = run_tasks(args.tasks, model=args.model, n=args.n, effort=args.effort, workers=args.workers,
                            out_root=args.out, label=args.label, only=args.only, max_steps=args.max_steps,
                            resume=args.resume, tools=args.tools, kb=args.kb)
        if args.no_grade:
            print(f"next: python -m theoclaw.evals grade {run_dir}")
            return
        grade_run(run_dir)
        print("\n" + write_report(run_dir).read_text(encoding="utf-8"))
        print(f"details of failed runs: python -m theoclaw.evals show {run_dir} --failed")
    elif args.cmd == "grade":
        from .report import write_report
        from .runner import grade_run
        grade_run(args.run_dir, args.tasks)
        print("\n" + write_report(args.run_dir).read_text(encoding="utf-8"))
    elif args.cmd == "report":
        from .report import write_report
        print(write_report(args.run_dir, args.k).read_text(encoding="utf-8"))
    elif args.cmd == "show":
        from .show import show
        print(show(args.run_dir, args.task, args.run_index, args.failed, args.full))
    elif args.cmd == "compare":
        from .report import compare
        print(compare(args.base, args.new))
    elif args.cmd == "cost":
        from .cost import compare_costs
        print(compare_costs(args.run_dirs, tuple(int(v) for v in args.volumes.split(","))))
    elif args.cmd == "experiment":
        from .experiment import load_experiment, plan_text, run_experiment
        print(plan_text(load_experiment(args.file)))
        if not args.dry_run:
            run_experiment(args.file, workers=args.workers, only=args.only)
    elif args.cmd == "decide":
        from .decide import render
        margins = {k: float(v) for k, v in (m.split("=", 1) for m in args.margin)}
        text = render(args.current, args.candidate, args.rater, margins)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(text)
    elif args.cmd == "judge":
        from . import judge
        if args.jcmd == "score":
            print(judge.score(args.run_dirs, args.model, limit=args.limit, workers=args.workers))
        elif args.jcmd == "pair":
            print(judge.pair(args.run_a, args.run_b, args.model, limit=args.limit, workers=args.workers))
        else:
            text = judge.analyze(args.run_dirs, args.human)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            print(text)
    elif args.cmd == "ground":
        from . import ground
        if args.gcmd == "score":
            print(ground.score(args.run_dirs, args.model, workers=args.workers, limit=args.limit, budget_usd=args.budget))
        elif args.gcmd == "spotcheck":
            from . import cite
            if args.score:
                print(cite.spotcheck_score(args.paths[0]))
            else:
                print(f"wrote {cite.spotcheck_make(args.paths, args.out, args.model, args.n)} (and a .key.json next to it)")
        elif args.gcmd in ("cite", "recheck", "cite-report"):
            from . import cite
            if args.gcmd == "cite":
                print(cite.cite(args.run_dirs, args.model, workers=args.workers, budget_usd=args.budget))
            elif args.gcmd == "recheck":
                print(cite.recheck(args.run_dirs, args.source, args.model, workers=args.workers, budget_usd=args.budget))
            else:
                text = cite.report(args.run_dirs, args.model)
                if args.out:
                    Path(args.out).write_text(text, encoding="utf-8")
                print(text)
        else:
            text = ground.report(args.run_dirs, args.model)
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
            print(text)
    elif args.cmd == "monitor":
        from .monitor import export_tasks, monitor
        text, rows = monitor(args.chat_dir, suite=args.suite, model=args.model, llm=not args.no_llm, budget_usd=args.budget)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        if args.export_tasks:
            print(f"wrote {export_tasks(rows, Path(args.export_tasks))} draft tasks to {args.export_tasks}")
        print(text)
    elif args.cmd == "human":
        from . import human
        if args.hcmd == "rate":
            human.rate(args.run_dirs, args.rater, blind=args.blind, redo=args.redo, only=args.only)
        elif args.hcmd == "export":
            path = human.export_csv(args.run_dirs, args.out, blind=args.blind, sample=args.sample,
                                    flagged_by=args.flagged_by)
            print(f"wrote {path} and {path.with_suffix('.key.json')} (keep the key file; raters only need the CSV)")
        elif args.hcmd == "import":
            print(f"imported {human.import_csv(args.sheet, args.rater)} scores")
        else:
            s = human.human_summary(args.run_dir)
            print(human.render_human(s) if s else "no human scores yet")


if __name__ == "__main__":
    main()
