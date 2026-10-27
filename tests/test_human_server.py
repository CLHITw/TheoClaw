import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("human_server", ROOT / "human_scoring" / "human_server.py")
hs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hs)


@pytest.fixture(autouse=True, params=["files", "db"])
def storage(request, tmp_path, monkeypatch):
    """Every server test on both storages; the database is each test's own SQLite file and
    the chat folder its own temporary one, never the project's or the server's (a local
    server run leaves real conversations in runs/pastor-chat)."""
    monkeypatch.setattr(hs, "CHAT_DIR", tmp_path / "default-chat")
    monkeypatch.setenv("THEOCLAW_DB", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setattr(hs, "STORAGE", request.param)
    return request.param


def _ratings(store, rater=None):
    return sorted(store.db.ratings(rater=rater), key=lambda r: r["rated_at"])


def _run(tmp_path, name, n=3):
    d = tmp_path / name
    d.mkdir()
    lines = []
    for i in range(n):
        lines.append(json.dumps({"task_id": f"q{i}", "run_index": 0, "prompt": "題目", "final_text": "回答",
                                 "outcome": "completed", "model": "secret-model",
                                 "steps": [{"tool_calls": [{"name": "wesley_note", "input": {"reference": "羅馬書 8:16"},
                                                            "output": "長" * 2000, "is_error": False}]}]},
                                ensure_ascii=False))
    (d / "traces.jsonl").write_text("\n".join(lines), encoding="utf-8")
    return d


def _consent(store, code, nick=None):
    """Chat writes are gated on the training-use consent; tests opt in explicitly."""
    store.db.record_consent(store.who(code, nick))


def test_blind_items_full_tools_and_ratings_saved(tmp_path):
    a, b = _run(tmp_path, "a"), _run(tmp_path, "b")
    path = tmp_path / "assignment.json"
    data = hs.prepare([str(a), str(b)], ["王牧師"], None, None, path)
    code = next(iter(data["raters"]))
    assert hs.prepare([str(a), str(b)], ["王牧師"], None, None, path)["raters"].keys() == {code}  # same link again
    store = hs.Store(path, rubric=hs.ROOT / "config" / "human_rubric.yaml")  # the five-dimension rubric
    st = store.state(code)
    assert st["rater"] == "王牧師" and len(st["order"]) == 6 and st["done"] == []
    it = store.item(code, st["order"][0])
    assert "secret-model" not in json.dumps(it, ensure_ascii=False) and "task_id" not in it
    assert len(it["tools"][0]["output"]) == 2000  # not cut short
    dims = {d["key"]: 4 for d in st["rubric"]["dimensions"]}
    assert store.rate(code, {"id": it["id"], "scores": dims, "verdict": None}) == "請選擇總評"
    assert "還沒有評分" in store.rate(code, {"id": it["id"], "scores": {}, "verdict": True})
    assert store.rate(code, {"id": it["id"], "scores": dims, "verdict": False, "problems": ["shallow", "bogus"]}) is None
    rec = _ratings(store, "王牧師")
    assert len(rec) == 1 and rec[0]["problems"] == ["shallow"] and rec[0]["blind"] and rec[0]["verdict"] is False
    assert hs.Store(path).state(code)["done"] == [it["id"]]  # survives a restart (any rubric)
    assert store.item(code, it["id"])["previous"]["verdict"] is False


def test_default_rubric_is_one_score_0_to_10(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    code = next(iter(hs.prepare([str(a)], ["信徒1"], None, None, path)["raters"]))
    store = hs.Store(path)
    st = store.state(code)
    assert [d["key"] for d in st["rubric"]["dimensions"]] == ["overall"] and st["rubric"]["scale"] == {"min": 0, "max": 10}
    assert not st["rubric"]["allow_na"] and len(st["rubric"]["anchors"]) == 4
    item = st["order"][0]
    assert "需要打分" in store.rate(code, {"id": item, "scores": {"overall": None}})
    assert "無效" in store.rate(code, {"id": item, "scores": {"overall": 11}})
    assert "無效" in store.rate(code, {"id": item, "scores": {"overall": True}})
    assert store.rate(code, {"id": item, "scores": {"overall": 6}}) is None  # verdict from the score, none sent
    assert store.rate(code, {"id": item, "scores": {"overall": 7}, "verdict": False}) is None  # client verdict ignored
    rows = [r for _, r in store.db.all_ratings()]  # every rating kept, the latest one counts
    assert [(r["scores"]["overall"], r["verdict"]) for r in rows] == [(6, False), (7, True)]
    assert [r["scores"]["overall"] for r in _ratings(store, "信徒1")] == [7]


def test_http_requires_code(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    code = next(iter(hs.prepare([str(a)], ["李傳道"], None, None, path)["raters"]))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hs.make_handler(hs.Store(path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        try:
            urllib.request.urlopen(base + "/api/state?t=wrong")
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 403
        st = json.loads(urllib.request.urlopen(base + f"/api/state?t={code}").read())
        assert st["rater"] == "李傳道"
        assert b"TheoClaw" in urllib.request.urlopen(base + "/").read()
    finally:
        srv.shutdown()


def test_chat_mode_limits_and_saving(tmp_path):
    import time as _t
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    codes = list(hs.prepare([str(a)], ["牧者1", "牧者2"], None, None, path)["raters"])
    chat_dir = tmp_path / "pastor-chat"
    store = hs.Store(path, chat={"model": "deepseek-flash", "daily_limit": 1, "budget_usd": 1.0}, chat_dir=chat_dir)
    _consent(store, codes[0])
    _consent(store, codes[1])
    fake = lambda q: {"model": "deepseek-flash", "prompt": q, "final_text": "答案", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.01}
    assert "error" in store.ask(codes[0], "x")  # too short
    job = store.ask(codes[0], "請解釋約翰福音 3:16", runner=fake)["job"]
    for _ in range(50):
        if store.job(codes[0], job)["status"] != "running":
            break
        _t.sleep(0.05)
    j = store.job(codes[0], job)
    assert j["status"] == "done" and store.job(codes[1], job) is None  # another pastor cannot see it
    assert "明天" in store.ask(codes[0], "第二個問題", runner=fake)["error"]  # daily limit 1
    assert store.item(codes[1], j["item"]) is None and store.item(codes[0], j["item"])["chat"]
    dims = {d["key"]: 5 for d in store.rubric["dimensions"]}
    assert store.rate(codes[0], {"id": j["item"], "scores": dims, "verdict": True}) is None
    [rec] = _ratings(store, "牧者1")
    assert rec["mode"] == "own" and rec["blind"] is False
    again = hs.Store(path, chat={"model": "deepseek-flash", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=chat_dir)
    assert [q["rated"] for q in again.state(codes[0])["chat"]["questions"]] == [True]
    assert hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 0.01}, chat_dir=chat_dir).ask(
        codes[1], "預算用完了嗎", runner=fake)["error"].startswith("本次測試")


def test_assignment_ids_survive_a_move_to_another_machine(tmp_path):
    # On the server the run folder has another absolute path, so Item.item_id would differ;
    # the store must use the ids written in the assignment.
    a = _run(tmp_path, "a", 2)
    path = tmp_path / "assignment.json"
    data = hs.prepare([str(a)], ["牧者1"], None, None, path)
    for e in data["items"]:
        e["id"] = "moved" + e["id"][:5]
    for r in data["raters"].values():
        r["order"] = ["moved" + i[:5] for i in r["order"]]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    store = hs.Store(path)
    code = next(iter(data["raters"]))
    first = store.state(code)["order"][0]
    assert store.item(code, first)["prompt"] == "題目"
    dims = {d["key"]: 5 for d in store.rubric["dimensions"]}
    assert store.rate(code, {"id": first, "scores": dims, "verdict": True}) is None
    assert store.state(code)["done"] == [first]


def test_group_link_is_private_per_person(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    assert hs.add_group("查經班", path) == code  # same link again
    chat_dir = tmp_path / "pastor-chat"
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0, "group_daily_limit": 2},
                     chat_dir=chat_dir)
    tom1, tom2, mary = ("小明", "k" * 20), ("小明", "z" * 20), ("小華", "m" * 20)  # two people pick the same nickname
    assert store.state(code)["need_name"] and store.state(code, ("小明", "short"))["need_name"]  # a key is required
    assert "稱呼" in store.ask(code, "問題", nick=("", "k" * 20))["error"]
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "答案", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    for nick in (tom1, tom2, mary):
        _consent(store, code, nick)
    j = store.ask(code, "我最近很軟弱，該讀哪段經文？", runner=fake, nick=tom1)
    for _ in range(50):
        if store.job(code, j["job"], tom1)["status"] != "running":
            break
        time.sleep(0.05)
    item = store.job(code, j["job"], tom1)["item"]
    assert store.job(code, j["job"], tom2) is None  # the same nickname on another browser is someone else
    st = store.state(code, tom1)
    assert st["rater"] == "小明" and [q["id"] for q in st["chat"]["questions"]] == [item] and "others" not in st["chat"]
    for other in (tom2, mary):
        assert store.state(code, other)["chat"]["questions"] == []
        assert store.item(code, item, other) is None and store.rate(code, {"id": item, "scores": {"overall": 3}}, other) == "找不到這一題"
    assert store.rate(code, {"id": item, "scores": {"overall": 8}}, tom1) is None
    [rec] = _ratings(store)
    assert rec["rater"].startswith("查經班·小明#") and "k" * 20 not in json.dumps(rec)  # a hash, not the key
    personal = next(c for c, r in store.raters.items() if not r.get("group"))
    assert store.item(personal, item) is None  # a pastor's personal link cannot see it either
    assert code in hs.prepare([str(a)], ["牧者1"], None, None, path)["raters"]  # re-preparing keeps the group link
    store.ask(code, "第二題", runner=fake, nick=mary)
    time.sleep(0.2)
    assert "團契" in store.ask(code, "第三題", runner=fake, nick=mary)["error"]  # group daily limit 2


def test_denomination_recorded_with_question_and_rating(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    chat_dir = tmp_path / "pastor-chat"
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=chat_dir)
    assert "無宗派 Non-denominational" in store.state(code)["denominations"]
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "answer", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    _consent(store, code, "Tom")
    j = store.ask(code, "What is grace?", runner=fake, nick="Tom", denomination="聖公會 Anglican")
    store.ask(code, "Another?", runner=fake, nick="Tom", denomination="made up")
    time.sleep(0.3)
    traces = store.db.answers()
    assert sorted(str(t["denomination"]) for t in traces) == ["None", "聖公會 Anglican"]
    item = store.job(code, j["job"], "Tom")["item"]
    assert store.rate(code, {"id": item, "scores": {"overall": 7}, "denomination": "聖公會 Anglican"}, "Tom") is None
    [rec] = _ratings(store)
    assert rec["denomination"] == "聖公會 Anglican"


def test_sermon_preparation_for_pastors_only(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    pastor = next(iter(hs.prepare([str(a)], ["牧者1"], None, None, path)["raters"]))
    group = hs.add_group("查經班", path)
    chat_dir = tmp_path / "pastor-chat"
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0, "sermon_daily_limit": 1},
                     chat_dir=chat_dir)
    assert store.state(pastor)["chat"]["sermon"]["remaining_today"] == 1
    assert "sermon" not in store.state(group, "小明")["chat"]
    assert "牧者" in store.sermon(group, {"passage": "路加福音 15"}, nick="小明")["error"]
    assert "經文" in store.sermon(pastor, {"passage": ""})["error"]
    fake = lambda q: {"kind": "sermon", "model": "m", "prompt": q, "final_text": "講章", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.05, "briefs": "[A1] 要點", "revised": False,
                      "check_summary": {"unsupported": 0}}
    j = store.sermon(pastor, {"passage": "路加福音 15:11-32", "theme": "父親的愛"}, runner=fake)
    for _ in range(50):
        if store.job(pastor, j["job"])["status"] != "running":
            break
        time.sleep(0.05)
    item = store.item(pastor, store.job(pastor, j["job"])["item"])
    assert item["kind"] == "sermon" and item["briefs"] == "[A1] 要點" and "父親的愛" in item["prompt"]
    assert "1 篇" in store.sermon(pastor, {"passage": "約翰福音 3"}, runner=fake)["error"]  # daily limit
    assert store.state(pastor)["chat"]["remaining_today"] == 5  # sermons do not use up questions
    pastors = hs.add_group("牧者", path, role="pastor")
    store2 = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0, "sermon_daily_limit": 1},
                      chat_dir=tmp_path / "chat2")
    assert store2.state(pastors, "王牧師")["chat"]["sermon"]["remaining_today"] == 1  # the shared pastor link
    assert "sermon" not in store2.state(group, "小明")["chat"]                         # the lay link


