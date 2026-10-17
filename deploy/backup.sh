#!/bin/bash
# 每日备份：AstrBot 数据 + NapCat 配置，滚动保留最近 7 份
# 用法：./backup.sh [base_dir]   # 默认 /opt/dafeiyu
# 定时：crontab 里加一行
#   17 3 * * * /opt/dafeiyu/backup.sh
set -e
BASE="${1:-/opt/dafeiyu}"
TS=$(date +%Y%m%d_%H%M%S)
cd "$BASE"
mkdir -p backups
tar -czf "backups/dafeiyu_backup_${TS}.tar.gz" astrbot/data napcat/config 2>/dev/null
# 只留最近 7 份
ls -1t backups/dafeiyu_backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
echo "$(date '+%F %T') backup done: dafeiyu_backup_${TS}.tar.gz" >> backups/backup.log
