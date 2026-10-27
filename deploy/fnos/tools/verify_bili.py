import json
from pathlib import Path
import re
import urllib.request

base = Path(__file__).resolve().parents[1]
text = json.loads((base / 'astrbot/data/browser-bili-validation.json').read_text())['text']
ids = list(dict.fromkeys(re.findall(r'BV[0-9A-Za-z]{10}', text)))[:3]
results = []
for bvid in ids:
    request = urllib.request.Request('https://api.bilibili.com/x/web-interface/view?bvid=' + bvid,
                                    headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.bilibili.com/'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        video = data.get('data') or {}
        title = video.get('title', '')
        author = video.get('owner', {}).get('name', '')
        results.append({'bvid': bvid, 'api_ok': data.get('code') == 0,
                        'title_matches': bool(title) and title in text,
                        'author_matches': bool(author) and author in text,
                        'title': title, 'author': author})
    except Exception as error:
        results.append({'bvid': bvid, 'api_ok': False, 'error': type(error).__name__})
passed = len(results) > 0 and all(r.get('api_ok') and r.get('title_matches') and r.get('author_matches') for r in results)
record = {'verified': passed, 'videos': results}
(base / 'incoming/bili-verified.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
print(json.dumps(record, ensure_ascii=False), flush=True)
raise SystemExit(0 if passed else 1)
