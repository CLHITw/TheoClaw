#!/usr/bin/env bash
# 印出可以直接打開的完整連結（網址 + 代碼）：
#   sudo bash /opt/theoclaw/human_scoring/deploy/links.sh
# 網址用 .env 的 THEOCLAW_URL；沒有就用 https://theoclaw.app（舊的臨時通道 theoclaw-tunnel 已不再使用）。
APP=/opt/theoclaw
URL=$(sed -n 's/^THEOCLAW_URL=[[:space:]]*\([^[:space:]]*\).*/\1/p' "$APP/.env" 2>/dev/null | tail -1)
URL=${URL:-https://theoclaw.app}
"$APP/.venv/bin/python" - "$URL" "$APP/human_scoring/assignment.json" "${1:-}" <<'PY'
import json, sys
url, path, which = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
raters = json.load(open(path, encoding="utf-8"))["raters"]
groups = [(c, r) for c, r in raters.items() if r.get("group")]
people = [(c, r) for c, r in raters.items() if not r.get("group")]
print("對外網址：" + url)
print()
for c, r in groups:
    role = "牧者，有講道預備" if r.get("role") == "pastor" else "平信徒，只能提問"
    print(f"★ {r['name']}（{role}；大家共用，發到群組即可，不要公開張貼）：")
    print(f"  {url}/?t={c}")
print()
print("個人連結：")
for c, r in people:
    print(f"  {r['name']}: {url}/?t={c}")
PY
