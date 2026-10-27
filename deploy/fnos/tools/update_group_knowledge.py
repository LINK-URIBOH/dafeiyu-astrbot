"""Update only the owned public manual; leave schedules and persona unchanged."""
import json
import time
import uuid
from api_client import BASE, Dashboard

credentials = json.loads((BASE / 'secrets/credentials.json').read_text(encoding='utf-8-sig'))
group_id = str(credentials.get('context_group_id', '')).strip()
if not group_id.isdigit():
    raise ValueError('Set context_group_id before updating group documentation')
path = BASE / 'knowledge/commands.md'
text = path.read_text()
old = '本部署仅放行管理员私聊；尚未开放任何群聊。'
new = '本部署放行管理员私聊和群' + group_id + '；该群内共享上下文，群与私聊隔离。群内23:00至08:00只回应点名，默认文字回复。'
if old in text:
    text = text.replace(old, new)
elif new not in text:
    text += '\n\n' + new + '\n'
api = Dashboard()
state = json.loads((BASE / 'incoming/setup-state.json').read_text())
kb = state['kb_ids']['大肥鱼手册']
result = api.request('GET', '/knowledge-bases/' + kb + '/documents')
items = result.get('items', result.get('documents', [])) if isinstance(result, dict) else result
old_ids = [d.get('doc_id') or d.get('document_id') for d in items if d.get('file_name') == 'commands.md']
boundary = 'Dafeiyu' + uuid.uuid4().hex
body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="commands.md"\r\nContent-Type: text/markdown\r\n\r\n').encode() + text.encode() + ('\r\n--' + boundary + '--\r\n').encode()
uploaded = api.request('POST', '/knowledge-bases/' + kb + '/documents', raw=body, content_type='multipart/form-data; boundary=' + boundary)
if uploaded.get('task_id'):
    for _ in range(60):
        status = api.request('GET', '/knowledge-bases/tasks/' + uploaded['task_id'])
        if status.get('status') in ('success','completed'):
            break
        if status.get('status') == 'failed':
            raise RuntimeError('Updated manual ingestion failed; previous manual retained')
        time.sleep(2)
    else:
        raise RuntimeError('Updated manual ingestion timed out; previous manual retained')
for doc_id in old_ids:
    if doc_id:
        api.request('DELETE', '/knowledge-bases/' + kb + '/documents/' + doc_id)
path.write_text(text)
result = api.request('POST', '/knowledge-bases/' + kb + '/retrieve', {'kb_names':['大肥鱼手册'],'query':'群' + group_id + '的上下文和夜间回复规则','top_k':3})
hit = any(group_id in r.get('content','') for r in result.get('results',[]))
if not hit:
    raise RuntimeError('Updated group deployment note was not retrieved')
record_path=BASE/'incoming/group-policy-validation.json'
record=json.loads(record_path.read_text()) if record_path.exists() else {}
record['group_knowledge_updated']=True
record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2))
print('Public group deployment note updated and retrieved; schedules unchanged')
