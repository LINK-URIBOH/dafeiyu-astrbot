import json
from pathlib import Path
import urllib.error
import urllib.request

base = Path(__file__).resolve().parents[1]
credentials = json.loads((base / 'secrets/credentials.json').read_text(encoding='utf-8-sig'))
results = []

def check(name, url, key):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            data = json.load(response)
        models = [entry['id'] for entry in data.get('data', []) if isinstance(entry, dict) and 'id' in entry]
        desired = {'deepseek-flash', 'qwen3-vl-plus', 'qwen3-asr-flash',
                   'qwen-audio-3.1-tts-flash', 'BAAI/bge-m3', 'Qwen/Qwen-Image',
                   'Qwen/Qwen-Image-Edit-2509'}
        results.append({'service': name, 'ok': True, 'target_models_listed': sorted(set(models) & desired)})
    except urllib.error.HTTPError as error:
        results.append({'service': name, 'ok': False, 'http_status': error.code})
    except Exception as error:
        results.append({'service': name, 'ok': False, 'error_type': type(error).__name__})

check('deepseek', 'https://api.deepseek.com/v1/models', credentials['deepseek_api_key'].strip())
check('siliconflow', 'https://api.siliconflow.cn/v1/models', credentials['siliconflow_api_key'].strip())
endpoint = credentials.get('dashscope_base_url', '').strip().rstrip('/')
if not endpoint:
    workspace = credentials.get('dashscope_workspace_id', '').strip()
    endpoint = ('https://' + workspace + '.cn-beijing.maas.aliyuncs.com/compatible-mode/v1') if workspace else 'https://dashscope.aliyuncs.com/compatible-mode/v1'
if not endpoint.startswith('https://') or not ('.aliyuncs.com/' in endpoint or '.aliyun.com/' in endpoint):
    raise ValueError('Unexpected DashScope endpoint; refusing to transmit API key')
check('dashscope', endpoint + '/models', credentials['dashscope_api_key'].strip())
(base / 'incoming/credential-check.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print(json.dumps(results, ensure_ascii=False), flush=True)
