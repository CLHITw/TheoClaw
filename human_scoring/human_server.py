"""TheoClaw 線上人工評分：讓牧者用瀏覽器盲評 agent 的回答。

準備一批要評的回答，並給每位評分人一條專屬連結：

    python human_scoring/human_server.py prepare runs/<a> runs/<b> --sample 40 --flagged-by claude \
        --raters 王牧師,李傳道

啟動伺服器（預設只聽本機；對外請經 Cloudflare Tunnel 等 https 通道）：

    python human_scoring/human_server.py serve --port 8000

每評完一題立即寫入 runs/<run>/human/<評分人>.jsonl（與 `evals human` 同一格式），
所以 `python -m theoclaw.evals human report runs/<run>` 直接比較牧者、Claude 與 LLM 裁判。
評分人看不到模型、任務編號或來源，順序每人各自打亂；可隨時離開，下次從未評的題目繼續。

提問模式（serve --chat）：評分人用同一條連結自己提問，agent 當場回答（預設 deepseek-flash），
再用同一套標準評分。問題與回答存到 runs/pastor-chat/（與評測同一格式），評分存在它的 human/。
每人每天有題數上限，總花費超過上限就停止回答。這個模式要在 .env 放 DEEPSEEK_API_KEY。
"""

from __future__ import annotations

import argparse
import re
import json
import random
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from theoclaw.evals.human import (Item, calibration_sample, load_items, load_ratings,  # noqa: E402
                                  load_rubric, save_rating)

RUBRIC_10 = ROOT / "config" / "human_rubric_10.yaml"   # 預設：一個 0–10 分；--rubric 可換回五項評分
ASSIGNMENT = HERE / "assignment.json"   # 評分名單與連結代碼；不要外流
CHAT_DIR = ROOT / "runs" / "pastor-chat"
SERMON_TIMEOUT = 600
WS_TIMEOUT = {"sermon_start": 360, "sermon_turn": 300, "sermon_draft": 420}   # 講章工作區各步驟的等候上限（秒）
WS_TURN_LIMIT = 60       # 每位牧者每天在講章工作區最多問幾次
PROJECT_ID = re.compile(r"^[0-9a-f]{12}$")                     # 講道預備要跑研究、寫作、查核，約 3 分鐘
SERMON_KB = "plain-account-pdf.en.deepseek-flash"   # 衛斯理傳統研究用的知識庫（knowledge/ 底下）
CHAT_TIMEOUT = 300                       # 秒；超過就告訴提問者失敗（背景的回答若之後完成仍會存檔）
CHAT_MODEL = "deepseek-flash"            # 提問模式預設模型；不跟 config/llm.yaml 走，換模型要明確指定
PAGE = HERE / "human-scoring.html"
MAX_BODY = 64 * 1024
# 宗派：在輸入稱呼時選一次，記在提問與評分裡。現在只作記錄，回答仍以循道衛理立場為主；
# 之後可按宗派選用對應的 wiki，「無宗派」則用所有承認三位一體信仰的傳統。
DENOMINATIONS = ["循道衛理 Methodist", "聖公會 Anglican", "浸信會 Baptist", "長老會／改革宗 Presbyterian / Reformed",
                 "信義會 Lutheran", "五旬節／靈恩 Pentecostal / Charismatic", "天主教 Catholic", "東正教 Orthodox",
                 "無宗派 Non-denominational", "其他 Other"]
GROUP_SEP = "·"            # rater name of a group member: 查經班·小明
GROUP_DAYS = 2             # a group member also sees (and may score) the group's questions of the last two days
_NICK = re.compile(r"^[^\x00-\x1f<>&\"'/\\·]{1,20}$")

# 「主要問題」：評分人勾選答案的毛病，日後可直接變成回歸測試題
PROBLEMS = [
    {"key": "scripture_wrong", "label": "經文引錯或出處錯"},
    {"key": "scripture_memory", "label": "經文不是查來的（憑記憶寫）"},
    {"key": "wesley_invented", "label": "捏造或曲解衛斯理"},
    {"key": "fact_wrong", "label": "史實、教義或條文錯誤"},
    {"key": "not_honest", "label": "查不到卻沒有說明"},
    {"key": "layers_mixed", "label": "經文、註釋與推論混在一起"},
    {"key": "shallow", "label": "空泛、沒有幫助"},
    {"key": "off_topic", "label": "答非所問"},
    {"key": "too_long", "label": "太長或重複"},
    {"key": "language", "label": "語言問題（簡體、夾雜、不通順）"},
    {"key": "tradition", "label": "不符合循道衛理傳統"},
]


# ---------------------------------------------------------------- assignment

def _rel(p: Path) -> str:
    """Run folders inside the project are stored relative to it, so the assignment works on another machine."""
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def _abs(s: str) -> Path:
    p = Path(s)
    return p if p.is_absolute() else ROOT / p


