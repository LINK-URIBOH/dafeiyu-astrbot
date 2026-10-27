"""Fail closed when pinned versions or full-file override snapshots drift."""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
lock = json.loads((BASE / 'versions.lock.json').read_text(encoding='utf-8'))
patches = json.loads((BASE / 'patches.lock.json').read_text(encoding='utf-8'))
assert lock['project']['commit'] == patches['tested_project_commit'], 'Project changed: rebase overrides and re-test before updating patch lock'
assert lock['runtime'] == patches['tested_runtime'], 'Runtime changed: rebase overrides and re-test before updating patch lock'
assert {p['directory']: p['commit'] for p in lock['plugins']} == patches['tested_plugins'], 'Plugin versions changed: review and re-test overrides'
for name, expected in patches['files'].items():
    actual = hashlib.sha256((BASE / name).read_bytes()).hexdigest()
    assert actual == expected, 'Patch changed: review and re-test before updating patch lock: ' + name
print('PATCH_LOCK_OK: pinned project, runtimes, plugins and override hashes match')
