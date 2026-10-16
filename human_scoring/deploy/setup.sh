#!/usr/bin/env bash
# 在 Ubuntu VPS 上安裝或更新 TheoClaw 線上評分（以 root 或 sudo 執行）：
#   sudo bash setup.sh theoclaw-scoring.tar.gz
# 第一次安裝後，請建立 /opt/theoclaw/.env，內容一行：DEEPSEEK_API_KEY=你的金鑰（提問模式需要），
# 然後 sudo systemctl restart theoclaw-scoring。
# 再次執行本腳本是更新程式：已有的評分（runs/*/human/、runs/pastor-chat/）與 .env 都會保留。
set -euo pipefail

TARBALL="${1:?用法：sudo bash setup.sh theoclaw-scoring.tar.gz}"
APP=/opt/theoclaw
USER_NAME=theoclaw

apt-get update -qq
apt-get install -y -qq python3 python3-venv curl >/dev/null

id -u "$USER_NAME" >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin "$USER_NAME"
mkdir -p "$APP"
# 解壓到暫存再複製，保留伺服器上已有的評分與 .env
TMP=$(mktemp -d)
tar -xzf "$TARBALL" -C "$TMP"
cp -r "$TMP/theoclaw/." "$APP/"
rm -rf "$TMP"

python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements-server.txt"
touch "$APP/.env"; chmod 600 "$APP/.env"
chown -R "$USER_NAME:$USER_NAME" "$APP"

# cloudflared（沒有網域時用它取得 https 網址）
if ! command -v cloudflared >/dev/null; then
  ARCH=$(dpkg --print-architecture)
  curl -fsSL -o /tmp/cloudflared.deb "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb"
  dpkg -i /tmp/cloudflared.deb
fi

install -m 644 "$APP/human_scoring/deploy/theoclaw-scoring.service" /etc/systemd/system/
install -m 644 "$APP/human_scoring/deploy/theoclaw-tunnel.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now theoclaw-scoring theoclaw-tunnel
systemctl restart theoclaw-scoring

sleep 8
echo "評分伺服器狀態："; systemctl --no-pager --lines=3 status theoclaw-scoring || true
echo
bash "$APP/human_scoring/deploy/links.sh"
