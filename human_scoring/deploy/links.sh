#!/usr/bin/env bash
# 印出可以直接打開的完整連結（通道網址 + 代碼）。通道重啟後網址會變，再執行一次即可：
#   sudo bash /opt/theoclaw/human_scoring/deploy/links.sh
APP=/opt/theoclaw
TUNNEL=theoclaw-tunnel
URL=""
for i in $(seq 1 15); do
  URL=$(journalctl -u "$TUNNEL" --no-pager | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1)
  [ -n "$URL" ] && break
  sleep 2
done
if [ -z "$URL" ]; then
  echo "通道網址還沒出現，稍等再執行：sudo bash $APP/human_scoring/deploy/links.sh ${1:-}"
  exit 0
fi
"$APP/.venv/bin/python" - "$URL" "$APP/human_scoring/assignment.json" "${1:-}" <<'PY'
import json, sys
url, path, which = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
raters = json.load(open(path, encoding="utf-8"))["raters"]
groups = [(c, r) for c, r in raters.items() if r.get("group")]
people = [(c, r) for c, r in raters.items() if not r.get("group")]
print("對外網址（每次重啟 theoclaw-tunnel 會換新的）：" + url)
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
