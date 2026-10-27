import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

base = Path(__file__).resolve().parents[1]
home = base / 'astrbot/data/plugin_data/meme_generator'
manifest = json.loads((base / 'meme-resources.lock.json').read_text())
home.mkdir(parents=True, exist_ok=True)

def valid(path, item):
    if not path.is_file() or path.stat().st_size != item['size']:
        return False
    data = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == item['sha']

def fetch(item):
    path = home / item['path']
    if not path.resolve().is_relative_to(home.resolve()):
        raise ValueError('Unexpected resource path')
    if valid(path, item):
        return True
    sources = [
        'https://raw.githubusercontent.com/MemeCrafters/meme-generator-rs/v0.2.3/',
        'https://fastly.jsdelivr.net/gh/MemeCrafters/meme-generator-rs@v0.2.3/',
        'https://cdn.jsdelivr.net/gh/MemeCrafters/meme-generator-rs@v0.2.3/',
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    for source in sources:
        try:
            request = urllib.request.Request(source + item['path'], headers={'User-Agent': 'dafeiyu-deployment/1.0'})
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(item['size'] + 1)
            digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if len(data) != item['size'] or digest != item['sha']:
                continue
            temporary = path.with_suffix(path.suffix + '.download')
            temporary.write_bytes(data)
            temporary.replace(path)
            return True
        except Exception:
            continue
    return False

missing = [item for item in manifest if not valid(home / item['path'], item)]
print('Missing or invalid resources before repair: ' + str(len(missing)), flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    success = list(executor.map(fetch, missing))
failed = [item['path'] for item, ok in zip(missing, success) if not ok]
result = {'version': '0.2.3', 'expected_files': len(manifest), 'repaired': sum(success), 'failed': failed}
(base / 'incoming/meme-resource-validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False), flush=True)
raise SystemExit(1 if failed else 0)
