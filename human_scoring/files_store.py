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

    # ---- consent (training use of questions): one stamp per name
    def _consents(self) -> dict:
        path = self.chat_dir / "consents.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def consented(self, name: str) -> bool:
        return bool(self._consents().get(name))

    def record_consent(self, r: dict) -> None:
        import time
        c = self._consents()
        c.setdefault(r["name"], time.strftime("%Y%m%d-%H%M%S"))
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        (self.chat_dir / "consents.json").write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- fellowships (the codes typed on the front page)
    def _fellowships(self) -> dict:
        path = self.chat_dir / "fellowships.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def fellowships(self) -> dict[str, dict]:
        return self._fellowships()

    def fellowship(self, code: str) -> dict | None:
        return self._fellowships().get(code or "")

    def put_fellowship(self, code: str, name: str = "", role: str = "pastor") -> None:
        import time
        code = (code or "").strip()
        if not code or len(code) > 16:
            raise ValueError("團契碼要在 1 到 16 字之間")
        if role not in ("member", "pastor"):
            raise ValueError("role 要 member 或 pastor")
        f = self._fellowships()
        if code not in f:
            f[code] = {"code": code, "name": name, "role": role, "created": time.strftime("%Y%m%d-%H%M%S")}
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            (self.chat_dir / "fellowships.json").write_text(
                json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- Google accounts (cross-device sync; only the salted hash of the Google sub is kept)
    def _accounts(self) -> dict:
        path = self.chat_dir / "google_accounts.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def google_account(self, sub_hash: str) -> dict | None:
        return self._accounts().get(sub_hash or "")

    def put_google_account(self, sub_hash: str, name: str) -> None:
        import time
        a = self._accounts()
        a[sub_hash] = {"sub_hash": sub_hash, "name": name, "created": a.get(sub_hash, {}).get("created")
                       or time.strftime("%Y%m%d-%H%M%S"), "last_login": time.strftime("%Y%m%d-%H%M%S")}
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        (self.chat_dir / "google_accounts.json").write_text(
            json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")

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

    # ---- shares: one answer behind a read-only link (shares.json, token -> row)
    def _shares(self) -> dict:
        path = self.chat_dir / "shares.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save_shares(self, s: dict) -> None:
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        (self.chat_dir / "shares.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")

    def add_share(self, token: str, task_id: str, owner: str) -> None:
        import time
        s = self._shares()
        s[token] = {"token": token, "task_id": task_id, "owner": owner, "created": time.strftime("%Y%m%d-%H%M%S"),
                    "revoked_at": None, "views": 0}
        self._save_shares(s)

    def share(self, token: str) -> dict | None:
        return self._shares().get(token or "")

    def shares(self, owner: str) -> list[dict]:
        return sorted((r for r in self._shares().values() if r["owner"] == owner), key=lambda r: r["created"])

    def revoke_share(self, token: str) -> None:
        import time
        s = self._shares()
        if token in s:
            s[token]["revoked_at"] = time.strftime("%Y%m%d-%H%M%S")
            self._save_shares(s)

    def view_share(self, token: str) -> None:
        s = self._shares()
        if token in s:
            s[token]["views"] = s[token].get("views", 0) + 1
            self._save_shares(s)

    # ---- identities: recovery after a browser lost its key
    def identities(self, group: str) -> list[dict]:
        seen: dict[str, dict] = {}
        for rec in self.answers():
            name = rec.get("asked_by") or ""
            if name.startswith(group + "·"):
                p = seen.setdefault(name, {"name": name, "nick": name.split("·", 1)[1].split("#")[0],
                                           "first_seen": rec.get("asked_at"), "last_seen": rec.get("asked_at"), "answers": 0})
                p["answers"] += 1
                p["last_seen"] = max(p["last_seen"] or "", rec.get("asked_at") or "")
        return sorted(seen.values(), key=lambda p: p["last_seen"] or "", reverse=True)

    def _tokens(self) -> dict:
        path = self.chat_dir / "recover_tokens.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save_tokens(self, t: dict) -> None:
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        (self.chat_dir / "recover_tokens.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")

    def add_recover_token(self, token_hash: str, old_name: str, group: str, expires: str) -> None:
        t = self._tokens()
        t[token_hash] = {"old_name": old_name, "group_name": group, "expires": expires, "used_by": None}
        self._save_tokens(t)

    def take_recover_token(self, token_hash: str, new_name: str) -> str | None:
        import time
        t = self._tokens()
        r = t.get(token_hash)
        if r is None or r["used_by"] or r["expires"] < time.strftime("%Y%m%d-%H%M%S"):
            return None
        r["used_by"] = new_name
        self._save_tokens(t)
        return r["old_name"]

    def rename_identity(self, old: str, new: str) -> int:
        """Every record of ``old`` becomes ``new``'s, rewriting the files."""
        from theoclaw.evals.human import _safe_name
        if old == new:
            return 0
        n = 0
        rows = self.answers()
        for rec in rows:
            if rec.get("asked_by") == old:
                rec["asked_by"] = new
                n += 1
        if n:
            (self.chat_dir / "traces.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                       encoding="utf-8")
        for d in self.dirs.values():
            src = d / "human" / f"{_safe_name(old)}.jsonl"
            if src.exists():
                recs = [{**r, "rater": new} for r in _jsonl(src)]
                with open(d / "human" / f"{_safe_name(new)}.jsonl", "a", encoding="utf-8") as f:
                    f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
                src.unlink()
                n += len(recs)
        for p in self.projects(old):
            self.save_project({**p, "owner": new})
            n += 1
        costs = self.costs()
        if any(c["by"] == old for c in costs):
            (self.chat_dir / "costs.jsonl").write_text(
                "".join(json.dumps({**c, "by": new} if c["by"] == old else c, ensure_ascii=False) + "\n" for c in costs),
                encoding="utf-8")
        shares = self._shares()
        if any(r["owner"] == old for r in shares.values()):
            self._save_shares({t: {**r, "owner": new} if r["owner"] == old else r for t, r in shares.items()})
        consents = self._consents()
        if old in consents:  # the agreement follows the person into the account
            consents.setdefault(new, consents.pop(old))
            (self.chat_dir / "consents.json").write_text(
                json.dumps(consents, ensure_ascii=False, indent=1), encoding="utf-8")
        return n

    def stats(self) -> dict:
        return {"links": len(self.links()), "answers": len(self.answers()), "ratings": len(self.all_ratings()),
                "sermon_projects": len(self.projects()), "costs": len(self.costs())}