def _wait(store, code, job, nick=None):
    for _ in range(100):
        j = store.job(code, job, nick)
        if j["status"] != "running":
            return j
        time.sleep(0.03)
    raise AssertionError("job did not finish")


def test_sermon_workspace_start_turns_board_and_assemble(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    pastors = hs.add_group("牧者", path, role="pastor")
    lay = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0, "sermon_daily_limit": 2},
                     chat_dir=tmp_path / "chat")
    _consent(store, pastors, "王牧師")
    assert "牧者" in store.ws_start(lay, {"passage": "路加福音 15"}, "小明")["error"]
    start = lambda f, owner, model, kb: {"id": "a1b2c3d4e5f6", "owner": owner, "created": "20261017-100000",
                                          "passage": f["passage"], "theme": f["theme"], "request": "經文：" + f["passage"],
                                          "briefs": "[A1] 要點", "word_study": "| 表 |", "board": [], "turns": [],
                                          "research_cost_usd": 0.02}
    j = _wait(store, pastors, store.ws_start(pastors, {"passage": "路加福音 15:11-32", "theme": "父親的愛"}, "王牧師", start)["job"], "王牧師")
    pid = j["project"]
    assert pid == "a1b2c3d4e5f6" and store.ws_list(pastors, "王牧師")["projects"][0]["passage"] == "路加福音 15:11-32"
    assert store.ws_get(pastors, pid, "李牧師") is None  # another pastor cannot open it
    turn = lambda p, m, model: {"kind": "sermon_turn", "project": p["id"], "model": "m", "prompt": m, "final_text": "引言草稿",
                                "outcome": "completed", "steps": [], "usage_total": {}, "cost_usd": 0.01, "check_summary": {}}
    j = _wait(store, pastors, store.ws_turn(pastors, {"project": pid, "message": "寫引言"}, "王牧師", turn)["job"], "王牧師")
    item = j["item"]
    got = store.ws_get(pastors, pid, "王牧師")
    assert [t["ask"] for t in got["turns"]] == ["寫引言"] and got["turns"][0]["reply"] == "引言草稿"
    assert "還沒有段落" in store.ws_assemble(pastors, {"project": pid}, "王牧師")["error"]
    assert store.ws_board(pastors, {"project": pid, "action": "add", "item": item, "label": "引言"}, "王牧師")["ok"]
    assert store.ws_board(pastors, {"project": pid, "action": "text", "index": 0, "text": "改過的引言"}, "王牧師")["board"][0]["text"] == "改過的引言"
    draft = lambda p, model: {"kind": "sermon_draft", "project": p["id"], "model": "m", "prompt": "組成", "final_text": "全文",
                              "outcome": "completed", "steps": [], "usage_total": {}, "cost_usd": 0.03, "check_summary": {}}
    j = _wait(store, pastors, store.ws_assemble(pastors, {"project": pid}, "王牧師", draft)["job"], "王牧師")
    assert store.item(pastors, j["item"], "王牧師")["kind"] == "sermon_draft"
    assert abs(store._spent() - 0.06) < 1e-9  # research cost counts too
    store.ws_start(pastors, {"passage": "約翰福音 4"}, "王牧師", start)
    time.sleep(0.2)
    assert "2 篇" in store.ws_start(pastors, {"passage": "約翰福音 5"}, "王牧師", start)["error"]  # daily limit


