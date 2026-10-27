import hashlib
from pathlib import Path
import sqlite3
import tarfile
import tempfile

base = Path(__file__).resolve().parents[1]
archive = max((base / 'backups').glob('dafeiyu_backup_*.tar.gz'), key=lambda p: p.stat().st_mtime)
databases = 0
files = 0
with tempfile.TemporaryDirectory(prefix='restore-check-', dir=base / 'incoming') as scratch:
    root = Path(scratch).resolve()
    with tarfile.open(archive) as tar:
        for member in tar:
            target = (root / member.name).resolve()
            if not target.is_relative_to(root):
                raise ValueError('Archive member escapes restore directory')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open('wb') as destination:
                    while chunk := source.read(1024 * 1024):
                        destination.write(chunk)
                files += 1
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        with path.open('rb') as handle:
            is_sqlite = handle.read(16) == b'SQLite format 3\x00'
        if is_sqlite:
            with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Restored database failed integrity check: ' + path.name)
            databases += 1
print('RESTORE_CHECK_OK files=' + str(files) + ' sqlite_databases=' + str(databases) + ' archive=' + archive.name)
