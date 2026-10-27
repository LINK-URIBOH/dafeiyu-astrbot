"""Export an allowlist of non-secret deployment evidence; never export runtime configs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import pwd
import os
import sqlite3
import subprocess
from api_client import BASE

report = {'collected_at': datetime.now(timezone.utc).isoformat(),
          'versions': json.loads((BASE / 'versions.lock.json').read_text()), 'images': {}, 'patch_sha256': {}, 'validation': {}}
report['runtime_versions'] = {'AstrBot': '4.29.0', 'NapCat': '4.18.37', 'browser-use': '0.13.11', 'browser-mcp': '2.1.1'}
report['plugin_versions'] = {}
for plugin in (BASE / 'astrbot/data/plugins').iterdir():
    metadata = plugin / 'metadata.yaml'
    if metadata.is_file():
        match = re.search(r'^version:\s*(.+)', metadata.read_text(), re.M)
        report['plugin_versions'][plugin.name] = match.group(1).strip(' \"\'') if match else 'see commit lock'
for name in ('dafeiyu-astrbot', 'dafeiyu-napcat', 'dafeiyu-browser'):
    container = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', container['Image']]))[0]
    report['images'][name] = {'image_id': container['Image'], 'tag': container['Config']['Image'],
        'digests': image.get('RepoDigests', []), 'state': container['State']['Status'], 'started_at': container['State']['StartedAt'],
        'port_bindings': container['HostConfig'].get('PortBindings', {})}
for path in list((BASE / 'patches').glob('*.py')) + [BASE / 'browser/server.py',
    BASE / 'astrbot/data/plugins/astrbot_plugin_proactive_chat/core/adapters/astrbot_provider.py',
    BASE / 'astrbot/data/plugins/astrbot_plugin_proactive_chat/core/services/llm_service.py',
    BASE / 'tools/heal_ws.py', BASE / 'tools/apply_group_settings.py', BASE / 'tools/validate_group_settings.py']:
    report['patch_sha256'][str(path.relative_to(BASE))] = hashlib.sha256(path.read_bytes()).hexdigest()
for folder, names in [('astrbot/data', ['deployment-validation.json', 'image-validation.json', 'media-validation.json',
                                      'browser-health-validation.json', 'browser-bili-validation.json', 'search-music-validation.json', 'proactive-validation.json', 'group-context-live.json', 'group-memory-capture-validation.json']),
                      ('incoming', ['bili-verified.json', 'outbound-media-validation.json', 'browser-guard-validation.json', 'knowledge-validation.json', 'lan-access-validation.json', 'group-policy-validation.json'])]:
    for name in names:
        path = BASE / folder / name
        if path.exists():
            report['validation'][name] = json.loads(path.read_text())
with sqlite3.connect('file:' + str(BASE / 'astrbot/data/data_v4.db') + '?mode=ro', uri=True) as db:
    report['cron'] = [dict(zip(['name', 'enabled', 'status', 'next_run_utc', 'last_error'], row)) for row in db.execute(
        'SELECT name,enabled,status,next_run_time,last_error FROM cron_jobs')]
report['timers'] = subprocess.check_output(['systemctl', 'list-timers', '--all', 'dafeiyu-*', '--no-pager'], text=True)
report['containers'] = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}} {{.Status}}'], text=True).splitlines()
report['backups'] = [{'file': p.name, 'bytes': p.stat().st_size} for p in sorted((BASE / 'backups').glob('dafeiyu_backup_*.tar.gz'))]
report['human_checks'] = 'Not executed by the collector; record real manual acceptance separately.'
# Fail closed if any known secret accidentally appears in the selected evidence.
serialized = json.dumps(report, ensure_ascii=False, indent=2)
secrets = json.loads((BASE / 'secrets/credentials.json').read_text())
access = json.loads((BASE / 'secrets/admin-access.json').read_text())
values = [v for k, v in secrets.items() if 'key' in k] + list(access.values())
for secret in values:
    if isinstance(secret, str) and len(secret) > 10 and secret in serialized:
        raise RuntimeError('Secret detected in selected evidence; export aborted')
path = BASE / 'incoming/deployment-public-report.json'
path.write_text(serialized)
path.chmod(0o600)
print('Public evidence ready; no credential fields exported')
