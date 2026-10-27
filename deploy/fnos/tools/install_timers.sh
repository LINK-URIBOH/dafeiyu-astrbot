#!/bin/bash
set -Eeuo pipefail
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for unit in dafeiyu-backup.service dafeiyu-heal.service; do
    path="/etc/systemd/system/$unit"
    if [[ -e "$path" ]] && ! grep -qF "$BASE/tools/" "$path"; then
        echo "Refusing to replace unrelated unit: $path" >&2
        exit 1
    fi
done
chmod 700 "$BASE/tools/backup.sh"
cat > /etc/systemd/system/dafeiyu-backup.service <<EOF
[Unit]
Description=Dafeiyu isolated application backup
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
UMask=0077
WorkingDirectory=$BASE
ExecStart=/bin/bash $BASE/tools/backup.sh
EOF
cat > /etc/systemd/system/dafeiyu-backup.timer <<EOF
[Unit]
Description=Daily Dafeiyu backup at 03:17 Asia/Shanghai

[Timer]
OnCalendar=*-*-* 03:17:00 Asia/Shanghai
Persistent=true
Unit=dafeiyu-backup.service

[Install]
WantedBy=timers.target
EOF
cat > /etc/systemd/system/dafeiyu-heal.service <<EOF
[Unit]
Description=Check and repair only Dafeiyu's OneBot connection
After=docker.service

[Service]
Type=oneshot
UMask=0077
WorkingDirectory=$BASE
ExecStart=/usr/bin/python3 $BASE/tools/heal_ws.py
EOF
cat > /etc/systemd/system/dafeiyu-heal.timer <<EOF
[Unit]
Description=Dafeiyu OneBot connection check

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
Unit=dafeiyu-heal.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now dafeiyu-backup.timer dafeiyu-heal.timer
systemctl list-timers --all 'dafeiyu-*' --no-pager
