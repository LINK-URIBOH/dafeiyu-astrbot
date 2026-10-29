"""Freeze gateway writes briefly; archive an independent, coherent snapshot."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

BASE = Path(__file__).resolve().parents[1]


def snapshot(destination):
    names = ['astrbot/data', 'napcat/config', 'napcat/qq', 'secrets', 'compose.yaml',
             'Dockerfile', 'patches', 'tools', 'vendor/plugins', 'fetch_plugins.py',
             'meme-resources.lock.json', 'browser/server.py', 'browser/Dockerfile',
             'browser/browser_allowlist.txt', 'versions.lock.json', 'persona-deployed.md',
             'knowledge', '.env', 'compose.lan.yaml', 'patches.lock.json', 'compose.cost-report.yaml', 'Dockerfile.cost-report',
             'cost-report-requirements.txt', 'compose.snowluma.yaml', 'gateway.json', 'snowluma']
    paused = False
    settings = BASE/'gateway.json'
    selected = json.loads(settings.read_text()).get('backend') if settings.exists() else 'napcat'
    gateway = 'dafeiyu-snowluma' if selected == 'snowluma' else 'dafeiyu-napcat'
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=BASE/'backups') as tmp:
        root = Path(tmp)
        try:
            state = subprocess.run(['docker','inspect','-f','{{.State.Running}}',gateway],
                                   capture_output=True,text=True)
            if state.returncode == 0 and state.stdout.strip() == 'true':
                subprocess.run(['docker','pause',gateway],check=True,stdout=subprocess.DEVNULL)
                paused = True
            for name in names:
                src = BASE/name
                if not src.exists():
                    continue
                target = root/name
                target.parent.mkdir(parents=True,exist_ok=True)
                subprocess.run(['cp','-a',str(src),str(target)],check=True)
        finally:
            if paused:
                subprocess.run(['docker','unpause',gateway],check=True,stdout=subprocess.DEVNULL)
        # The copied files and WAL now belong exclusively to this snapshot.
        # Normalize plaintext SQLite through its backup API before archiving.
        count = 0
        for file in list(root.rglob('*')):
            if not file.is_file() or file.is_symlink():
                continue
            with file.open('rb') as stream:
                is_sqlite = stream.read(16) == b'SQLite format 3\0'
            if not is_sqlite:
                continue
            stat = file.stat()
            normalized = file.with_name(file.name+'.snapshot')
            with sqlite3.connect('file:'+str(file)+'?mode=ro',uri=True) as source:
                with sqlite3.connect(normalized) as target:
                    source.backup(target)
            os.chmod(normalized,stat.st_mode)
            os.chown(normalized,stat.st_uid,stat.st_gid)
            os.replace(normalized,file)
            for suffix in ['-wal','-shm']:
                file.with_name(file.name+suffix).unlink(missing_ok=True)
            count += 1
        subprocess.run(['tar','-czf',str(destination),'-C',str(root),'.'],check=True)
        print('Consistent SQLite snapshots:',count)


if __name__ == '__main__':
    import sys
    snapshot(Path(sys.argv[1]).resolve())
