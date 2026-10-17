"""The server's data in plain files, the layout used before the database (and still read by
theoclaw.evals): assignment.json for links, runs/pastor-chat/traces.jsonl for questions and
answers, <run>/human/<rater>.jsonl for ratings, runs/pastor-chat/projects/*.json for sermons,
runs/pastor-chat/costs.jsonl for research costs.

Same methods as human_scoring.db.DB, so the server runs on either (`serve --storage files|db`).
"""

from __future__ import annotations

import json
from pathlib import Path

from human_scoring.db import CHAT_RUN, run_key


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


class FileStore:
    def __init__(self, assignment: Path, chat_dir: Path):
        self.assignment, self.chat_dir = Path(assignment), Path(chat_dir)
        self.dirs: dict[str, Path] = {CHAT_RUN: self.chat_dir}   # rating key -> folder
        self.url = f"files ({self.chat_dir})"

    def register(self, run_dir: Path) -> None:
        """A blind-scoring run whose human/ ratings are read and written."""
        self.dirs[run_key(run_dir, self.chat_dir)] = Path(run_dir)

    # ---- links
    def _assignment(self) -> dict:
        return json.loads(self.assignment.read_text(encoding="utf-8")) if self.assignment.exists() else {"items": [], "raters": {}}

    def links(self) -> dict[str, dict]:
        return self._assignment().get("raters", {})

    def put_link(self, code: str, entry: dict) -> None:
        data = self._assignment()
        if data.setdefault("raters", {}).get(code) != entry:
            data["raters"][code] = entry
            self.assignment.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def touch_user(self, r: dict, denomination: str | None = None, at: str | None = None, lang: str | None = None) -> None:
        pass  # the files have no users table; who asked is in each answer and rating

    # ---- answers
    def add_answer(self, rec: dict) -> None:
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        cfg = self.chat_dir / "config.json"
        if not cfg.exists():
            cfg.write_text(json.dumps({"kind": "pastor-chat", "model": rec.get("model"), "n": 1, "label": "pastor-chat",
                                       "toolset": rec.get("toolset")}, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(self.chat_dir / "traces.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def answers(self) -> list[dict]:
        return _jsonl(self.chat_dir / "traces.jsonl")

    # ---- ratings
    def add_rating(self, key: str, rec: dict) -> None:
        from theoclaw.evals.human import _safe_name
        folder = self.dirs.get(key, self.chat_dir) / "human"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{_safe_name(rec['rater'])}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def all_ratings(self) -> list[tuple[str, dict]]:
        out = []
        for key, d in self.dirs.items():
            for path in sorted((d / "human").glob("*.jsonl")) if (d / "human").is_dir() else []:
                out += [(key, r) for r in _jsonl(path)]
        return sorted(out, key=lambda x: str(x[1].get("rated_at", "")))

    def ratings(self, run_dir: str | None = None, rater: str | None = None) -> list[dict]:
        latest: dict[tuple, dict] = {}
        for key, r in self.all_ratings():
            if (run_dir is None or key == run_dir) and (rater is None or r["rater"] == rater):
                latest[(key, r["rater"], r["task_id"], r["run_index"])] = {**r, "_run_dir": key}
        return list(latest.values())

    # ---- sermon projects
    def _projects_dir(self) -> Path:
        return self.chat_dir / "projects"

    def project(self, pid: str) -> dict | None:
        path = self._projects_dir() / f"{pid}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def projects(self, owner: str | None = None) -> list[dict]:
        out = [json.loads(p.read_text(encoding="utf-8")) for p in self._projects_dir().glob("*.json")] \
            if self._projects_dir().is_dir() else []
        return sorted((p for p in out if owner is None or p.get("owner") == owner), key=lambda p: p.get("created", ""), reverse=True)

    def save_project(self, p: dict) -> None:
        self._projects_dir().mkdir(parents=True, exist_ok=True)
        (self._projects_dir() / f"{p['id']}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")

    # ---- costs
    def add_cost(self, rec: dict) -> None:
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        with open(self.chat_dir / "costs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def costs(self) -> list[dict]:
        return _jsonl(self.chat_dir / "costs.jsonl")

    def stats(self) -> dict:
        return {"links": len(self.links()), "answers": len(self.answers()), "ratings": len(self.all_ratings()),
                "sermon_projects": len(self.projects()), "costs": len(self.costs())}
