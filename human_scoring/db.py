"""The online server's data in one database: links, questions and answers, ratings, sermon
projects, research costs and the people who use it.

MySQL on the server, SQLite anywhere else (tests, a laptop). The connection comes from
THEOCLAW_DB in .env or the environment, e.g.

    THEOCLAW_DB=mysql+pymysql://theoclaw:PASSWORD@localhost/theoclaw?charset=utf8mb4

and without it a SQLite file, runs/pastor-chat/theoclaw.db. Every row keeps the full record as
JSON in ``data`` (nothing the old files held is lost) plus the columns one queries by.

The evaluation tools still read the old file layout (traces.jsonl, human/<rater>.jsonl);
``export`` writes it from the database, and ``import`` brings existing files in once:

    python human_scoring/db.py import            # assignment.json, runs/pastor-chat/, runs/*/human/
    python human_scoring/db.py export runs_db    # the same layout, for theoclaw.evals
    python human_scoring/db.py stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from sqlalchemy import (JSON, Boolean, Column, Float, Integer, MetaData, String, Table, Text, create_engine,
                        delete, func, insert, select, update)
from sqlalchemy.dialects import mysql

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SQLITE_FILE = ROOT / "runs" / "pastor-chat" / "theoclaw.db"   # git-ignored and never packed

LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")
Json = JSON().with_variant(mysql.JSON(), "mysql")
Number = Float().with_variant(mysql.DOUBLE(asdecimal=False), "mysql")   # money: not single precision
ID = 64      # codes, task ids, project ids
NAME = 191   # "group·nickname#hash" (191 = the longest indexable utf8mb4 VARCHAR on old MySQL)

meta = MetaData()
_opts = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_bin"}   # exact: "Tom" and "tom" are two people

links = Table(
    "links", meta,
    Column("code", String(ID), primary_key=True),
    Column("name", String(NAME), nullable=False),
    Column("is_group", Boolean, nullable=False, default=False),
    Column("role", String(16)),                       # lay / pastor (groups)
    Column("data", Json, nullable=False),             # the whole entry, e.g. the blind order
    **_opts)

users = Table(
    "users", meta,
    Column("name", String(NAME), primary_key=True),   # as recorded: 查經班·小明#1a2b3c4d
    Column("group_name", String(NAME)),
    Column("nick", String(64)),
    Column("role", String(16)),
    Column("denomination", String(64)),
    Column("first_seen", String(20)),
    Column("last_seen", String(20)),
    **_opts)

answers = Table(
    "answers", meta,
    Column("task_id", String(ID), primary_key=True),  # chat-YYYYMMDD-HHMMSS-<job>
    Column("run_index", Integer, nullable=False, default=0),
    Column("kind", String(16), nullable=False),       # question / sermon / sermon_turn / sermon_draft
    Column("asked_by", String(NAME), index=True),
    Column("asked_at", String(20), index=True),
    Column("conv", String(ID), index=True),           # conversation id (questions)
    Column("turn", Integer),
    Column("project", String(ID), index=True),        # sermon project (workspace turns)
    Column("denomination", String(64)),
    Column("prompt", LongText),
    Column("final_text", LongText),
    Column("model", String(64)),
    Column("outcome", String(32)),
    Column("cost_usd", Number),
    Column("latency_s", Number),
    Column("data", Json, nullable=False),             # the full trace: steps, tool calls, usage
    **_opts)

ratings = Table(
    "ratings", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_dir", String(NAME), nullable=False, index=True),   # runs/pastor-chat or a blind-scoring run
    Column("task_id", String(ID), nullable=False, index=True),
    Column("run_index", Integer, nullable=False, default=0),
    Column("rater", String(NAME), nullable=False, index=True),
    Column("overall", Number),                          # the 0–10 score (one-score rubric)
    Column("verdict", Boolean),
    Column("comment", Text),
    Column("mode", String(16)),                        # blind / own / group
    Column("rated_at", String(20)),
    Column("data", Json, nullable=False),              # scores, problems, rubric hash, denomination
    **_opts)

projects = Table(
    "sermon_projects", meta,
    Column("id", String(ID), primary_key=True),
    Column("owner", String(NAME), nullable=False, index=True),
    Column("passage", String(191)),
    Column("theme", Text),
    Column("created", String(20)),
    Column("updated", String(20)),
    Column("data", Json, nullable=False),              # briefs, word study, board, turns, research steps
    **_opts)

costs = Table(
    "costs", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("by_name", String(NAME), index=True),
    Column("kind", String(16)),
    Column("cost_usd", Number),
    Column("project", String(ID)),
    Column("at", String(20)),
    **_opts)


def db_url(sqlite_file: Path = SQLITE_FILE) -> str:
    try:
        from theoclaw.llm.env import load_env
        load_env()
    except Exception:  # noqa: BLE001 - only for reading .env
        pass
    return os.environ.get("THEOCLAW_DB") or f"sqlite:///{Path(sqlite_file).as_posix()}"


CHAT_RUN = "runs/pastor-chat"


def run_key(run_dir: Path, chat_dir: Path | None = None) -> str:
    """Where a rating belongs, the same wherever the files were copied to: the questions asked
    online are runs/pastor-chat, a blind-scoring run is runs/<its folder name>."""
    if chat_dir is not None and Path(run_dir).resolve() == Path(chat_dir).resolve():
        return CHAT_RUN
    return f"runs/{Path(run_dir).name}"


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


class DB:
    """Small, explicit methods; one short transaction each (the server is threaded)."""

    def __init__(self, url: str | None = None, sqlite_file: Path = SQLITE_FILE):
        url = url or db_url(sqlite_file)
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
        kw = {"pool_pre_ping": True, "pool_recycle": 3600}
        if url.startswith("sqlite"):
            kw = {"connect_args": {"check_same_thread": False}}
        self.engine = create_engine(url, **kw)
        meta.create_all(self.engine)
        self.url = self.engine.url.render_as_string(hide_password=True)

    # ---- links
    def links(self) -> dict[str, dict]:
        with self.engine.connect() as c:
            return {r.code: r.data for r in c.execute(select(links))}

    def put_link(self, code: str, entry: dict) -> None:
        row = {"name": entry["name"], "is_group": bool(entry.get("group")), "role": entry.get("role"), "data": entry}
        with self.engine.begin() as c:
            if c.execute(select(links.c.code).where(links.c.code == code)).first():
                c.execute(update(links).where(links.c.code == code).values(**row))
            else:
                c.execute(insert(links).values(code=code, **row))

    # ---- users
    def touch_user(self, r: dict, denomination: str | None = None, at: str | None = None) -> None:
        at = at or _stamp()
        with self.engine.begin() as c:
            old = c.execute(select(users).where(users.c.name == r["name"])).first()
            if old is None:
                c.execute(insert(users).values(name=r["name"], group_name=r.get("group") or None, nick=r.get("nick"),
                                               role=r.get("role") or ("pastor" if not r.get("group") else "lay"),
                                               denomination=denomination, first_seen=at, last_seen=at))
            else:
                vals = {"last_seen": max(old.last_seen or "", at)}
                if denomination:
                    vals["denomination"] = denomination
                c.execute(update(users).where(users.c.name == r["name"]).values(**vals))

    # ---- answers
    def add_answer(self, rec: dict) -> None:
        with self.engine.begin() as c:
            c.execute(insert(answers).values(**_answer_row(rec)))

    def answers(self) -> list[dict]:
        with self.engine.connect() as c:
            return [r.data for r in c.execute(select(answers.c.data).order_by(answers.c.asked_at, answers.c.task_id))]

    # ---- ratings
    def add_rating(self, run_dir: str, rec: dict) -> None:
        with self.engine.begin() as c:
            c.execute(insert(ratings).values(**_rating_row(run_dir, rec)))

    def ratings(self, run_dir: str | None = None, rater: str | None = None) -> list[dict]:
        """Latest rating per (run, rater, task, run index), as the old files were read."""
        q = select(ratings.c.run_dir, ratings.c.data).order_by(ratings.c.id)
        if run_dir is not None:
            q = q.where(ratings.c.run_dir == run_dir)
        if rater is not None:
            q = q.where(ratings.c.rater == rater)
        latest: dict[tuple, dict] = {}
        with self.engine.connect() as c:
            for r in c.execute(q):
                d = r.data
                latest[(r.run_dir, d["rater"], d["task_id"], d["run_index"])] = {**d, "_run_dir": r.run_dir}
        return list(latest.values())

    def all_ratings(self) -> list[tuple[str, dict]]:
        """Every rating ever given, oldest first, as (run_dir, rating)."""
        with self.engine.connect() as c:
            return [(r.run_dir, r.data) for r in c.execute(select(ratings.c.run_dir, ratings.c.data).order_by(ratings.c.id))]

    # ---- sermon projects
    def project(self, pid: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(projects.c.data).where(projects.c.id == pid)).first()
            return r.data if r else None

    def projects(self, owner: str | None = None) -> list[dict]:
        q = select(projects.c.data).order_by(projects.c.created.desc())
        if owner is not None:
            q = q.where(projects.c.owner == owner)
        with self.engine.connect() as c:
            return [r.data for r in c.execute(q)]

    def save_project(self, p: dict) -> None:
        row = {"owner": p["owner"], "passage": p.get("passage"), "theme": p.get("theme"),
               "created": p.get("created"), "updated": _stamp(), "data": p}
        with self.engine.begin() as c:
            if c.execute(select(projects.c.id).where(projects.c.id == p["id"])).first():
                c.execute(update(projects).where(projects.c.id == p["id"]).values(**row))
            else:
                c.execute(insert(projects).values(id=p["id"], **row))

    # ---- costs
    def add_cost(self, rec: dict) -> None:
        with self.engine.begin() as c:
            c.execute(insert(costs).values(by_name=rec["by"], kind=rec["kind"], cost_usd=rec["cost_usd"],
                                           project=rec.get("project"), at=rec["at"]))

    def costs(self) -> list[dict]:
        with self.engine.connect() as c:
            return [{"by": r.by_name, "kind": r.kind, "cost_usd": float(r.cost_usd or 0), "project": r.project, "at": r.at}
                    for r in c.execute(select(costs).order_by(costs.c.id))]

    # ---- summary
    def stats(self) -> dict:
        with self.engine.connect() as c:
            n = {t.name: c.execute(select(func.count()).select_from(t)).scalar() for t in meta.sorted_tables}
            n["spent_usd"] = round(float(c.execute(select(func.sum(answers.c.cost_usd))).scalar() or 0)
                                   + float(c.execute(select(func.sum(costs.c.cost_usd))).scalar() or 0), 4)
        return n


def _answer_row(rec: dict) -> dict:
    return {"task_id": rec["task_id"], "run_index": rec.get("run_index", 0), "kind": rec.get("kind") or "question",
            "asked_by": rec.get("asked_by"), "asked_at": rec.get("asked_at"), "conv": rec.get("conv"),
            "turn": rec.get("turn"), "project": rec.get("project"), "denomination": rec.get("denomination"),
            "prompt": rec.get("prompt"), "final_text": rec.get("final_text"), "model": rec.get("model"),
            "outcome": rec.get("outcome"), "cost_usd": rec.get("cost_usd"), "latency_s": rec.get("latency_s"),
            "data": rec}


def _rating_row(run_dir: str, rec: dict) -> dict:
    scores = rec.get("scores") or {}
    overall = scores.get("overall")
    return {"run_dir": run_dir, "task_id": rec["task_id"], "run_index": rec.get("run_index", 0), "rater": rec["rater"],
            "overall": overall if isinstance(overall, (int, float)) else None, "verdict": rec.get("verdict"),
            "comment": rec.get("comment"), "mode": rec.get("mode"),
            "rated_at": rec.get("rated_at"), "data": rec}


# ---------------------------------------------------------------- moving the old files in and out

def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def import_files(db: DB, assignment: Path, chat_dir: Path, run_dirs: list[Path]) -> dict:
    """Bring the file-based data in. Safe to run again: what is already there is skipped."""
    def rel(p: Path) -> str:
        return run_key(p, chat_dir)

    n = {"links": 0, "answers": 0, "ratings": 0, "projects": 0, "costs": 0}
    if assignment.exists():
        have = db.links()
        for code, entry in json.loads(assignment.read_text(encoding="utf-8")).get("raters", {}).items():
            if code not in have:
                db.put_link(code, entry)
                n["links"] += 1
    have = {a["task_id"] for a in db.answers()}
    for rec in _jsonl(chat_dir / "traces.jsonl"):
        if rec["task_id"] not in have:
            db.add_answer(rec)
            have.add(rec["task_id"])
            n["answers"] += 1
            if rec.get("asked_by"):
                name = rec["asked_by"]
                group, _, nick = name.partition("·") if "·" in name else ("", "", name)
                db.touch_user({"name": name, "group": group or None, "nick": nick.split("#")[0] or None,
                               "role": None if group else "pastor"}, rec.get("denomination"), rec.get("asked_at"))
    seen = {(run_dir, r["rater"], r["task_id"], r["run_index"], r.get("rated_at")) for run_dir, r in db.all_ratings()}
    for d in [chat_dir, *run_dirs]:
        for path in sorted((d / "human").glob("*.jsonl")) if (d / "human").is_dir() else []:
            for rec in _jsonl(path):
                key = (rel(d), rec["rater"], rec["task_id"], rec["run_index"], rec.get("rated_at"))
                if key not in seen:
                    db.add_rating(rel(d), rec)
                    seen.add(key)
                    n["ratings"] += 1
    for path in sorted((chat_dir / "projects").glob("*.json")) if (chat_dir / "projects").is_dir() else []:
        p = json.loads(path.read_text(encoding="utf-8"))
        if db.project(p["id"]) is None:
            db.save_project(p)
            n["projects"] += 1
    have_costs = {(c["by"], c["kind"], c["at"]) for c in db.costs()}
    for rec in _jsonl(chat_dir / "costs.jsonl"):
        if (rec["by"], rec["kind"], rec["at"]) not in have_costs:
            db.add_cost(rec)
            n["costs"] += 1
    return n


def export_files(db: DB, out: Path) -> dict:
    """The old layout under ``out``: <run_dir>/traces.jsonl, <run_dir>/human/<rater>.jsonl,
    pastor-chat/projects/*.json, pastor-chat/costs.jsonl, assignment.json."""
    from theoclaw.evals.human import _safe_name
    out = Path(out)
    chat = out / "runs" / "pastor-chat"
    chat.mkdir(parents=True, exist_ok=True)
    (chat / "config.json").write_text(json.dumps({"kind": "pastor-chat", "n": 1, "label": "pastor-chat"}), encoding="utf-8")
    rows = db.answers()
    (chat / "traces.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    all_ratings = db.all_ratings()  # every rating, not only the latest, as the files kept them
    for run_dir, rec in all_ratings:
        folder = out / run_dir / "human"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{_safe_name(rec['rater'])}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    (chat / "projects").mkdir(exist_ok=True)
    for p in db.projects():
        (chat / "projects" / f"{p['id']}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    (chat / "costs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in db.costs()), encoding="utf-8")
    (out / "assignment.json").write_text(json.dumps({"raters": db.links()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"answers": len(rows), "ratings": len(all_ratings), "projects": len(db.projects()), "folder": str(out)}


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="bring assignment.json, runs/pastor-chat/ and runs/*/human/ into the database")
    p.add_argument("--assignment", default=str(HERE / "assignment.json"))
    p.add_argument("--chat-dir", default=str(ROOT / "runs" / "pastor-chat"))
    p.add_argument("--runs", default=str(ROOT / "runs"), help="folder whose */human/ ratings are imported too")
    p = sub.add_parser("export", help="write the old file layout, for theoclaw.evals")
    p.add_argument("out")
    sub.add_parser("stats", help="rows per table and money spent")
    a = ap.parse_args(argv)
    db = DB()
    print(f"database: {db.url}")
    if a.cmd == "import":
        run_dirs = [d for d in Path(a.runs).iterdir() if (d / "human").is_dir() and d.resolve() != Path(a.chat_dir).resolve()]
        print(import_files(db, Path(a.assignment), Path(a.chat_dir), run_dirs))
    elif a.cmd == "export":
        print(export_files(db, Path(a.out)))
    print(db.stats())


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
