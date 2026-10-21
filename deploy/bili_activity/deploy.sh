#!/usr/bin/env bash
# Run on the actual cloud server after confirming its deployment root.
set -euo pipefail
deploy_root="${1:-/opt/dafeiyu}"
install_deps="${2:-}"
[[ -z "$install_deps" || "$install_deps" == "--install-deps" ]] || { echo "Usage: deploy.sh [deploy-root] [--install-deps]" >&2; exit 2; }
script_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_root/../.." && pwd)"
source_plugin="$repo_root/plugin/astrbot_plugin_bili_activity"
target_plugin="$deploy_root/astrbot/data/plugins/astrbot_plugin_bili_activity"
target_tools="$deploy_root/tools/bili_activity"
data_dir="$deploy_root/astrbot/data/plugin_data/astrbot_plugin_bili_activity"
[[ -f "$source_plugin/main.py" ]] || { echo "Plugin source incomplete: $source_plugin" >&2; exit 1; }
[[ -d "$deploy_root/astrbot/data" ]] || { echo "AstrBot deployment not found: $deploy_root/astrbot/data" >&2; exit 1; }
python3 - "$source_plugin" "$script_root" "$target_plugin" "$target_tools" "$data_dir" "$deploy_root" <<'PY'
import datetime
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

source, scripts, target, tools, data, root = map(Path, sys.argv[1:])
root = root.resolve()
for location in (target, tools, data):
    if location.is_symlink() or not location.resolve().is_relative_to(root):
        raise SystemExit(f"Unsafe deployment path: {location}")
    if location.exists() and any(path.is_symlink() for path in location.rglob("*")):
        raise SystemExit(f"Existing destination contains a symlink; inspect before deployment: {location}")
source, scripts, target, tools, data = (p.resolve() for p in (source, scripts, target, tools, data))
for src in (source, scripts):
    if any(path.is_symlink() for path in src.rglob("*")):
        raise SystemExit(f"Source contains a symlink: {src}")
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
backup = root / "backups" / f"bili-activity-{stamp}.tar.gz"
backup.parent.mkdir(parents=True, exist_ok=True)
paths = [target, tools, data,
         root / "astrbot/data/config/astrbot_plugin_bili_activity_config.json",
         root / "astrbot/data/mcp_server.json",
         root / "astrbot/data/cmd_config.json"]
db_path = data / "activity.sqlite3"
with tempfile.TemporaryDirectory(prefix="bili-backup-") as temp:
    db_copy = Path(temp) / "activity.sqlite3"
    if db_path.exists():
        with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as origin:
            with sqlite3.connect(db_copy) as destination:
                origin.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SystemExit("Activity database backup failed integrity_check")
    def skip_database(member):
        relative_db = str(db_path.relative_to(root))
        if member.name in {relative_db, relative_db + "-wal", relative_db + "-shm"}:
            return None
        return member
    with tarfile.open(backup, "x:gz") as archive:
        for path in paths:
            if path.exists():
                archive.add(path, arcname=str(path.relative_to(root)), recursive=True, filter=skip_database)
        if db_copy.exists():
            archive.add(db_copy, arcname=str(db_path.relative_to(root)))
backup.chmod(0o600)
with tarfile.open(backup, "r:gz") as archive:
    # Verify readability before installing. The original files remain in place.
    for member in archive.getmembers():
        if member.isfile():
            with archive.extractfile(member) as stream:
                while stream.read(1024 * 1024):
                    pass
for src, dst in ((source, target), (scripts, tools)):
    dst.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if any(part in {".venv", "__pycache__", "state", "logs"} for part in path.relative_to(src).parts):
            continue
        if path.is_symlink():
            raise SystemExit(f"Refusing source symlink: {path}")
        if path.is_file() and path.suffix not in {".pyc", ".log"}:
            output = dst / path.relative_to(src)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, output)
print(f"Backup verified: {backup}")
print(f"Plugin staged: {target}")
print(f"Operations staged: {tools}")
print("Existing configuration, persona and cron jobs were not changed.")
PY
python3 "$target_tools/ops.py" --data-dir "$data_dir" init
if [[ "$install_deps" == "--install-deps" ]]; then
  container="${ASTRBOT_CONTAINER:-astrbot}"
  docker inspect "$container" >/dev/null
  docker exec "$container" python3 -m pip install --no-cache-dir -r /AstrBot/data/plugins/astrbot_plugin_bili_activity/requirements.txt
  docker exec "$container" python3 -m pip check
  docker exec "$container" python3 -c 'from mcp.client.streamable_http import streamablehttp_client; from PIL import Image; print("Plugin dependencies import successfully")'
fi
echo "Staged only. Reload the plugin in AstrBot after checking dependencies and actual configuration."
echo "Control: python3 $target_tools/ops.py --data-dir $data_dir status"