def test_follow_up_questions_carry_the_conversation(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0}, chat_dir=tmp_path / "chat")
    me, other = ("小明", "k" * 20), ("小華", "m" * 20)
    _consent(store, code, me)
    _consent(store, code, other)
    seen = []

    def fake(prompt):
        seen.append(prompt)
        return {"model": "m", "prompt": prompt, "final_text": f"答{len(seen)}", "outcome": "completed",
                "steps": [], "usage_total": {}, "cost_usd": 0.001}

    first = store.ask(code, "羅馬書 8 章的重點？", runner=fake, nick=me)
    _wait(store, code, first["job"], me)
    second = store.ask(code, "那第 28 節呢？", runner=fake, nick=me, conv=first["conv"])
    _wait(store, code, second["job"], me)
    assert second["conv"] == first["conv"] and seen[0] == "羅馬書 8 章的重點？"
    assert "羅馬書 8 章的重點？" in seen[1] and "答1" in seen[1] and seen[1].endswith("那第 28 節呢？")
    conv = store.conversation(code, first["conv"], me)
    assert [t["ask"] for t in conv["turns"]] == ["羅馬書 8 章的重點？", "那第 28 節呢？"]  # shown as asked
    state = store.state(code, me)["chat"]["conversations"]
    assert len(state) == 1 and state[0]["turns"] == 2 and state[0]["title"] == "羅馬書 8 章的重點？"
    assert store.conversation(code, first["conv"], other) is None  # private
    assert "找不到" in store.ask(code, "插話", runner=fake, nick=other, conv=first["conv"])["error"]


def test_lay_tools_use_the_methodist_kb_and_never_the_pastor_tools(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["甲"], None, None, path)
    missing = hs.Store(path, chat={"model": "deepseek-flash", "kb": "no-such-kb"}, chat_dir=tmp_path / "c1")
    assert missing._lay_tools().meta["tools"] == ["scripture", "wesley"]  # falls back, does not fail
    if (ROOT / "knowledge" / hs.METHODIST_KB).is_dir():  # only where the (git-ignored) KB has been compiled
        ts = hs.Store(path, chat={"model": "deepseek-flash", "kb": hs.METHODIST_KB}, chat_dir=tmp_path / "c2")._lay_tools()
        assert "kb" in ts.meta["tools"] and "rag" in ts.meta["tools"]
        assert "reference" not in ts.meta["tools"] and "original" not in ts.meta["tools"]


