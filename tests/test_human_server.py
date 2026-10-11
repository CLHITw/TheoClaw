import importlib.util
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("human_server", ROOT / "human_scoring" / "human_server.py")
hs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hs)


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


def test_blind_items_full_tools_and_ratings_on_disk(tmp_path):
    a, b = _run(tmp_path, "a"), _run(tmp_path, "b")
    path = tmp_path / "assignment.json"
    data = hs.prepare([str(a), str(b)], ["王牧師"], None, None, path)
    code = next(iter(data["raters"]))
    assert hs.prepare([str(a), str(b)], ["王牧師"], None, None, path)["raters"].keys() == {code}  # same link again
    store = hs.Store(path)
    st = store.state(code)
    assert st["rater"] == "王牧師" and len(st["order"]) == 6 and st["done"] == []
    it = store.item(code, st["order"][0])
    assert "secret-model" not in json.dumps(it, ensure_ascii=False) and "task_id" not in it
    assert len(it["tools"][0]["output"]) == 2000  # not cut short
    dims = {d["key"]: 4 for d in st["rubric"]["dimensions"]}
    assert store.rate(code, {"id": it["id"], "scores": dims, "verdict": None}) == "請選擇總評"
    assert "還沒有評分" in store.rate(code, {"id": it["id"], "scores": {}, "verdict": True})
    assert store.rate(code, {"id": it["id"], "scores": dims, "verdict": False, "problems": ["shallow", "bogus"]}) is None
    rec = [json.loads(x) for p in (a, b) if (p / "human" / "王牧師.jsonl").exists()
           for x in (p / "human" / "王牧師.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rec) == 1 and rec[0]["problems"] == ["shallow"] and rec[0]["blind"] and rec[0]["verdict"] is False
    assert hs.Store(path).state(code)["done"] == [it["id"]]  # survives a restart
    assert store.item(code, it["id"])["previous"]["verdict"] is False


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
    rec = json.loads((chat_dir / "human" / "牧者1.jsonl").read_text(encoding="utf-8"))
    assert rec["mode"] == "chat" and rec["blind"] is False
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
