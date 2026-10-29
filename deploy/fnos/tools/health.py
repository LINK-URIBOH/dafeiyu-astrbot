import json
from pathlib import Path
import sqlite3
import subprocess
import urllib.request

base = Path(__file__).resolve().parents[1]
from gateway_health import backend
for name in ('dafeiyu-astrbot', 'dafeiyu-snowluma' if backend() == 'snowluma' else 'dafeiyu-napcat', 'dafeiyu-browser'):
    result = subprocess.run(['docker', 'inspect', '-f', '{{.State.Status}}', name], capture_output=True, text=True)
    print(name + ': ' + (result.stdout.strip() or 'unavailable'))
try:
    with urllib.request.urlopen('http://127.0.0.1:6185/api/v1/auth/setup-status', timeout=5) as response:
        print('AstrBot HTTP: ' + str(response.status))
except Exception as error:
    print('AstrBot HTTP: ' + type(error).__name__)
path = base / 'astrbot/data/data_v4.db'
if path.exists():
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        print('SQLite: ' + db.execute('PRAGMA quick_check').fetchone()[0])
        for name, enabled, next_run in db.execute('SELECT name,enabled,next_run_time FROM cron_jobs'):
            print('Task: ' + name + '; enabled=' + str(enabled) + '; next_run_utc=' + str(next_run))