def test_database_import_is_idempotent_and_export_round_trips(tmp_path):
    db = hs.DB()
    chat = tmp_path / "pastor-chat"
    (chat / "human").mkdir(parents=True)
    (chat / "projects").mkdir()
    traces = [{"task_id": f"chat-1-{i}", "run_index": 0, "kind": "question", "asked_by": "查經班·小明#ab", "asked_at": f"2026101{i}-1",
               "prompt": "問", "final_text": "答", "outcome": "completed", "steps": [], "cost_usd": 0.01} for i in range(3)]
    (chat / "traces.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces), encoding="utf-8")
    ratings = [{"task_id": "chat-1-0", "run_index": 0, "rater": "查經班·小明#ab", "scores": {"overall": s}, "verdict": True,
                "comment": "", "rated_at": f"2026-10-1{s} 10:00:00"} for s in (6, 8)]  # the same answer rated twice
    (chat / "human" / "x.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ratings), encoding="utf-8")
    (chat / "projects" / "abc.json").write_text(json.dumps({"id": "abc", "owner": "牧者1", "passage": "羅 8", "created": "1", "board": []}),
                                              encoding="utf-8")
    (chat / "costs.jsonl").write_text(json.dumps({"by": "牧者1", "kind": "sermon_start", "cost_usd": 0.02, "project": "abc", "at": "1"}) + "\n",
                                      encoding="utf-8")
    assign = tmp_path / "assignment.json"
    assign.write_text(json.dumps({"items": [], "raters": {"c1": {"name": "查經班", "group": True, "role": "lay", "order": []}}}), encoding="utf-8")
    first = hs.db_mod.import_files(db, assign, chat, [])
    assert first == {"links": 1, "answers": 3, "ratings": 2, "projects": 1, "costs": 1}
    assert set(hs.db_mod.import_files(db, assign, chat, []).values()) == {0}  # a second import adds nothing
    assert [r["scores"]["overall"] for r in db.ratings()] == [8]  # the latest rating counts
    out = hs.db_mod.export_files(db, tmp_path / "out")
    back = tmp_path / "out" / "runs" / "pastor-chat"
    assert [json.loads(x)["task_id"] for x in (back / "traces.jsonl").read_text(encoding="utf-8").splitlines()] == [t["task_id"] for t in traces]
    assert len((back / "human" / "查經班·小明#ab.jsonl").read_text(encoding="utf-8").splitlines()) == 2  # both kept
    assert json.loads((back / "projects" / "abc.json").read_text(encoding="utf-8"))["passage"] == "羅 8"
    assert out["answers"] == 3 and db.stats()["users"] == 1


def test_language_recorded_and_old_databases_get_the_column(tmp_path, storage):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("International", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=tmp_path / "pastor-chat")
    seen = []
    fake = lambda q: seen.append(q) or {"model": "m", "prompt": q, "final_text": "answer", "outcome": "completed",
                                        "steps": [], "usage_total": {}, "cost_usd": 0.001}
    nick = ("Eden", "e" * 20)
    _consent(store, code, nick)
    store.ask(code, "什麼是恩典？", runner=fake, nick=nick, lang="en")
    time.sleep(0.3)
    assert seen[0].endswith("(Please answer in English.)")
    [rec] = store.db.answers()
    assert rec["lang"] == "en" and rec["prompt"] == "什麼是恩典？"  # recorded as asked
    item = store.state(code, nick)["chat"]["questions"][0]["id"]
    assert store.rate(code, {"id": item, "scores": {"overall": 8}}, nick) is None
    assert store.db.ratings()[0]["lang"] == "en"  # the rating knows the answer was English
    if storage == "db":
        from sqlalchemy import text
        with store.db.engine.begin() as c:
            assert c.execute(text("select lang from users")).scalar() == "en"
            assert c.execute(text("select lang from ratings")).scalar() == "en"
            for table in ("answers", "ratings"):
                c.execute(text(f"DROP INDEX ix_{table}_lang"))
                c.execute(text(f"ALTER TABLE {table} DROP COLUMN lang"))  # a database made before the column existed
        again = hs.DB()
        with again.engine.connect() as c:
            assert c.execute(text("select lang from answers")).scalar() == "zh"  # added, earlier rows Chinese
            assert c.execute(text("select lang from ratings")).scalar() == "zh"


def test_one_time_recovery_link_moves_records_to_the_new_browser(tmp_path, storage):
    import hashlib
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=tmp_path / "pastor-chat")
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "答", "outcome": "completed", "steps": [],
                      "usage_total": {}, "cost_usd": 0.001}
    old, new, other = ("小明", "o" * 20), ("小明", "n" * 20), ("小華", "x" * 20)
    _consent(store, code, old)
    store.ask(code, "以前問過的問題", runner=fake, nick=old)
    time.sleep(0.3)
    item = store.state(code, old)["chat"]["questions"][0]["id"]
    assert store.rate(code, {"id": item, "scores": {"overall": 8}}, old) is None
    old_name = store.who(code, old)["name"]
    assert [p["name"] for p in store.db.identities("查經班")][:1] == [old_name] or storage == "files"
    token = "t" * 24
    store.db.add_recover_token(hashlib.sha256(token.encode()).hexdigest(), old_name, "查經班", "29991231-000000")
    assert store.state(code, new)["chat"]["questions"] == []          # a new browser sees nothing yet
    assert "error" in store.recover(code, "bad-token-xxxxxxxxxxxx", new)
    out = store.recover(code, token, new)
    assert out["ok"] and out["moved"] >= 2
    st = store.state(code, new)
    assert [q["id"] for q in st["chat"]["questions"]] == [item] and st["done"] == [] and item in store.done(store.who(code, new)["name"])
    assert store.state(code, old)["chat"]["questions"] == []           # the old identity is empty now
    assert "error" in store.recover(code, token, other)                # one use only
    again = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=tmp_path / "pastor-chat")
    assert [q["id"] for q in again.state(code, new)["chat"]["questions"]] == [item]   # survives a restart


