"""Merge only the new cost plugin. Core, other plugins and model keys are untouched."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--plugin-source', required=True)
parser.add_argument('--backup', required=True)
parser.add_argument('--credentials')
parser.add_argument('--verified-state')
args = parser.parse_args()
base = Path(__file__).resolve().parents[1]
source = Path(args.plugin_source).resolve()
backup = Path(args.backup).resolve()
if not backup.is_relative_to((base / 'backups').resolve()) or not backup.is_file():
    raise SystemExit('A verified backup inside this project is required')
with tarfile.open(backup) as archive:
    if 'astrbot/data/cmd_config.json' not in archive.getnames():
        raise SystemExit('Backup does not contain the current core configuration')
if subprocess.check_output(['docker', 'inspect', '-f', '{{.State.Running}}', 'dafeiyu-astrbot'], text=True).strip() != 'false':
    raise SystemExit('Stop only dafeiyu-astrbot before installing; do not stop NapCat')
if not (source / 'metadata.yaml').is_file() or not (source / 'engine.py').is_file():
    raise SystemExit('Invalid plugin source')
credentials = json.loads((base / 'secrets/credentials.json').read_text(encoding='utf-8-sig'))
owner = str(credentials['owner_qq'])
core = json.loads((base / 'astrbot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
if not owner.isdigit() or owner not in {str(v) for v in core.get('admins_id', [])}:
    raise SystemExit('Deployment owner must still be a global AstrBot administrator')
destination = base / 'astrbot/data/plugins/astrbot_plugin_daily_cost_report'
shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.log'))
secret_path = base / 'secrets/daily-cost-report.json'
if args.credentials:
    values = json.loads(Path(args.credentials).read_text(encoding='utf-8-sig'))
    values = {key: values.get(key, {}) for key in ('bailian', 'siliconflow')}
    fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(values, handle, ensure_ascii=False, indent=2)
    secret_path.chmod(0o600)
elif not secret_path.exists():
    fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('{}\n')
config_path = base / 'astrbot/data/config/astrbot_plugin_daily_cost_report_config.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
config.update({'recipient_qq': owner, 'platform_id': 'qq', 'secrets_file': '/run/secrets/daily-cost-report.json'})
for flag in ('report_enabled', 'collection_enabled', 'deepseek_enabled', 'bailian_enabled', 'siliconflow_enabled'):
    config.setdefault(flag, True)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
config_path.chmod(0o600)
if args.verified_state:
    sys.path.insert(0, str(destination.parent))
    from astrbot_plugin_daily_cost_report.store import Store
    store = Store(base / 'astrbot/data/plugin_data/astrbot_plugin_daily_cost_report/costs.sqlite3')
    verified = json.loads(Path(args.verified_state).read_text(encoding='utf-8'))
    for provider in ('siliconflow','bailian'):
        prior = store.state(provider)
        store.state(provider, {**prior, **verified.get(provider, {})})
print('Cost plugin installed; owner-only private recipient set; existing core and model credentials unchanged')
