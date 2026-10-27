from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import time

from .domain import BOUNDARY_TOLERANCE, amount, money


class Store:
    def __init__(self, path: Path, now: int | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots(provider TEXT,planned INTEGER,observed INTEGER,body TEXT NOT NULL,PRIMARY KEY(provider,planned));
            CREATE TABLE IF NOT EXISTS states(provider TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bills(account TEXT,cycle TEXT,id TEXT,body TEXT NOT NULL,PRIMARY KEY(account,cycle,id));
            CREATE TABLE IF NOT EXISTS coverage(account TEXT,cycle TEXT,observed INTEGER,PRIMARY KEY(account,cycle));
            CREATE TABLE IF NOT EXISTS adjustments(id INTEGER PRIMARY KEY,provider TEXT,moment INTEGER,value TEXT,kind TEXT,created INTEGER,revoked INTEGER);
            CREATE TABLE IF NOT EXISTS reports(ending INTEGER PRIMARY KEY,revision INTEGER,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS corrections(id INTEGER PRIMARY KEY,ending INTEGER,provider TEXT,revision INTEGER,body TEXT,notified INTEGER DEFAULT 0,UNIQUE(ending,provider,revision));
            CREATE TABLE IF NOT EXISTS deliveries(ending INTEGER PRIMARY KEY,status TEXT,attempts INTEGER,updated INTEGER);
            ''')
            db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', ('first_seen', str(now if now is not None else int(time.time()))))
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()
        for suffix in ('-wal', '-shm'):
            path = Path(str(self.path) + suffix)
            if path.exists():
                path.chmod(0o600)

    def meta(self, key, default=None):
        with self.db() as db:
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_meta(self, key, value):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, str(value)))

    def snapshot(self, provider, planned, observed, data):
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)', (provider, planned, observed, json.dumps(data)))

    def has_snapshot(self, provider, planned):
        with self.db() as db:
            return db.execute('SELECT 1 FROM snapshots WHERE provider=? AND planned=?', (provider, planned)).fetchone() is not None

    def boundary(self, provider, ending):
        with self.db() as db:
            row = db.execute('SELECT * FROM snapshots WHERE provider=? AND ABS(observed-?)<=? ORDER BY ABS(observed-?) LIMIT 1',
                             (provider, ending, BOUNDARY_TOLERANCE, ending)).fetchone()
        return {**json.loads(row['body']), 'observed': row['observed']} if row else None

    def latest(self, provider, before=None):
        with self.db() as db:
            row = db.execute('SELECT * FROM snapshots WHERE provider=? AND observed<=? ORDER BY observed DESC LIMIT 1',
                             (provider, before or 2**62)).fetchone()
        return {**json.loads(row['body']), 'observed': row['observed']} if row else None

    def state(self, provider, data=None):
        with self.db() as db:
            if data is not None:
                db.execute('INSERT OR REPLACE INTO states VALUES(?,?)', (provider, json.dumps(data)))
                return data
            row = db.execute('SELECT body FROM states WHERE provider=?', (provider,)).fetchone()
        return json.loads(row['body']) if row else {'status': 'unconfigured', 'reason': '尚未配置或采集'}

    def replace_bills(self, account, cycle, rows, now):
        with self.db() as db:
            db.execute('DELETE FROM bills WHERE account=? AND cycle=?', (account, cycle))
            db.executemany('INSERT INTO bills VALUES(?,?,?,?)', [(account, cycle, row['id'], json.dumps(row)) for row in rows])
            db.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?)', (account, cycle, now))

    def bills(self, account, cycles):
        rows, complete = [], True
        with self.db() as db:
            for cycle in cycles:
                complete &= db.execute('SELECT 1 FROM coverage WHERE account=? AND cycle=?', (account, cycle)).fetchone() is not None
                rows.extend(json.loads(r['body']) for r in db.execute('SELECT body FROM bills WHERE account=? AND cycle=?', (account, cycle)))
        return rows, complete

    def adjustment(self, provider, moment, value, kind, now):
        value = money(value)
        if value == 0 or abs(value) > Decimal('1000000000'):
            raise ValueError('调整金额须为非零且绝对值小于十亿元')
        with self.db() as db:
            cursor = db.execute('INSERT INTO adjustments(provider,moment,value,kind,created) VALUES(?,?,?,?,?)',
                                (provider, moment, amount(value), kind, now))
            return cursor.lastrowid

    def revoke(self, adjustment_id, now):
        with self.db() as db:
            return db.execute('UPDATE adjustments SET revoked=? WHERE id=? AND revoked IS NULL', (now, adjustment_id)).rowcount == 1

    def adjustments(self, provider, start, end):
        with self.db() as db:
            rows = db.execute('SELECT value FROM adjustments WHERE provider=? AND moment>=? AND moment<? AND revoked IS NULL', (provider, start, end))
            return sum((money(r['value']) for r in rows), Decimal(0))

    def report(self, ending):
        with self.db() as db:
            row = db.execute('SELECT body FROM reports WHERE ending=?', (ending,)).fetchone()
        return json.loads(row['body']) if row else None

    def save_report(self, report):
        ending = report['ending']
        with self.db() as db:
            row = db.execute('SELECT revision,body FROM reports WHERE ending=?', (ending,)).fetchone()
            old = json.loads(row['body']) if row else None
            revision = row['revision'] + 1 if row else 1
            if old == report:
                return
            delivered = db.execute("SELECT 1 FROM deliveries WHERE ending=? AND status IN ('sent','unknown','sending')", (ending,)).fetchone()
            if old and delivered:
                for provider, current in report['providers'].items():
                    previous = old['providers'][provider]
                    if current.get('cost') != previous.get('cost'):
                        body = {'old': previous.get('cost'), 'new': current.get('cost')}
                        db.execute('INSERT OR IGNORE INTO corrections(ending,provider,revision,body) VALUES(?,?,?,?)', (ending, provider, revision, json.dumps(body)))
            db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?)', (ending, revision, json.dumps(report)))

    def pending_corrections(self):
        with self.db() as db:
            return [dict(row, body=json.loads(row['body'])) for row in db.execute('SELECT * FROM corrections WHERE notified=0 ORDER BY ending,id')]

    def claim(self, endings, now):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for ending in endings:
                row = db.execute('SELECT * FROM deliveries WHERE ending=?', (ending,)).fetchone()
                if row and (row['status'] != 'failed' or row['attempts'] >= 3 or now - row['updated'] < 600):
                    return False
            for ending in endings:
                db.execute("INSERT INTO deliveries VALUES(?,'sending',1,?) ON CONFLICT(ending) DO UPDATE SET status='sending',attempts=attempts+1,updated=excluded.updated", (ending, now))
        return True

    def finish(self, endings, status, now, correction_ids=()):
        with self.db() as db:
            db.executemany('UPDATE deliveries SET status=?,updated=? WHERE ending=?', [(status, now, e) for e in endings])
            if status == 'sent':
                db.executemany('UPDATE corrections SET notified=1 WHERE id=?', [(i,) for i in correction_ids])

    def delivery(self, ending):
        with self.db() as db:
            row = db.execute('SELECT * FROM deliveries WHERE ending=?', (ending,)).fetchone()
        return dict(row) if row else None

    def recover(self, now):
        with self.db() as db:
            db.execute("UPDATE deliveries SET status='unknown',updated=? WHERE status='sending'", (now,))

    def prune(self, now):
        cutoff = now - 365 * 86400
        with self.db() as db:
            for table, field in [('snapshots', 'observed'), ('reports', 'ending'), ('deliveries', 'ending'), ('corrections', 'ending'), ('adjustments', 'created')]:
                db.execute(f'DELETE FROM {table} WHERE {field}<?', (cutoff,))
            from .domain import local
            cycle = local(cutoff).strftime('%Y-%m')
            db.execute('DELETE FROM bills WHERE cycle<?', (cycle,))
            db.execute('DELETE FROM coverage WHERE cycle<?', (cycle,))
