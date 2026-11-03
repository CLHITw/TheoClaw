#!/usr/bin/env bash
# 在 Ubuntu VPS 上安裝或更新 TheoClaw 線上評分（以 root 或 sudo 執行）：
#   sudo bash setup.sh theoclaw-scoring.tar.gz
# 第一次安裝後，請建立 /opt/theoclaw/.env，內容一行：DEEPSEEK_API_KEY=你的金鑰（提問模式需要），
# 然後 sudo systemctl restart theoclaw-scoring。
# 再次執行本腳本是更新程式：已有的評分（runs/*/human/、runs/pastor-chat/）與 .env 都會保留。
# 更新前先把整個 /opt/theoclaw 備份到 /opt/theoclaw.bak-prev（只留最近一份），最後印出退回命令。
# 各宗派的知識庫（knowledge/<宗派>.en.deepseek-flash）包裡只帶循道衛理；其他宗派缺的話從測試伺服器
# （/home/trainer/theoclaw-test/knowledge）複製過來。已有的知識庫檔案不刪除。
# 首頁（不帶代碼的網址）讓人選信徒或牧者：牧者要輸入團契碼（human_server.PASTOR_CODE；.env 的 THEOCLAW_PASTOR_CODE 可覆寫）。
# 資料存在 MySQL：.env 有一行 THEOCLAW_DB=mysql+pymysql://theoclaw:密碼@localhost/theoclaw?charset=utf8mb4
# （沒有就用 runs/pastor-chat/theoclaw.db 這個 SQLite 檔）。啟動時會把舊檔案裡還沒進資料庫的資料匯入（不重複）。
# 測試用（不需要 root）：THEOCLAW_APP=/tmp/x THEOCLAW_SANDBOX=1 bash setup.sh theoclaw-scoring.tar.gz
#   只做備份、解壓、合併 assignment.json、補知識庫，跳過 apt、使用者、venv、chown、systemd 與健康檢查。
set -euo pipefail

TARBALL="${1:?用法：sudo bash setup.sh theoclaw-scoring.tar.gz}"
APP="${THEOCLAW_APP:-/opt/theoclaw}"
BACKUP="$APP.bak-prev"
TEST_KB="${THEOCLAW_TEST_KB:-/home/trainer/theoclaw-test/knowledge}"
SANDBOX="${THEOCLAW_SANDBOX:-}"
USER_NAME=theoclaw
PORT=8765
ROLLBACK="sudo systemctl stop theoclaw-scoring && sudo rm -rf $APP.failed && sudo mv $APP $APP.failed && sudo cp -a $BACKUP $APP && sudo systemctl start theoclaw-scoring"

if [ -z "$SANDBOX" ]; then
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv curl >/dev/null
  id -u "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin "$USER_NAME"
fi

# 備份：只留最近一份，出問題時用最後印出的退回命令還原
HAD_BACKUP=
if [ -d "$APP" ]; then
  echo "備份 $APP → $BACKUP ..."
  rm -rf "$BACKUP"
  cp -a "$APP" "$BACKUP"
  HAD_BACKUP=1
fi
mkdir -p "$APP"
# 解壓到暫存再複製，保留伺服器上已有的評分與 .env
TMP=$(mktemp -d)
tar -xzf "$TARBALL" -C "$TMP"
# assignment.json：包裡的評分名單加上伺服器上已有的評分人與團體連結（在 VPS 上建立的連結不會因更新而失效）
if [ -f "$APP/human_scoring/assignment.json" ]; then
  python3 - "$TMP/theoclaw/human_scoring/assignment.json" "$APP/human_scoring/assignment.json" <<'PY'
import json, sys
new_path, old_path = sys.argv[1], sys.argv[2]
new, old = json.load(open(new_path, encoding="utf-8")), json.load(open(old_path, encoding="utf-8"))
for code, r in old.get("raters", {}).items():
    new.setdefault("raters", {}).setdefault(code, r)