def test_front_page_members_go_in_pastors_need_the_fellowship_code(tmp_path, monkeypatch):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    lay = hs.add_group("查經班", path)
    pastor = hs.add_group("牧者", path, role="pastor")
    monkeypatch.delenv("THEOCLAW_PASTOR_CODE", raising=False)  # the seed is then the built-in code
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=tmp_path / "pastor-chat")
    assert store.enter("lay") == {"t": lay}
    assert store.enter("pastor", hs.PASTOR_CODE, "1.2.3.4") == {"t": pastor}  # the seeded fellowship
    store.db.put_fellowship("grace2026", "恩典團契", "pastor")                # more fellowships at runtime
    assert store.enter("pastor", " grace2026 ", "1.2.3.4") == {"t": pastor}
    store.db.put_fellowship("m2026", "青年團契", "member")                    # a member-role code works too
    assert store.enter("member", "m2026", "1.2.3.4") == {"t": lay}
    assert "不正確" in store.enter("pastor", "wrong", "5.6.7.8")["error"]
    for _ in range(store.ENTER_TRIES):
        store.enter("pastor", "wrong", "9.9.9.9")
    assert "太多次" in store.enter("pastor", "grace2026", "9.9.9.9")["error"]  # locked out for an hour
    assert store.enter("pastor", "grace2026", "1.1.1.1") == {"t": pastor}     # others are not


def test_german_questions_are_answered_in_german(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 5, "budget_usd": 1.0}, chat_dir=tmp_path / "chat")
    me = ("Eden", "e" * 20)
    _consent(store, code, me)
    seen = []
    fake = lambda q: seen.append(q) or {"model": "m", "prompt": q, "final_text": "Antwort", "outcome": "completed",
                                        "steps": [], "usage_total": {}, "cost_usd": 0.001}
    store.ask(code, "Was ist Gnade?", runner=fake, nick=me, lang="de")
    time.sleep(0.3)
    assert seen[0].endswith("(Bitte antworten Sie auf Deutsch.)")
    [rec] = store.db.answers()
    assert rec["lang"] == "de" and rec["prompt"] == "Was ist Gnade?"  # recorded as asked


def test_consent_gate_blocks_chat_writes_until_given(tmp_path, monkeypatch):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    lay = hs.add_group("查經班", path)
    pastors = hs.add_group("牧者", path, role="pastor")
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0, "sermon_daily_limit": 2},
                     chat_dir=tmp_path / "chat")
    me = ("小明", "k" * 20)
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "答", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    assert "同意" in store.ask(lay, "我還沒有同意", runner=fake, nick=me)["error"]
    start = lambda f, owner, model, kb: {"id": "abc123def456", "owner": owner, "created": "20261018-100000",
                                          "passage": f["passage"], "theme": f.get("theme"), "request": f["passage"],
                                          "briefs": "", "word_study": "", "board": [], "turns": [],
                                          "research_cost_usd": 0.01}
    assert "同意" in store.ws_start(pastors, {"passage": "約翰福音 3"}, "王牧師", start)["error"]
    assert store.state(lay, me)["consented"] is False
    _consent(store, lay, me)
    _consent(store, pastors, "王牧師")
    assert store.state(lay, me)["consented"] is True
    job = store.ask(lay, "同意之後就能提問", runner=fake, nick=me)["job"]
    _wait(store, lay, job, me)
    item = store.job(lay, job, me)["item"]
    monkeypatch.setattr(store.db, "consented", lambda name: False)  # the same gate guards a chat rating
    assert "同意" in store.rate(lay, {"id": item, "scores": {"overall": 8}}, me)
    monkeypatch.undo()
    assert store.rate(lay, {"id": item, "scores": {"overall": 8}}, me) is None


def test_google_login_binds_this_browser_then_merges_another(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0}, chat_dir=tmp_path / "chat")
    dev_a, dev_b = ("小明", "k" * 20), ("小明", "z" * 20)  # same nickname, two browsers
    _consent(store, code, dev_a)
    _consent(store, code, dev_b)
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "答", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    store.ask(code, "瀏覽器一問的", runner=fake, nick=dev_a)
    time.sleep(0.3)
    name_a, name_b = store.who(code, dev_a)["name"], store.who(code, dev_b)["name"]
    assert name_a != name_b  # two devices are two identities until an account binds them
    sub_hash = hs.google_sub_hash("sub-xyz", store.google_salt())
    name, err, moved = store.bind_google(sub_hash, name_a)  # first login: this device becomes the account
    assert err is None and name == name_a and moved == 0
    cookie = store.issue_session(sub_hash)
    assert store.session_account(cookie)["name"] == name_a
    assert store.session_account("tampered-value") is None
    store.ask(code, "瀏覽器二問的", runner=fake, nick=dev_b)
    time.sleep(0.3)
    name, err, moved = store.bind_google(sub_hash, name_b)  # the same Google account on device two
    assert err is None and name == name_a and moved >= 1        # the anonymous records merge over
    assert store.session_account(store.issue_session(sub_hash))["name"] == name_a
    prompts = [q["prompt"] for q in store.state(code, dev_a)["chat"]["questions"]]
    assert prompts == ["瀏覽器一問的", "瀏覽器二問的"]