def prepare(run_dirs: list[str], raters: list[str], sample: int | None, flagged_by: str | None,
            path: Path = ASSIGNMENT) -> dict:
    """Pick the answers, give each rater a secret code and an own shuffled order."""
    items = load_items(run_dirs)
    if sample:
        items = calibration_sample(items, sample, flagged_by)
    entries = [{"id": it.item_id, "run_dir": _rel(it.run_dir), "task_id": it.key[0],
                "run_index": it.key[1]} for it in items]
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"raters": {}}
    rater_codes = {c: r for c, r in old.get("raters", {}).items() if r.get("group")}  # group links survive
    for name in raters:
        code = next((c for c, r in old.get("raters", {}).items() if r["name"] == name), None) or secrets.token_urlsafe(9)
        order = [e["id"] for e in entries]
        random.Random(code).shuffle(order)
        rater_codes[code] = {"name": name, "order": order}
    data = {"items": entries, "raters": rater_codes}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


ROLES = ("lay", "pastor")  # 平信徒連結只能提問；牧者連結另有講道預備，也只有它用得到牧者參考資料


def add_group(name: str, path: Path = ASSIGNMENT, role: str = "lay") -> str:
    """Add (or find) a shared group link in the assignment; returns its code."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"items": [], "raters": {}}
    for code, r in data["raters"].items():
        if r.get("group") and r["name"] == name:
            return code
    code = secrets.token_urlsafe(9)
    data["raters"][code] = {"name": name, "order": [], "group": True, "role": role}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return code


class Store:
    """The assignment plus the items it names, loaded once; ratings go straight to disk."""

    def __init__(self, path: Path = ASSIGNMENT, chat: dict | None = None, chat_dir: Path = CHAT_DIR,
                 rubric: Path = RUBRIC_10):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.raters = data["raters"]
        self.rubric = load_rubric(rubric)
        self.items: dict[str, Item] = {}
        # Items are keyed by the id written in the assignment, not recomputed: Item.item_id hashes
        # the folder's absolute path, which differs on the server the assignment is copied to.
        by_dir: dict[str, dict] = {}
        for e in data["items"]:
            by_dir.setdefault(e["run_dir"], {})[(e["task_id"], e["run_index"])] = e["id"]
        for d, ids in by_dir.items():
            for it in load_items([_abs(d)]):
                if it.key in ids:
                    self.items[ids[it.key]] = it
        self.lock = threading.Lock()
        self.chat = chat  # {"model", "daily_limit", "budget_usd"} or None
        self.chat_dir = chat_dir
        self.jobs: dict[str, dict] = {}
        self.owner: dict[str, str] = {}  # chat item id -> rater name
        if (chat_dir / "traces.jsonl").exists():
            for it in load_items([chat_dir]):
                self.items[it.item_id] = it
                self.owner[it.item_id] = it.trace.get("asked_by", "")

    def rater(self, code: str) -> dict | None:
        return self.raters.get(code or "")

    def who(self, code: str, nick: str | None = None) -> dict | None:
        """The rater behind a request. A personal link is the rater; a group link plus a
        nickname is one member of the group, recorded as 「群組·暱稱」. None: group link
        without a valid nickname yet."""
        r = self.raters[code]
        if not r.get("group"):
            return r
        nick = (nick or "").strip()
        if not _NICK.match(nick):
            return None
        return {"name": f"{r['name']}{GROUP_SEP}{nick}", "order": [], "group": r["name"], "role": r.get("role", "lay")}

    @staticmethod
    def is_pastor(r: dict) -> bool:
        """Personal links are the pastors' (and the project owner's); a group link by its role."""
        return not r.get("group") or r.get("role") == "pastor"

    def _group_items(self, group: str) -> list[str]:
        since = time.strftime("%Y%m%d", time.localtime(time.time() - GROUP_DAYS * 86400))
        return sorted((i for i, n in self.owner.items()
                       if n.startswith(group + GROUP_SEP) and str(self.items[i].trace.get("asked_at", "")) >= since),
                      key=lambda i: self.items[i].trace.get("asked_at", ""))

    def done(self, name: str) -> dict[str, dict]:
        """item id -> latest rating by this rater."""
        out = {}
        for item_id, it in self.items.items():
            for r in load_ratings(it.run_dir):
                if r["rater"] == name and (r["task_id"], r["run_index"]) == it.key:
                    out[item_id] = r
        return out

    def state(self, code: str, nick: str | None = None) -> dict:
        r = self.who(code, nick)
        if r is None:
            return {"need_name": True, "group": self.raters[code]["name"], "denominations": DENOMINATIONS}
        done = self.done(r["name"])
        chat = None
        if self.chat:
            mine = sorted((i for i, n in self.owner.items() if n == r["name"]),
                          key=lambda i: self.items[i].trace.get("asked_at", ""))
            chat = {"remaining_today": max(0, self.chat["daily_limit"] - self._today(r["name"])),
                    "open": self._spent() < self.chat["budget_usd"],
                    "questions": [{"id": i, "prompt": self.items[i].trace["prompt"][:80], "rated": i in done,
                                   "kind": self.items[i].trace.get("kind", "question")} for i in mine]}
            if self.is_pastor(r) and self.chat.get("sermon_daily_limit"):
                chat["sermon"] = {"remaining_today": max(0, self.chat["sermon_daily_limit"] - self._today(r["name"], "sermon_start"))}
            if r.get("group"):  # the others' questions, so answers get more than one rater
                chat["others"] = [{"id": i, "prompt": self.items[i].trace["prompt"][:80], "rated": i in done}
                                  for i in self._group_items(r["group"]) if self.owner[i] != r["name"]]
        return {"rater": r["name"], "order": r["order"], "done": sorted(i for i in done if i in r["order"]),
                "problems": PROBLEMS, "chat": chat, "denominations": DENOMINATIONS,
                "rubric": {"scale": self.rubric["scale"], "verdict": self.rubric["verdict"],
                           "allow_na": self.rubric.get("allow_na", True), "anchors": self.rubric.get("anchors", []),
                           "dimensions": [{k: d[k] for k in ("key", "name", "question")} for d in self.rubric["dimensions"]]}}

    def item(self, code: str, item_id: str, nick: str | None = None) -> dict | None:
        r = self.who(code, nick)
        if r is None or not self._allowed(r, item_id):
            return None
        t = self.items[item_id].trace
        calls = [{"name": c["name"], "input": c["input"], "output": c["output"], "is_error": c["is_error"]}
                 for s in t["steps"] for c in s["tool_calls"]]
        prev = self.done(r["name"]).get(item_id)
        chat = item_id in self.owner
        extra = {k: t[k] for k in ("kind", "briefs", "word_study", "check_summary", "revised", "project", "ask") if k in t}
        return {**extra, "id": item_id, "chat": chat,
                "position": None if chat else r["order"].index(item_id) + 1, "total": len(r["order"]),
                "prompt": t["prompt"], "tools": calls, "answer": t.get("final_text") or "（沒有回答）",
                "previous": None if prev is None else {k: prev.get(k) for k in ("scores", "verdict", "comment", "problems")}}

    def rate(self, code: str, body: dict, nick: str | None = None) -> str | None:
        """Validate and save one rating; returns an error message or None."""
        r = self.who(code, nick)
        if r is None:
            return "請先輸入您的稱呼"
        item = self.items.get(body.get("id"))
        if item is None or not self._allowed(r, body.get("id")):
            return "找不到這一題"
        chat = body.get("id") in self.owner
        lo, hi = self.rubric["scale"]["min"], self.rubric["scale"]["max"]
        scores = {}
        for d in self.rubric["dimensions"]:
            v = (body.get("scores") or {}).get(d["key"], "missing")
            if v == "missing":
                return f"「{d['name']}」還沒有評分"
            if v is None and not self.rubric.get("allow_na", True):
                return f"「{d['name']}」需要打分"
            if v is not None and not (isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi):
                return f"「{d['name']}」的分數無效"
            scores[d["key"]] = v
        auto = self.rubric["verdict"].get("auto_min")
        verdict = (scores[self.rubric["dimensions"][0]["key"]] >= auto) if auto is not None else body.get("verdict")
        if verdict not in (True, False):
            return "請選擇總評"
        keys = {p["key"] for p in PROBLEMS}
        problems = [p for p in body.get("problems") or [] if p in keys]
        comment = str(body.get("comment") or "")[:2000]
        mode = "blind" if not chat else ("own" if self.owner.get(body.get("id")) == r["name"] else "group")
        extra = {"problems": problems, "via": "human_server", "mode": mode}
        if body.get("denomination") in DENOMINATIONS:
            extra["denomination"] = body["denomination"]
        with self.lock:
            save_rating(item, r["name"], scores, verdict, comment, blind=not chat, rubric=self.rubric, extra=extra)
        return None

    # ------------------------------------------------------------ chat mode

    def _allowed(self, r: dict, item_id: str) -> bool:
        if item_id not in self.items:
            return False
        if item_id in r["order"] or self.owner.get(item_id) == r["name"]:
            return True
        return bool(r.get("group")) and item_id in self._group_items(r["group"])

    def _chat_traces(self) -> list[dict]:
        return [self.items[i].trace for i in self.owner]

    def _costs(self) -> list[dict]:
        path = self.chat_dir / "costs.jsonl"
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []

    def _spent(self) -> float:
        return sum(t.get("cost_usd") or 0.0 for t in self._chat_traces()) + sum(c["cost_usd"] for c in self._costs())

    def _today(self, name: str, kind: str = "question") -> int:
        today = time.strftime("%Y%m%d")
        asked = sum(1 for t in self._chat_traces()
                    if t.get("asked_by") == name and str(t.get("asked_at", "")).startswith(today)
                    and t.get("kind", "question") == kind)
        asked += sum(1 for c in self._costs() if c["by"] == name and c["kind"] == kind and c["at"].startswith(today))
        running = sum(1 for j in self.jobs.values()
                      if j["name"] == name and j["status"] == "running" and j.get("kind", "question") == kind)
        return asked + running

    def _today_group(self, group: str) -> int:
        today = time.strftime("%Y%m%d")
        asked = sum(1 for t in self._chat_traces()
                    if str(t.get("asked_by", "")).startswith(group + GROUP_SEP) and str(t.get("asked_at", "")).startswith(today))
        return asked + sum(1 for j in self.jobs.values() if j["name"].startswith(group + GROUP_SEP) and j["status"] == "running")

    def ask(self, code: str, question: str, runner=None, nick: str | None = None,
            denomination: str | None = None) -> dict:
        """Start answering in the background; returns {"job": id} or {"error": ...}."""
        if not self.chat:
            return {"error": "提問模式沒有開啟"}
        r = self.who(code, nick)
        if r is None:
            return {"error": "請先輸入您的稱呼"}
        question = (question or "").strip()
        if not 2 <= len(question) <= 1000:
            return {"error": "問題請在 2 到 1000 字之間"}
        with self.lock:
            if self._spent() >= self.chat["budget_usd"]:
                return {"error": "本次測試的提問額度已用完，謝謝您的參與"}
            if self._today(r["name"]) >= self.chat["daily_limit"]:
                return {"error": f"今天已問了 {self.chat['daily_limit']} 題，請明天再來"}
            group_limit = self.chat.get("group_daily_limit")
            if r.get("group") and group_limit and self._today_group(r["group"]) >= group_limit:
                return {"error": "今天團契的提問額度已用完，請明天再來"}
            job = secrets.token_hex(6)
            self.jobs[job] = {"name": r["name"], "status": "running", "item": None, "error": None,
                              "started": time.time()}
        denom = denomination if denomination in DENOMINATIONS else None
        threading.Thread(target=self._answer, args=(job, r["name"], question, runner, denom), daemon=True).start()
        return {"job": job}

    def sermon(self, code: str, body: dict, runner=None, nick: str | None = None) -> dict:
        """Start a sermon preparation (pastors' personal links only)."""
        if not self.chat or not self.chat.get("sermon_daily_limit"):
            return {"error": "講道預備沒有開啟"}
        r = self.who(code, nick)
        if r is None or not self.is_pastor(r):
            return {"error": "講道預備只開放給牧者連結"}
        f = {k: str(body.get(k) or "").strip() for k in ("passage", "theme", "audience", "length", "notes")}
        if not 2 <= len(f["passage"]) <= 60:
            return {"error": "請填寫經文（例如：路加福音 15:11-32）"}
        if any(len(v) > 300 for v in f.values()):
            return {"error": "每一欄請在 300 字以內"}
        with self.lock:
            if self._spent() >= self.chat["budget_usd"]:
                return {"error": "本次測試的額度已用完，謝謝您的參與"}
            if self._today(r["name"], "sermon") >= self.chat["sermon_daily_limit"]:
                return {"error": f"今天已預備了 {self.chat['sermon_daily_limit']} 篇，請明天再來"}
            job = secrets.token_hex(6)
            self.jobs[job] = {"name": r["name"], "status": "running", "item": None, "error": None,
                              "started": time.time(), "kind": "sermon", "timeout": SERMON_TIMEOUT}
        run = runner or (lambda _q: self._run_sermon(f))
        from theoclaw.agent.sermon import request_text
        question = request_text(f["passage"], f["theme"], f["audience"], f["length"], f["notes"])
        threading.Thread(target=self._answer, args=(job, r["name"], question, run, body.get("denomination") if body.get("denomination") in DENOMINATIONS else None),
                         daemon=True).start()
        return {"job": job}

    def _run_sermon(self, f: dict) -> dict:
        from theoclaw.agent.sermon import prepare
        kb = self.chat.get("sermon_kb")
        if kb and not (ROOT / "knowledge" / kb / "wiki" / "index.md").is_file():
            kb = None  # the knowledge base was not deployed: Wesley's notes only
        return prepare(f["passage"], theme=f["theme"], audience=f["audience"], length=f["length"], notes=f["notes"],
                       model=self.chat["model"], kb=kb)

    # ------------------------------------------------------------ sermon workspace (pastors)

    def _projects_dir(self) -> Path:
        return self.chat_dir / "projects"

    def _project(self, r: dict, pid: str) -> dict | None:
        if not PROJECT_ID.match(pid or ""):
            return None
        path = self._projects_dir() / f"{pid}.json"
        if not path.is_file():
            return None
        p = json.loads(path.read_text(encoding="utf-8"))
        return p if p.get("owner") == r["name"] else None

    def _save_project(self, p: dict) -> None:
        self._projects_dir().mkdir(parents=True, exist_ok=True)
        (self._projects_dir() / f"{p['id']}.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")

    def _ws_rater(self, code: str, nick: str | None) -> tuple[dict | None, str | None]:
        if not self.chat or not self.chat.get("sermon_daily_limit"):
            return None, "講道預備沒有開啟"
        r = self.who(code, nick)
        if r is None or not self.is_pastor(r):
            return None, "講道預備只開放給牧者連結"
        return r, None

    def _busy(self, pid: str) -> bool:
        return any(j.get("project") == pid and j["status"] == "running" for j in self.jobs.values())

    def _new_job(self, r: dict, kind: str, pid: str | None = None) -> str:
        job = secrets.token_hex(6)
        self.jobs[job] = {"name": r["name"], "status": "running", "item": None, "error": None, "started": time.time(),
                          "kind": kind, "timeout": WS_TIMEOUT[kind], "project": pid}
        return job

    def ws_list(self, code: str, nick: str | None = None) -> dict:
        r, err = self._ws_rater(code, nick)
        if err:
            return {"error": err}
        out = []
        if self._projects_dir().is_dir():
            for path in self._projects_dir().glob("*.json"):
                p = json.loads(path.read_text(encoding="utf-8"))
                if p.get("owner") == r["name"]:
                    out.append({"id": p["id"], "passage": p["passage"], "theme": p.get("theme", ""),
                                "created": p["created"], "board": len(p.get("board", []))})
        return {"projects": sorted(out, key=lambda x: x["created"], reverse=True),
                "starts_left": max(0, self.chat["sermon_daily_limit"] - self._today(r["name"], "sermon_start"))}

    def ws_get(self, code: str, pid: str, nick: str | None = None) -> dict | None:
        r, err = self._ws_rater(code, nick)
        if err:
            return None
        p = self._project(r, pid)
        if p is None:
            return None
        done = self.done(r["name"])
        turns = sorted((i for i, it in self.items.items() if it.trace.get("project") == pid),
                       key=lambda i: self.items[i].trace.get("asked_at", ""))
        return {k: p.get(k) for k in ("id", "passage", "theme", "audience", "length", "briefs", "word_study", "board")} | {
            "turns": [{"id": i, "kind": self.items[i].trace.get("kind"), "ask": self.items[i].trace.get("ask", ""),
                       "reply": self.items[i].trace.get("final_text") or "", "check": self.items[i].trace.get("check_summary"),
                       "rated": i in done} for i in turns],
            "busy": self._busy(pid)}

    def ws_start(self, code: str, body: dict, nick: str | None = None, runner=None) -> dict:
        r, err = self._ws_rater(code, nick)
        if err:
            return {"error": err}
        f = {k: str(body.get(k) or "").strip() for k in ("passage", "theme", "audience", "length", "notes")}
        if not 2 <= len(f["passage"]) <= 60:
            return {"error": "請填寫經文（例如：路加福音 15:11-32）"}
        if any(len(v) > 300 for v in f.values()):
            return {"error": "每一欄請在 300 字以內"}
        with self.lock:
            if self._spent() >= self.chat["budget_usd"]:
                return {"error": "本次測試的額度已用完，謝謝您的參與"}
            if self._today(r["name"], "sermon_start") >= self.chat["sermon_daily_limit"]:
                return {"error": f"今天已開了 {self.chat['sermon_daily_limit']} 篇講章，請明天再來"}
            job = self._new_job(r, "sermon_start")

        def work():
            try:
                from theoclaw.agent import workspace
                kb = self.chat.get("sermon_kb")
                if kb and not (ROOT / "knowledge" / kb / "wiki" / "index.md").is_file():
                    kb = None
                p = (runner or workspace.start)(f, owner=r["name"], model=self.chat["model"], kb=kb)
                with self.lock:
                    self._save_project(p)
                    self._log_cost(r["name"], "sermon_start", p.get("research_cost_usd") or 0.0, p["id"])
                    self.jobs[job].update(status="done", project=p["id"])
            except Exception as e:
                with self.lock:
                    self.jobs[job].update(status="error", error="研究時出錯，請稍後再試")
                sys.stderr.write(f"sermon start error {job}: {type(e).__name__}: {e}\n")

        threading.Thread(target=work, daemon=True).start()
        return {"job": job}

    def _log_cost(self, name: str, kind: str, usd: float, pid: str) -> None:
        """Research has no trace of its own; its cost still counts against the budget and the daily limit."""
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        with open(self.chat_dir / "costs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"by": name, "kind": kind, "cost_usd": usd, "project": pid,
                                "at": time.strftime("%Y%m%d-%H%M%S")}, ensure_ascii=False) + "\n")

    def _ws_run(self, code: str, body: dict, nick: str | None, kind: str, runner=None) -> dict:
        r, err = self._ws_rater(code, nick)
        if err:
            return {"error": err}
        pid = str(body.get("project") or "")
        p = self._project(r, pid)
        if p is None:
            return {"error": "找不到這篇講章"}
        message = str(body.get("message") or "").strip()
        if kind == "sermon_turn" and not 1 <= len(message) <= 1500:
            return {"error": "請輸入要求（1500 字以內）"}
        if kind == "sermon_draft" and not p.get("board"):
            return {"error": "講稿板上還沒有段落，請先把滿意的回答加入講稿"}
        with self.lock:
            if self._spent() >= self.chat["budget_usd"]:
                return {"error": "本次測試的額度已用完，謝謝您的參與"}
            if self._busy(pid):
                return {"error": "上一個要求還在處理中，請稍候"}
            if self._today(r["name"], "sermon_turn") + self._today(r["name"], "sermon_draft") >= WS_TURN_LIMIT:
                return {"error": f"今天已問了 {WS_TURN_LIMIT} 次，請明天再來"}
            job = self._new_job(r, kind, pid)

        def run(_question):
            from theoclaw.agent import workspace
            with self.lock:
                project = self._project(r, pid)
            if kind == "sermon_turn":
                rec = (runner or workspace.turn)(project, message, model=self.chat["model"])
                rec["ask"] = message
            else:
                rec = (runner or workspace.assemble)(project, model=self.chat["model"])
                rec["ask"] = "組成完整講稿"
            with self.lock:
                self._save_project(project)
            return rec

        threading.Thread(target=self._answer, args=(job, r["name"], message or "assemble", run, None), daemon=True).start()
        return {"job": job}

    def ws_turn(self, code: str, body: dict, nick: str | None = None, runner=None) -> dict:
        return self._ws_run(code, body, nick, "sermon_turn", runner)

    def ws_assemble(self, code: str, body: dict, nick: str | None = None, runner=None) -> dict:
        return self._ws_run(code, body, nick, "sermon_draft", runner)

    def ws_board(self, code: str, body: dict, nick: str | None = None) -> dict:
        """Add a reply to the board, or move, rename or remove a piece."""
        r, err = self._ws_rater(code, nick)
        if err:
            return {"error": err}
        with self.lock:
            p = self._project(r, str(body.get("project") or ""))
            if p is None:
                return {"error": "找不到這篇講章"}
            board = p.setdefault("board", [])
            action = body.get("action")
            if action == "add":
                it = self.items.get(str(body.get("item") or ""))
                if it is None or it.trace.get("project") != p["id"]:
                    return {"error": "找不到這個回答"}
                if len(board) >= 30:
                    return {"error": "講稿板最多 30 段"}
                board.append({"label": str(body.get("label") or "段落")[:40], "text": it.trace.get("final_text") or "",
                              "item": body["item"]})
            else:
                i = body.get("index")
                if not isinstance(i, int) or not 0 <= i < len(board):
                    return {"error": "找不到這一段"}
                if action == "up" and i > 0:
                    board[i - 1], board[i] = board[i], board[i - 1]
                elif action == "down" and i < len(board) - 1:
                    board[i + 1], board[i] = board[i], board[i + 1]
                elif action == "delete":
                    board.pop(i)
                elif action == "label":
                    board[i]["label"] = str(body.get("label") or "段落")[:40]
                elif action == "text":
                    text = str(body.get("text") or "").strip()
                    if not text or len(text) > 8000:
                        return {"error": "段落內容請在 1 到 8000 字之間"}
                    board[i]["text"], board[i]["edited"] = text, True
                elif action not in ("up", "down"):
                    return {"error": "不明的操作"}
            self._save_project(p)
        return {"ok": True, "board": board}

    def job(self, code: str, job_id: str, nick: str | None = None) -> dict | None:
        j = self.jobs.get(job_id)
        r = self.who(code, nick)
        if j is None or r is None or j["name"] != r["name"]:
            return None
        if j["status"] == "running" and time.time() - j["started"] > j.get("timeout", CHAT_TIMEOUT):
            j.update(status="error", error="回答超時，請稍後再試，或把問題問得具體一點")
        return {"status": j["status"], "item": j["item"], "error": j["error"], "project": j.get("project"),
                "elapsed": int(time.time() - j["started"])}

    def _run_agent(self, question: str) -> dict:
        from theoclaw.agent.loop import run_agent
        from theoclaw.agent.tools import build_tool_set
        from theoclaw.common.pricing import cost
        from theoclaw.llm import make_client, role
        rl = role("agent", model=self.chat["model"])
        ts = build_tool_set("scripture,wesley")
        run = run_agent(make_client(provider=rl.provider, params=rl.params), question, model=rl.model,
                        handlers=ts.handlers, tools=ts.defs, system=ts.system, effort=rl.effort,
                        max_tokens=rl.max_tokens)
        rec = {"toolset": ts.meta, "llm": rl.describe(), **run.to_dict()}
        rec["cost_usd"] = cost(rec["usage_total"], rl.model)
        return rec

    def _answer(self, job: str, name: str, question: str, runner=None, denomination: str | None = None) -> None:
        t0 = time.time()
        sys.stderr.write(f"chat start {job} {name}\n")
        try:
            rec = (runner or self._run_agent)(question)
            sys.stderr.write(f"chat done {job} {rec.get('outcome')} {time.time() - t0:.0f}s "
                             f"cost={rec.get('cost_usd')} error={rec.get('error')}\n")
            stamp = time.strftime("%Y%m%d-%H%M%S")
            rec = {"task_id": f"chat-{stamp}-{job}", "run_index": 0, "asked_by": name, "asked_at": stamp,
                   "denomination": denomination, "kind": rec.get("kind", "question"), **rec}
            with self.lock:
                self.chat_dir.mkdir(parents=True, exist_ok=True)
                cfg = self.chat_dir / "config.json"
                if not cfg.exists():
                    cfg.write_text(json.dumps({"kind": "pastor-chat", "model": rec.get("model"), "n": 1,
                                               "label": "pastor-chat", "toolset": rec.get("toolset")},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
                with open(self.chat_dir / "traces.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                it = Item(self.chat_dir, rec)
                self.items[it.item_id] = it
                self.owner[it.item_id] = name
                if rec.get("outcome") == "api_error" or not rec.get("final_text"):
                    self.jobs[job].update(status="error", error="模型服務暫時無法使用，請稍後再試"
                                          + ("（伺服器沒有設定金鑰）" if "API key" in str(rec.get("error")) else ""))
                else:
                    self.jobs[job].update(status="done", item=it.item_id)
        except Exception as e:  # report, never crash the server
            with self.lock:
                self.jobs[job].update(status="error", error="回答時出錯，請稍後再試")
            sys.stderr.write(f"chat error {job}: {type(e).__name__}: {e}\n")


# ---------------------------------------------------------------- HTTP

def make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TheoClawScoring/2.0"

        def log_message(self, fmt, *args):  # no codes in the log: only path without query
            sys.stderr.write(f"{self.log_date_time_string()} {self.command} {urlparse(self.path).path} {args[1] if len(args) > 1 else ''}\n")

        def _json(self, data, status=HTTPStatus.OK):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _code(self, q):
            code = (q.get("t") or [""])[0]
            return code if store.rater(code) else None

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                body = PAGE.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)
                return
            code = self._code(q)
            if code is None:
                return self._json({"error": "連結無效，請向負責人索取您的專屬連結"}, HTTPStatus.FORBIDDEN)
            nick = (q.get("u") or [""])[0]
            if u.path == "/api/state":
                return self._json(store.state(code, nick))
            if u.path == "/api/item":
                item = store.item(code, (q.get("id") or [""])[0], nick)
                return self._json(item) if item else self._json({"error": "找不到這一題"}, HTTPStatus.NOT_FOUND)
            if u.path == "/api/sermon/list":
                return self._json(store.ws_list(code, nick))
            if u.path == "/api/sermon/project":
                p = store.ws_get(code, (q.get("id") or [""])[0], nick)
                return self._json(p) if p else self._json({"error": "找不到這篇講章"}, HTTPStatus.NOT_FOUND)
            if u.path == "/api/job":
                j = store.job(code, (q.get("id") or [""])[0], nick)
                return self._json(j) if j else self._json({"error": "找不到"}, HTTPStatus.NOT_FOUND)
            self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            code = self._code(q)
            if code is None:
                return self._json({"error": "連結無效"}, HTTPStatus.FORBIDDEN)
            nick = (q.get("u") or [""])[0]
            if u.path not in ("/api/rate", "/api/ask", "/api/sermon", "/api/sermon/start", "/api/sermon/turn",
                              "/api/sermon/assemble", "/api/sermon/board"):
                return self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json({"error": "資料過大"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "資料格式錯誤"}, HTTPStatus.BAD_REQUEST)
            if u.path == "/api/ask":
                out = store.ask(code, body.get("question", ""), nick=nick, denomination=body.get("denomination"))
                return self._json(out, HTTPStatus.BAD_REQUEST if "error" in out else HTTPStatus.OK)
            ws = {"/api/sermon/start": store.ws_start, "/api/sermon/turn": store.ws_turn,
                  "/api/sermon/assemble": store.ws_assemble, "/api/sermon/board": store.ws_board}
            if u.path in ws:
                out = ws[u.path](code, body, nick)
                return self._json(out, HTTPStatus.BAD_REQUEST if "error" in out else HTTPStatus.OK)
            if u.path == "/api/sermon":
                out = store.sermon(code, body, nick=nick)
                return self._json(out, HTTPStatus.BAD_REQUEST if "error" in out else HTTPStatus.OK)
            err = store.rate(code, body, nick)
            self._json({"error": err} if err else {"ok": True}, HTTPStatus.BAD_REQUEST if err else HTTPStatus.OK)

    return Handler


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="TheoClaw 線上人工評分")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="選出要評的回答，給每位評分人一條專屬連結")
    p.add_argument("run_dirs", nargs="+")
    p.add_argument("--raters", required=True, help="評分人名字，用逗號分隔")
    p.add_argument("--sample", type=int, help="只抽 n 個回答（各 run 平均、分散到各題）")
    p.add_argument("--flagged-by", help="抽樣時約四分之一取自這位評分人判有問題的回答")
    p.add_argument("--base-url", default="http://localhost:8765", help="印出連結時用的網址")
    p = sub.add_parser("group", help="加一條團體連結：大家共用一條連結，第一次打開時輸入稱呼，資料按稱呼分開記錄")
    p.add_argument("name", help="團體名稱，例如 查經班、牧者")
    p.add_argument("--role", choices=ROLES, default="lay", help="lay = 平信徒（只能提問）；pastor = 牧者（另有講道預備）")
    p.add_argument("--base-url", default="http://localhost:8765")
    p = sub.add_parser("serve", help="啟動評分伺服器")
    p.add_argument("--host", default="127.0.0.1", help="預設只聽本機；經通道對外，不要直接開 0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--chat", action="store_true", help="開啟提問模式（需要 DEEPSEEK_API_KEY）")
    p.add_argument("--chat-model", default=CHAT_MODEL, help=f"提問模式的模型（預設 {CHAT_MODEL}）")
    p.add_argument("--daily-limit", type=int, default=30, help="每人每天最多問幾題")
    p.add_argument("--budget", type=float, default=5.0, help="提問模式總花費上限（美元）")
    p.add_argument("--group-daily-limit", type=int, default=60, help="團體連結每天合計最多問幾題")
    p.add_argument("--sermon-daily-limit", type=int, default=5, help="每位牧者每天最多預備幾篇講章（0 = 關閉）")
    p.add_argument("--sermon-kb", default=SERMON_KB, help="講道預備時衛斯理傳統研究用的知識庫")
    p.add_argument("--rubric", default=str(RUBRIC_10),
                   help="評分標準（預設一個 0–10 分；五項評分用 config/human_rubric.yaml）")
    a = ap.parse_args(argv)
    if a.cmd == "prepare":
        data = prepare(a.run_dirs, [r.strip() for r in a.raters.split(",") if r.strip()], a.sample, a.flagged_by)
        print(f"已選 {len(data['items'])} 個回答，寫入 {ASSIGNMENT}（含連結代碼，不要外流）")
        for code, r in data["raters"].items():
            print(f"  {r['name']}: {a.base_url.rstrip('/')}/?t={code}")
    elif a.cmd == "group":
        code = add_group(a.name, role=a.role)
        print(f"團體連結（{a.name}，{'牧者' if a.role == 'pastor' else '平信徒'}，大家共用；不要公開張貼）：{a.base_url.rstrip('/')}/?t={code}")
    else:
        chat = ({"model": a.chat_model, "daily_limit": a.daily_limit, "budget_usd": a.budget,
                 "group_daily_limit": a.group_daily_limit, "sermon_daily_limit": a.sermon_daily_limit,
                 "sermon_kb": a.sermon_kb} if a.chat else None)
        store = Store(chat=chat, rubric=Path(a.rubric))
        note = (f"；提問模式開啟（{a.chat_model}，每人每天 {a.daily_limit} 題，總上限 ${a.budget}，"
                f"已花 ${store._spent():.2f}）") if chat else ""
        print(f"{len(store.items)} 個回答、{len(store.raters)} 位評分人{note}。"
              f"http://{a.host}:{a.port}/?t=<代碼>  （Ctrl+C 停止）")
        ThreadingHTTPServer((a.host, a.port), make_handler(store)).serve_forever()


if __name__ == "__main__":
    main()
