#!/usr/bin/env bash
# 把 VPS 上收集到的回饋（資料庫裡的提問、回答、評分、講章、花費、連結）匯出成評測工具讀的檔案格式，
# 打成一個檔案帶回本機：
#   sudo bash /opt/theoclaw/human_scoring/deploy/export.sh
# 全部是使用者的私人資料：本機請放在 runs/ 或 runs_vps/ 底下（git 不追蹤），不要上傳。
set -euo pipefail
APP=/opt/theoclaw
STAMP=$(date +%Y%m%d-%H%M)
TMP=$(mktemp -d)
cd "$APP"
"$APP/.venv/bin/python" human_scoring/db.py export "$TMP"
OUT=/root/theoclaw-feedback-$STAMP.tar.gz
tar -czf "$OUT" -C "$TMP" .
rm -rf "$TMP"
echo "已寫出 $OUT（$(du -h "$OUT" | cut -f1)）"
