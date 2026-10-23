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
#
# 恢复失败必须让脚本非零退出：以前恢复命令都挂 || true，打包成功而容器没起来
# 也返回 0，任务看着成功、机器人却是停的。被中断时也走同一条恢复路径。
set -uo pipefail
BASE="${1:-/opt/dafeiyu}"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$BASE/backups/backup.log"
mkdir -p "$BASE/backups"
cd "$BASE" || { echo "cd $BASE 失败"; exit 1; }

rc=0
STOPPED=0
RESTORED=0

# 备份前容器是否在跑：本来就没跑就别顺手把它拉起来（保留执行前状态）
WAS_RUNNING=1
if docker inspect -f '{{.State.Running}}' astrbot 2>/dev/null | grep -q false; then
  WAS_RUNNING=0
fi

restore_astrbot() {
  # 只在本次确实停过容器时恢复；任何一步失败都记 ERROR 并置 rc=1
  if [ "$STOPPED" != "1" ] || [ "$RESTORED" = "1" ]; then
    return 0
  fi
  RESTORED=1
  if ! { docker compose start astrbot >>"$LOG" 2>&1 || docker start astrbot >>"$LOG" 2>&1; }; then
    echo "$(date '+%F %T') [ERROR] astrbot 恢复启动失败（compose start 和 docker start 都失败），机器人可能仍在停止状态，请手动执行 docker compose start astrbot" >>"$LOG"
    rc=1
    return 1
  fi
  sleep 25
  if [ "$(docker inspect -f '{{.State.Running}}' astrbot 2>/dev/null)" != "true" ]; then
    echo "$(date '+%F %T') [ERROR] astrbot 容器启动后未处于 Running 状态，请检查 docker logs astrbot" >>"$LOG"
    rc=1
    return 1
  fi
  if [ -f "$BASE/heal_ws.py" ]; then
    heal_out=$(python3 "$BASE/heal_ws.py" 2>&1)
    heal_rc=$?
    printf '%s\n' "$heal_out" >>"$LOG"
    if [ "$heal_rc" -ne 0 ]; then
      echo "$(date '+%F %T') [ERROR] heal_ws.py 退出码 $heal_rc，NapCat<->AstrBot 可能未重连，请手动检查" >>"$LOG"
      rc=1
      return 1
    fi
    case "$heal_out" in
      *"30 秒内未重连成功"*)
        echo "$(date '+%F %T') [ERROR] heal_ws.py 30 秒内未重连成功，NapCat<->AstrBot 仍是断的，请手动检查" >>"$LOG"
        rc=1
        return 1
        ;;
    esac
  fi
  return 0
}

on_exit() {
  local code=$?
  trap - EXIT INT TERM
  restore_astrbot
  if [ "$code" -ne 0 ]; then
    exit "$code"
  fi
  exit "$rc"
}

on_signal() {
  trap - EXIT INT TERM
  restore_astrbot
  exit 130
}

trap on_exit EXIT
trap on_signal INT TERM

if [ "$WAS_RUNNING" = "1" ]; then
  if docker compose stop astrbot >>"$LOG" 2>&1; then
    STOPPED=1
  else
    echo "$(date '+%F %T') [WARN] 停 astrbot 失败，继续尝试备份（快照可能不一致）" >>"$LOG"
  fi
else
  echo "$(date '+%F %T') [INFO] astrbot 备份前已处于停止状态，跳过停止/恢复" >>"$LOG"
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
# 恢复失败会置 rc=1；提前退出或 Ctrl-C 由 on_exit/on_signal 兜底走同一条路径
restore_astrbot

# 只留最近 7 份
ls -1t backups/dafeiyu_backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f

exit "$rc"