def test_consent_survives_a_merge_into_an_existing_account(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    dev_a, dev_b = ("小明", "k" * 20), ("小明", "z" * 20)
    name_a, name_b = store.who(code, dev_a)["name"], store.who(code, dev_b)["name"]
    store.db.touch_user(store._user(name_a))  # the account already exists, without consent
    sub_hash = hs.google_sub_hash("sub-1", store.google_salt())
    store.db.put_google_account(sub_hash, name_a)
    _consent(store, code, dev_b)
    assert store.db.consented(name_a) is False
    name, err, moved = store.bind_google(sub_hash, name_b)  # this browser's records merge into it
    assert err is None and name == name_a
    assert store.db.consented(name_a) is True  # the merged browser's consent is kept
    assert store.db.consented(name_b) is False


def test_returning_google_account_logs_in_without_a_nickname(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    name = store.who(code, ("小明", "k" * 20))["name"]
    sub_hash = hs.google_sub_hash("sub-1", store.google_salt())
    store.db.put_google_account(sub_hash, name)
    logged_in, err, moved = store.bind_google(sub_hash, "")
    assert err is None and logged_in == name and moved == 0
    assert store.session_account(store.issue_session(sub_hash))["name"] == name


def test_first_google_login_without_a_nickname_creates_no_account(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    sub_hash = hs.google_sub_hash("sub-new", store.google_salt())
    assert store.bind_google(sub_hash, "") == (None, "newname", 0)
    assert store.db.google_account(sub_hash) is None


def _get(base, path, cookies=None):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    req = urllib.request.Request(base + path, headers={"Cookie": header} if header else {})
    try:
        urllib.request.build_opener(NoRedirect).open(req)
    except urllib.error.HTTPError as e:
        return e
    raise AssertionError("expected a redirect")


def _cookie_value(response, name):
    for c in response.headers.get_all("Set-Cookie") or []:
        if c.startswith(name + "=") and "Max-Age=0" not in c:
            return c.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"{name} not set")


def _serve(store):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hs.make_handler(store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_first_google_login_asks_for_a_name_then_binds_without_google_again(tmp_path, monkeypatch):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    store.google = {"client_id": "123456789012-abc_DEF.apps.googleusercontent.com", "client_secret": "secret"}
    monkeypatch.setattr(hs, "exchange_google_code", lambda *a, **k: "token")
    monkeypatch.setattr(hs, "fetch_google_sub", lambda token: "sub-new")
    srv, base = _serve(store)
    try:
        step = _get(base, f"/auth/google/start?t={code}")  # no nickname needed to start
        assert step.code == 303 and step.headers["Location"].startswith(hs.GOOGLE_AUTH_URL + "?")
        state = parse_qs(urlparse(step.headers["Location"]).query)["state"][0]
        back = _get(base, f"/auth/google/callback?state={state}&code=abc",
                    cookies={hs.LOGIN_COOKIE: state})
        assert back.code == 303
        params = parse_qs(urlparse(back.headers["Location"]).query)
        assert params["t"] == [code] and params["auth_error"] == ["newname"]
        sub_hash = hs.google_sub_hash("sub-new", store.google_salt())
        assert store.db.google_account(sub_hash) is None  # no nameless account is created
        pending = _cookie_value(back, hs.GOOGLE_PENDING_COOKIE)
        done = _get(base, "/auth/google/start?" + urlencode({"t": code, "u": "小明", "k": "k" * 20}),
                    cookies={hs.GOOGLE_PENDING_COOKIE: pending})
        assert done.code == 303 and done.headers["Location"] == f"/?t={code}"
        session = _cookie_value(done, hs.SESSION_COOKIE)
        name = store.who(code, ("小明", "k" * 20))["name"]
        assert store.session_account(session)["name"] == name
        cookies = done.headers.get_all("Set-Cookie") or []
        assert any(c.startswith(f"{hs.GOOGLE_PENDING_COOKIE}=;") and "Max-Age=0" in c for c in cookies)
    finally:
        srv.shutdown()


def test_returning_google_account_is_recognised_through_the_pending_cookie(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    store.google = {"client_id": "123456789012-abc_DEF.apps.googleusercontent.com", "client_secret": "secret"}
    name = store.who(code, ("小明", "k" * 20))["name"]
    sub_hash = hs.google_sub_hash("sub-old", store.google_salt())
    store.db.put_google_account(sub_hash, name)
    srv, base = _serve(store)
    try:
        pending = store.google_pending_value(sub_hash, code)
        done = _get(base, f"/auth/google/start?t={code}", cookies={hs.GOOGLE_PENDING_COOKIE: pending})
        assert done.code == 303 and done.headers["Location"] == f"/?t={code}"
        assert store.session_account(_cookie_value(done, hs.SESSION_COOKIE))["name"] == name
    finally:
        srv.shutdown()


def test_logout_clears_the_session_cookie_and_returns_to_the_link(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    name = store.who(code, ("小明", "k" * 20))["name"]
    store.db.put_google_account(hs.google_sub_hash("sub-1", store.google_salt()), name)
    session = store.issue_session(hs.google_sub_hash("sub-1", store.google_salt()))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hs.make_handler(store))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    try:
        req = urllib.request.Request(base + f"/auth/logout?t={code}",
                                     headers={"Cookie": f"{hs.SESSION_COOKIE}={session}"})
        try:
            urllib.request.build_opener(NoRedirect).open(req)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 303
            assert e.headers["Location"] == f"/?t={code}"
            cookies = e.headers.get_all("Set-Cookie") or []
            assert any(c.startswith(f"{hs.SESSION_COOKIE}=;") and "Max-Age=0" in c for c in cookies)
    finally:
        srv.shutdown()


def test_quick_skip_and_elapsed_recorded_with_ratings(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0}, chat_dir=tmp_path / "chat")
    me = ("小明", "k" * 20)
    _consent(store, code, me)
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "答", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    job = store.ask(code, "一個問題", runner=fake, nick=me)["job"]
    _wait(store, code, job, me)
    item = store.job(code, job, me)["item"]
    mine = lambda: store.db.ratings(rater=store.who(code, me)["name"])[-1]
    assert store.rate(code, {"id": item, "quick": "up", "elapsed": 1.5}, me) is None
    rec = mine()
    assert rec["method"] == "quick" and rec["quick"] == "up" and rec["verdict"] is True and rec["elapsed_s"] == 1.5
    assert store.rate(code, {"id": item, "quick": "down", "elapsed": 999999}, me) is None  # clamped to a day
    assert mine()["elapsed_s"] == 86400.0 and mine()["verdict"] is False
    assert store.rate(code, {"id": item, "skip": True}, me) is None  # a skip: no opinion, still recorded
    rec = mine()
    assert rec["method"] == "skip" and rec["verdict"] is None and rec["scores"] == {}
    assert store.rate(code, {"id": item, "scores": {"overall": 7}}, me) is None  # detailed still works
    rec = mine()
    assert rec["method"] == "detailed" and rec["scores"] == {"overall": 7} and rec["elapsed_s"] is None
    assert store.rate(code, {"id": item, "comment": "這句讀不懂"}, me) is None  # a note on its own: no score needed
    rec = mine()
    assert rec["method"] == "note" and rec["scores"] == {} and rec["verdict"] is None and rec["comment"] == "這句讀不懂"
    store.rate(code, {"id": item, "comment": "順帶一提", "quick": "up"}, me)  # a note typed next to a quick tap is kept
    rec = mine()
    assert rec["method"] == "quick" and rec["comment"] == "順帶一提" and rec["verdict"] is True
    assert store.rate(code, {"id": item, "skip": True, "comment": "不想說"}, me) is None  # a skip keeps no comment
    assert mine()["comment"] == ""


def test_state_offers_google_login_once_a_name_is_needed(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    pastors = hs.add_group("牧者", path, role="pastor")
    store = hs.Store(path, chat_dir=tmp_path / "chat")
    store.google = None
    assert store.state(code)["google"] is False  # no login entry anywhere when not set up
    store.google = {"client_id": "id", "client_secret": "secret"}
    st = store.state(code)
    assert st["need_name"] and st["google"] is True  # the name card offers the optional login
    assert st["pastor"] is False and store.state(pastors)["pastor"] is True
    assert store.state(code, ("小明", "k" * 20))["google"] is True
    assert store.state(code, ("小明", "k" * 20))["pastor"] is False
    assert store.state(pastors, ("小明", "k" * 20))["pastor"] is True
    url = store.begin_google_login("查經班·小明#abc", "https://theoclaw.app/auth/google/callback", code)
    pending = store.take_pending(parse_qs(urlparse(url).query)["state"][0])
    assert pending["code"] == code and pending["bind"] == "查經班·小明#abc"  # back to the same link


def test_signed_in_member_switches_to_pastor_mode_with_all_their_questions(tmp_path):
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    lay = hs.add_group("查經班", path)
    pastors = hs.add_group("牧者", path, role="pastor")
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0, "sermon_daily_limit": 5},
                     chat_dir=tmp_path / "chat")
    me = ("小明", "k" * 20)
    _consent(store, lay, me)
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "答", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    job = store.ask(lay, "平信徒時問的", runner=fake, nick=me)["job"]
    _wait(store, lay, job, me)
    name = store.who(lay, me)["name"]
    store.db.put_google_account(hs.google_sub_hash("sub-1", store.google_salt()), name)
    store.set_session(name)  # the Google account, now visiting either link
    member = store.state(lay, me)
    preacher = store.state(pastors, me)
    assert member["pastor"] is False and "sermon" not in member["chat"]
    assert preacher["pastor"] is True and preacher["chat"]["sermon"]
    assert [q["prompt"] for q in preacher["chat"]["questions"]] == ["平信徒時問的"]  # the same account's records


def test_env_passcode_seeds_the_first_fellowship(tmp_path, monkeypatch):
    monkeypatch.setenv("THEOCLAW_PASTOR_CODE", " seed42 ")
    store = hs.Store(tmp_path / "assignment.json", chat_dir=tmp_path / "chat")  # any Store seeds it once
    assert store.db.fellowship("seed42")["role"] == "pastor"
    monkeypatch.setenv("THEOCLAW_PASTOR_CODE", "other99")
    again = hs.Store(tmp_path / "assignment.json", chat_dir=tmp_path / "chat")  # existing rows stay
    assert again.db.fellowship("other99") is None


def test_google_config_cleans_pasted_invisible_characters(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "\u200b123456789012-abc_DEF-123.apps.googleusercontent.com\ufeff")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", " GOCSPX-test ")
    cfg = hs.google_config()
    assert cfg["client_id"] == "123456789012-abc_DEF-123.apps.googleusercontent.com"
    assert cfg["client_secret"] == "GOCSPX-test"
    assert hs.google_id_problem(cfg["client_id"]) == ""
    assert hs.google_id_problem("GOCSPX-test")   # the secret pasted into the ID line
    assert hs.google_id_problem("123456789012-abc")  # copied without the ending


def test_google_check_separates_unknown_client_from_unregistered_redirect(monkeypatch):
    import io
    import urllib.error

    def failing(body):
        def open_(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body))
        return open_

    cid = "123456789012-abc_DEF-123.apps.googleusercontent.com"
    monkeypatch.setattr(hs.urllib.request, "urlopen",
                        failing(b"Error 401: invalid_client. The OAuth client was not found."))
    state, msg = hs.google_client_check(cid, "https://theoclaw.app/auth/google/callback")
    assert state == "client" and "不認識" in msg
    monkeypatch.setattr(hs.urllib.request, "urlopen", failing(b"Error 400: redirect_uri_mismatch"))
    state, msg = hs.google_client_check(cid, "https://theoclaw.app/auth/google/callback")
    assert state == "redirect" and "重新導向" in msg


def test_a_failed_answer_is_kept_but_not_shown_or_counted(tmp_path):
    code = hs.add_group("查經班", path=tmp_path / "assignment.json")
    store = hs.Store(tmp_path / "assignment.json", chat={"model": "deepseek-flash", "daily_limit": 1, "budget_usd": 1.0},
                     chat_dir=tmp_path / "pastor-chat")
    me = ("小明", "k" * 20)
    _consent(store, code, me)
    failed = lambda q: {"model": "deepseek-flash", "prompt": q, "final_text": "", "outcome": "api_error",
                        "error": "ProviderAPIError: RateLimitError", "steps": [], "usage_total": {}, "cost_usd": 0.0}
    job = store.ask(code, "會失敗的問題", runner=failed, nick=me)["job"]
    for _ in range(50):
        if store.job(code, job, me)["status"] != "running":
            break
        time.sleep(0.05)
    j = store.job(code, job, me)
    assert j["status"] == "error" and "不計入" in j["error"]
    state = store.state(code, me)["chat"]
    assert state["remaining_today"] == 1 and state["questions"] == []
    assert [a["outcome"] for a in store.db.answers()] == ["api_error"]  # kept, to see why it failed


def test_no_api_key_is_reported_at_once(tmp_path):
    code = hs.add_group("查經班", path=tmp_path / "assignment.json")
    store = hs.Store(tmp_path / "assignment.json", chat={"model": "deepseek-flash", "daily_limit": 5, "budget_usd": 1.0},
                     chat_dir=tmp_path / "pastor-chat")
    me = ("小明", "k" * 20)
    _consent(store, code, me)

    def no_key(q):
        raise SystemExit("no API key for provider deepseek: set DEEPSEEK_API_KEY in .env or the environment")

    job = store.ask(code, "沒有金鑰", runner=no_key, nick=me)["job"]
    for _ in range(50):
        if store.job(code, job, me)["status"] != "running":
            break
        time.sleep(0.05)
    assert "金鑰" in store.job(code, job, me)["error"]


def test_two_scores_earn_one_more_question(tmp_path, storage):
    path = tmp_path / "assignment.json"
    hs.prepare([], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 2, "budget_usd": 1.0}, chat_dir=tmp_path / "pastor-chat")
    fake = lambda q: {"model": "m", "prompt": q, "final_text": "answer", "outcome": "completed",
                      "steps": [], "usage_total": {}, "cost_usd": 0.001}
    nick = ("Ruth", "r" * 20)
    _consent(store, code, nick)
    for q in ("第一題", "第二題"):
        assert "job" in store.ask(code, q, runner=fake, nick=nick)
        time.sleep(0.3)
    assert "每評分 2 個回答，可以多問一題" in store.ask(code, "第三題", runner=fake, nick=nick)["error"]
    chat = store.state(code, nick)["chat"]
    assert chat["remaining_today"] == 0 and chat["ratings_to_bonus"] == 2
    first, second = [q["id"] for q in chat["questions"]]
    assert store.rate(code, {"id": first, "quick": "up"}, nick) is None
    assert store.rate(code, {"id": first, "scores": {"overall": 8}}, nick) is None  # the same answer again: still one
    assert store.rate(code, {"id": second, "skip": True}, nick) is None              # a skip is not a score
    assert store.state(code, nick)["chat"]["ratings_to_bonus"] == 1
    assert store.rate(code, {"id": second, "quick": "down"}, nick) is None
    chat = store.state(code, nick)["chat"]
    assert chat["remaining_today"] == 1 and chat["ratings_to_bonus"] == 2
    assert "job" in store.ask(code, "第三題", runner=fake, nick=nick)


