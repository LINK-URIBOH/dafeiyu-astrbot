#!/bin/bash
set -Eeuo pipefail
umask 077
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$BASE"
mkdir -p backups
exec 9>backups/backup.lock
flock -n 9 || exit 0
RUNNING=$(docker inspect -f '{{.State.Running}}' dafeiyu-astrbot)
STOPPED=0
RESTORED=0
restore() {
    if [[ "$STOPPED" == 1 && "$RESTORED" == 0 ]]; then
        RESTORED=1
        docker compose start astrbot
        for attempt in $(seq 1 60); do
            if curl -sf --max-time 2 http://127.0.0.1:6185/api/v1/auth/setup-status >/dev/null; then
                python3 tools/heal_ws.py
                return $?
            fi
            sleep 2
        done
        echo 'ERROR: AstrBot did not recover within 120 seconds' >&2
        return 1
    fi
}
cleanup() {
    result=$?
    trap - EXIT INT TERM
    restore || result=1
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if [[ "$RUNNING" == true ]]; then
    docker compose stop astrbot
    STOPPED=1
fi
STAMP=$(date +%Y%m%d_%H%M%S)
TEMP="backups/.backup_${STAMP}.tar.gz"
FINAL="backups/dafeiyu_backup_${STAMP}.tar.gz"
OPTIONAL=()
for extra in .env compose.lan.yaml patches.lock.json; do
    [[ ! -f "$extra" ]] || OPTIONAL+=("$extra")
done
tar -czf "$TEMP" "${OPTIONAL[@]}" astrbot/data napcat/config napcat/qq secrets compose.yaml Dockerfile patches tools vendor/plugins fetch_plugins.py meme-resources.lock.json browser/server.py browser/Dockerfile browser/browser_allowlist.txt versions.lock.json persona-deployed.md knowledge
tar -tzf "$TEMP" >/dev/null
mv "$TEMP" "$FINAL"
restore
python3 - <<'PY'
from pathlib import Path
archives = sorted(Path('backups').glob('dafeiyu_backup_*.tar.gz'), key=lambda p: p.stat().st_mtime, reverse=True)
for archive in archives[7:]:
    archive.unlink()
PY
printf 'Backup complete: %s\n' "$FINAL"
