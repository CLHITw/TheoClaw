#!/usr/bin/env bash
# 把 VPS 上收集到的回饋打成一個檔案，帶回本機分析：
#   sudo bash /opt/theoclaw/human_scoring/deploy/export.sh          從資料庫（MySQL）匯出
#   sudo bash /opt/theoclaw/human_scoring/deploy/export.sh files    伺服器以 --storage files 執行時，直接打包檔案
# 內容：pastor-chat/（提問、回答、評分、講章、花費）、各盲評 runs 的 human/ 評分、assignment.json。
# 全部是使用者的私人資料：本機請放在 runs/ 或 runs_vps/ 底下（git 不追蹤），不要上傳。
set -euo pipefail
APP=/opt/theoclaw
STAMP=$(date +%Y%m%d-%H%M)
if [ "${1:-}" != "files" ]; then
  OUT=/root/theoclaw-feedback-db-$STAMP.tar.gz
  TMP=$(mktemp -d)
  cd "$APP"
  "$APP/.venv/bin/python" human_scoring/db.py export "$TMP"
  tar -czf "$OUT" -C "$TMP/runs" . -C "$TMP" assignment.json
  rm -rf "$TMP"
else
  OUT=/root/theoclaw-feedback-$STAMP.tar.gz
  cd "$APP/runs"
  HUMAN=$(ls -d */human 2>/dev/null | grep -v '^pastor-chat/' || true)
  tar -czf "$OUT" pastor-chat $HUMAN -C "$APP/human_scoring" assignment.json
fi
echo "已寫出 $OUT（$(du -h "$OUT" | cut -f1)）"
