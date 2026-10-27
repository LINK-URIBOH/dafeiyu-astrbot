import json
from pathlib import Path
import re
import sys

base = Path(__file__).resolve().parents[1]
values = []
for name in ('credentials.json', 'admin-access.json'):
    path = base / 'secrets' / name
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    values.extend(str(v) for k, v in data.items() if any(x in k for x in ('key', 'password', 'token')) and v)
for line in sys.stdin:
    for value in values:
        line = line.replace(value, '[REDACTED]')
    line = re.sub(r'(https?://txz\.qq\.com/p\?k=)\S+', r'\1[REDACTED]', line)
    line = re.sub(r'(?i)(token[=:]\s*)[^\s&,"\x27]+', r'\1[REDACTED]', line)
    sys.stdout.write(line)