def _post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def _open(url):
    """(status, headers, body text) of a page, 404 included."""
    try:
        r = urllib.request.urlopen(url)
    except urllib.error.HTTPError as e:
        r = e
    return r.status if hasattr(r, "status") else r.code, r.headers, r.read().decode("utf-8")


def test_sharing_one_answer(tmp_path, monkeypatch):
    monkeypatch.delenv("THEOCLAW_URL", raising=False)
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("祕密團契", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0}, chat_dir=tmp_path / "chat")
    me, other = ("小明祕密暱稱", "k" * 20), ("小華", "m" * 20)
    _consent(store, code, me)
    _consent(store, code, other)
    answers = iter(["# 重點\n**神的愛**：羅馬書 8 章說<b>沒有</b>定罪。" + "長" * 200, "第二輪的祕密回答"])

    def fake(prompt):
        return {"model": "secret-model", "prompt": prompt, "final_text": next(answers), "outcome": "completed",
                "steps": [], "usage_total": {}, "cost_usd": 0.0123}

    first = store.ask(code, "羅馬書 8 章的<重點>？", runner=fake, nick=me)
    item = _wait(store, code, first["job"], me)["item"]
    second = store.ask(code, "第二輪的祕密問題", runner=fake, nick=me, conv=first["conv"])
    _wait(store, code, second["job"], me)
    srv, base = _serve(store)
    q = "?" + urlencode({"t": code, "u": me[0], "k": me[1]})
    q_other = "?" + urlencode({"t": code, "u": other[0], "k": other[1]})
    try:
        assert "error" in _post(base, "/api/share" + q_other, {"id": item})  # not theirs
        url = _post(base, "/api/share" + q, {"id": item})["url"]
        assert url.startswith(base + "/s/") and _post(base, "/api/share" + q, {"id": item})["url"] == url  # same link again
        conv = json.loads(urllib.request.urlopen(base + "/api/conversation" + q + "&id=" + first["conv"]).read())
        assert [t["share"] for t in conv["turns"]] == [url, None]  # the state survives a reload

        status, headers, page = _open(url)
        assert status == 200 and headers["X-Robots-Tag"].startswith("noindex") and headers["Referrer-Policy"] == "no-referrer"
        assert 'name="robots" content="noindex' in page
        assert '<meta property="og:title" content="羅馬書 8 章的&lt;重點&gt;？">' in page
        desc = page.split('og:description" content="')[1].split('"')[0]
        assert desc.startswith("重點 神的愛：羅馬書 8 章說") and "**" not in desc and "<b>" not in desc and desc.endswith("…")
        for secret in ("小明祕密暱稱", code, "第二輪的祕密", "secret-model", "0.0123", "祕密團契"):
            assert secret not in page
        data = json.loads(page.split('<script id="shareData" type="application/json">')[1].split("</script>")[0])
        assert set(data) == {"ask", "reply", "lang"} and data["ask"] == "羅馬書 8 章的<重點>？"
        assert "<重點>" not in page  # escaped inside the script tag too
        assert store.db.share(url.rsplit("/", 1)[1])["views"] == 1

        assert "error" in _post(base, "/api/share/revoke" + q_other, {"id": item})
        assert _open(url)[0] == 200  # still works after someone else tried
        assert _post(base, "/api/share/revoke" + q, {"id": item}) == {"ok": True}
        gone = _open(url)
        unknown = _open(base + "/s/doesNotExist123")
        assert gone[0] == unknown[0] == 404 and gone[2] == unknown[2]  # revoked and unknown look the same
        assert '"gone": true' in gone[2] and "羅馬書" not in gone[2]
        assert _open(base + "/s/bad!token")[0] == 404
        again = _post(base, "/api/share" + q, {"id": item})["url"]
        assert again != url  # a new link after revoking; the old one stays dead
        assert _open(url)[0] == 404 and _open(again)[0] == 200
    finally:
        srv.shutdown()


