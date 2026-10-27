"""Materialize pinned public sources. Does not initialize or change live settings."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

BASE = Path(__file__).resolve().parents[1]
lock = json.loads((BASE / 'versions.lock.json').read_text(encoding='utf-8'))
subprocess.run([sys.executable, str(BASE / 'tools/verify_patches.py')], check=True)
for folder in ('incoming', 'backups', 'secrets', 'astrbot/data/config', 'napcat/config', 'napcat/qq', 'browser/data'):
    (BASE / folder).mkdir(parents=True, exist_ok=True)
for folder in ('secrets', 'incoming', 'backups'):
    (BASE / folder).chmod(0o700)
destination = BASE / 'source'
stamp = destination / '.deployment-commit'
commit = lock['project']['commit']
if destination.exists():
    if not stamp.is_file() or stamp.read_text().strip() != commit:
        raise RuntimeError('Existing source snapshot differs from lock; preserve it and review the update explicitly')
else:
    with tempfile.TemporaryDirectory(dir=BASE / 'incoming') as scratch:
        archive = Path(scratch) / 'source.tar.gz'
        url = 'https://codeload.github.com/' + lock['project']['repository'] + '/tar.gz/' + commit
        with urllib.request.urlopen(url, timeout=300) as response, archive.open('wb') as target:
            shutil.copyfileobj(response, target)
        root = Path(scratch).resolve()
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            roots = {m.name.split('/')[0] for m in members}
            if len(roots) != 1:
                raise RuntimeError('Unexpected archive roots')
            for member in members:
                target = (root / member.name).resolve()
                if not target.is_relative_to(root) or not (member.isfile() or member.isdir()):
                    raise RuntimeError('Unsafe source archive member')
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as src, target.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
        (root / roots.pop()).rename(destination)
    stamp.write_text(commit + '\n')
subprocess.run([sys.executable, str(BASE / 'fetch_plugins.py')], check=True)
print('Pinned source and plugins ready. Runtime credentials and settings were not changed.')
