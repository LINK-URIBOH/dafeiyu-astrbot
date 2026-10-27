import json
from pathlib import Path
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parents[1]

class Dashboard:
    def __init__(self):
        self.token = None
        access = json.loads((BASE / 'secrets/admin-access.json').read_text())
        result = self.request('POST', '/auth/login', {'username': access['astrbot_username'], 'password': access['astrbot_password']})
        self.token = result['token']

    def request(self, method, path, payload=None, raw=None, content_type='application/json'):
        headers = {}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if payload is not None:
            raw = json.dumps(payload, ensure_ascii=False).encode()
        if raw is not None:
            headers['Content-Type'] = content_type
        request = urllib.request.Request('http://127.0.0.1:6185/api/v1' + path, data=raw, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError('Dashboard ' + method + ' ' + path + ': HTTP ' + str(exc.code)) from None
        if result.get('status') not in ('ok', 'success', None):
            raise RuntimeError('Dashboard operation failed: ' + method + ' ' + path + ': ' + str(result.get('message', ''))[:350])
        return result.get('data', result)
