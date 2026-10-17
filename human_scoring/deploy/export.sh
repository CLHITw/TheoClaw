#!/usr/bin/env bash
# 把 VPS 上收集到的回饋打成一個檔案，帶回本機分析：
#   sudo bash /opt/theoclaw/human_scoring/deploy/export.sh
# 內容：runs/pastor-chat/（提問、回答、評分、講章工作區、花費）、各盲評 runs 的 human/ 評分、
# assignment.json（評分人與團體連結代碼）。全部是使用者的私人資料：只放本機的 runs/ 底下（git 不追蹤），不要上傳。
set -euo pipefail
APP=/opt/theoclaw
OUT=/root/theoclaw-feedback-$(date +%Y%m%d-%H%M).tar.gz
cd "$APP/runs"
HUMAN=$(ls -d */human 2>/dev/null | grep -v '^pastor-chat/' || true)
tar -czf "$OUT" pastor-chat $HUMAN -C "$APP/human_scoring" assignment.json
echo "已寫出 $OUT（$(du -h "$OUT" | cut -f1)）"
