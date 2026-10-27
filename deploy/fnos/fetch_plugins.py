import concurrent.futures
import json
from pathlib import Path
import tarfile
import tempfile
import urllib.request

base = Path(__file__).resolve().parent
manifest = json.loads((base / 'versions.lock.json').read_text())
target = base / 'vendor' / 'plugins'
target.mkdir(parents=True, exist_ok=True)

def fetch(plugin):
    destination = target / plugin['directory']
    stamp = destination / '.deployment-commit'
    if stamp.exists() and stamp.read_text().strip() == plugin['commit']:
        return plugin['directory'] + ': already pinned'
    if destination.exists():
        raise RuntimeError('Refusing to overwrite existing plugin: ' + str(destination))
    url = 'https://codeload.github.com/' + plugin['repository'] + '/tar.gz/' + plugin['commit']
    with tempfile.TemporaryDirectory(dir=base / 'incoming') as scratch:
        archive = Path(scratch) / 'plugin.tar.gz'
        with urllib.request.urlopen(url, timeout=600) as response, archive.open('wb') as out:
            while chunk := response.read(1024 * 1024):
                out.write(chunk)
        with tarfile.open(archive) as tar:
            roots = {member.name.split('/')[0] for member in tar.getmembers()}
            if len(roots) != 1:
                raise RuntimeError('Unexpected archive roots')
            root = Path(scratch).resolve()
            for member in tar.getmembers():
                resolved = (root / member.name).resolve()
                if not resolved.is_relative_to(root) or not (member.isdir() or member.isfile()):
                    raise RuntimeError('Unsafe archive member: ' + member.name)
                if member.isdir():
                    resolved.mkdir(parents=True, exist_ok=True)
                else:
                    resolved.parent.mkdir(parents=True, exist_ok=True)
                    resolved.write_bytes(tar.extractfile(member).read())
        (Path(scratch) / roots.pop()).rename(destination)
    stamp.write_text(plugin['commit'] + '\n')
    return plugin['directory'] + ': ' + plugin['commit']

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(fetch, manifest['plugins']))
for result in results:
    print(result, flush=True)
print('PLUGINS_READY', flush=True)