json.dump(new, open(new_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
fi
cp -r "$TMP/theoclaw/." "$APP/"
rm -rf "$TMP"

# 各宗派知識庫：清單取自程式（theoclaw/common/denominations.py 的 kb="..."）；缺的從測試伺服器複製
KB_MISSING=
mkdir -p "$APP/knowledge"
for kb in $(grep -o 'kb="[^"]*"' "$APP/theoclaw/common/denominations.py" | cut -d'"' -f2 | sort -u); do
  if [ -f "$APP/knowledge/$kb/wiki/index.md" ]; then
    echo "知識庫 $kb：已有"
  elif [ -f "$TEST_KB/$kb/wiki/index.md" ]; then
    echo "知識庫 $kb：從 $TEST_KB 複製"
    mkdir -p "$APP/knowledge/$kb"
    cp -a "$TEST_KB/$kb/." "$APP/knowledge/$kb/"
  else
    echo "!!!!!!!! WARNING：知識庫 $kb 在 $APP/knowledge 和 $TEST_KB 都找不到，這個宗派的問題沒有知識庫可查 !!!!!!!!"
    KB_MISSING="$KB_MISSING $kb"
  fi
done

if [ -n "$SANDBOX" ]; then
  echo "THEOCLAW_SANDBOX：已解壓到 $APP，跳過 venv、systemd 與健康檢查。"
  exit 0
fi

python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements-server.txt"
touch "$APP/.env"; chmod 600 "$APP/.env"
chown -R "$USER_NAME:$USER_NAME" "$APP"

# cloudflared（theoclaw.app 的命名通道 cloudflared.service 需要；通道本身在 Cloudflare 後台建立）
if ! command -v cloudflared >/dev/null; then
  ARCH=$(dpkg --print-architecture)
  curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  dpkg -i /tmp/cloudflared.deb
fi

install -m 644 "$APP/human_scoring/deploy/theoclaw-scoring.service" /etc/systemd/system/
# 舊的臨時通道（trycloudflare 網址）不再使用：網站只走 https://theoclaw.app。還裝著的伺服器在這裡關掉並移除。
systemctl disable --now theoclaw-tunnel 2>/dev/null || true
rm -f /etc/systemd/system/theoclaw-tunnel.service
systemctl daemon-reload
systemctl enable --now theoclaw-scoring
systemctl restart theoclaw-scoring
systemctl disable --now theoclaw-scoring-db theoclaw-tunnel-db 2>/dev/null || true   # the short-lived test pair

# 健康檢查：服務在跑、首頁回 200、程式認得各宗派知識庫（最多等 30 秒）
CODE=000
for i in $(seq 1 15); do
  sleep 2
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$PORT/" || true)
  [ "$CODE" = 200 ] && break
done
ACTIVE=$(systemctl is-active theoclaw-scoring || true)
KB_CHECK=$(cd "$APP" && sudo -u "$USER_NAME" "$APP/.venv/bin/python" -c '
from pathlib import Path
from theoclaw.common.denominations import DENOMS
bad = [d.key for d in DENOMS.values() if not (Path("knowledge") / d.kb / "wiki" / "index.md").is_file()]
print("缺：" + ",".join(bad) if bad else "OK")' 2>/dev/null || echo "檢查失敗")

echo
echo "評分伺服器狀態："; systemctl --no-pager --lines=3 status theoclaw-scoring || true
echo
echo "網站：https://theoclaw.app"
bash "$APP/human_scoring/deploy/links.sh" || true
echo
echo "服務：$ACTIVE　首頁：$CODE　宗派知識庫：$KB_CHECK"
if [ "$ACTIVE" = active ] && [ "$CODE" = 200 ] && [ "$KB_CHECK" = OK ]; then
  echo "========== 部署成功 =========="
  [ -n "$HAD_BACKUP" ] && echo "（若要退回上一版：$ROLLBACK）"
else
  echo "========== 部署失敗 =========="
  echo "看日誌：sudo journalctl -u theoclaw-scoring -n 50 --no-pager"
  [ -n "$HAD_BACKUP" ] && echo "退回上一版：$ROLLBACK"
  exit 1
fi
