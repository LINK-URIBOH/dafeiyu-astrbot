#!/bin/bash
# 每日备份：AstrBot 数据 + NapCat 配置 + 部署文件，滚动保留最近 7 份
# 用法：./backup.sh [base_dir]   # 默认 /opt/dafeiyu
# 定时：crontab 里加一行（用绝对路径）：
#   17 3 * * * /opt/dafeiyu/backup.sh
#
# 一致性策略：先短暂停掉 astrbot 容器（SQLite 在写入中直接打包可能拿到不一致快照），
# 打包完立刻恢复；napcat/config 是纯文件，可直接打。
# 恢复后自动跑 heal_ws.py 自愈 NapCat<->AstrBot 的 WebSocket
# （AstrBot 重启后 WS 不会自己回来，这是实测过的老毛病）。
set -uo pipefail
BASE="${1:-/opt/dafeiyu}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$BASE/backups/backup.log"
mkdir -p "$BASE/backups"
cd "$BASE" || { echo "cd $BASE 失败"; exit 1; }

STOPPED=0
if docker compose stop astrbot >>"$LOG" 2>&1; then
  STOPPED=1
else
  echo "$(date '+%F %T') [WARN] 停 astrbot 失败，继续尝试备份（快照可能不一致）" >>"$LOG"
fi

# 先写临时包，成功后再改名（失败不留半截包）
TMP="$BASE/backups/.tmp_backup_${TS}.tar.gz"
rc=0
if tar -czf "$TMP" \
    astrbot/data \
    napcat/config \
    compose.yaml Dockerfile patches heal_ws.py \
    >>"$LOG" 2>&1; then
  mv "$TMP" "backups/dafeiyu_backup_${TS}.tar.gz"
  echo "$(date '+%F %T') backup done: dafeiyu_backup_${TS}.tar.gz" >>"$LOG"
else
  rm -f "$TMP"
  echo "$(date '+%F %T') [ERROR] 备份失败（tar 非 0 退出），详见本日志" >>"$LOG"
  rc=1
fi

# 恢复容器，并自愈 WS（等 AstrBot 起来再拨一次 NapCat 的 websocket 开关）
if [ "$STOPPED" = "1" ]; then
  { docker compose start astrbot || docker start astrbot; } >>"$LOG" 2>&1 || true
  sleep 25
  if [ -f "$BASE/heal_ws.py" ]; then
    python3 "$BASE/heal_ws.py" >>"$LOG" 2>&1 || true
  fi
fi

# 只留最近 7 份
ls -1t backups/dafeiyu_backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f

exit "$rc"