def test_share_limits_and_sermon_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(hs, "SHARE_DAILY_LIMIT", 1)
    a = _run(tmp_path, "a", 1)
    path = tmp_path / "assignment.json"
    hs.prepare([str(a)], ["牧者1"], None, None, path)
    code = hs.add_group("查經班", path)
    store = hs.Store(path, chat={"model": "m", "daily_limit": 9, "budget_usd": 1.0}, chat_dir=tmp_path / "chat")
    me = ("小明", "k" * 20)
    _consent(store, code, me)
    fake = lambda p: {"model": "m", "prompt": p, "final_text": "答", "outcome": "completed", "steps": [],
                      "usage_total": {}, "cost_usd": 0.0}
    items = [_wait(store, code, store.ask(code, f"問題{i}", runner=fake, nick=me)["job"], me)["item"] for i in range(2)]
    assert "token" in store.share(code, items[0], me)
    assert "token" in store.share(code, items[0], me)  # the same link again is not a new one
    assert "明天" in store.share(code, items[1], me)["error"]
    assert "error" in store.share(code, "nope", me) and store.shared("") is None
    sermon_fake = lambda p: {"kind": "sermon_turn", **fake(p)}
    j = _wait(store, code, store.ask(code, "講章的一步", runner=sermon_fake, nick=me)["job"], me)
    assert "error" in store.share(code, j["item"], me)  # only plain questions are shared for now
