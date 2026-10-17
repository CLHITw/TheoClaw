import importlib.util
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("human_server", ROOT / "human_scoring" / "human_server.py")
hs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hs)


@pytest.fixture(autouse=True, params=["files", "db"])
def storage(request, tmp_path, monkeypatch):
    """Every server test on both storages; the database is each test's own SQLite file,
    never the project's or the server's."""
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
    assert "團契" in store.ask(code, "第三題", runner=fake, nick=("小李", "l" * 20))["error"]  # group daily limit 2


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
