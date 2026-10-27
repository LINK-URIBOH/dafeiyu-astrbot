import json
from pathlib import Path
import re
import time
import urllib.parse
import uuid

from api_client import BASE, Dashboard

api = Dashboard()
print('Dashboard login: OK', flush=True)
persona_id = '大肥鱼'
payload = {'persona_id': persona_id, 'system_prompt': (BASE / 'persona-deployed.md').read_text(), 'tools': None, 'skills': None}
personas = api.request('GET', '/personas')
if any(p.get('persona_id') == persona_id for p in personas):
    api.request('PUT', '/personas/' + urllib.parse.quote(persona_id), payload)
else:
    api.request('POST', '/personas', payload)
print('Persona imported: OK', flush=True)

knowledge = BASE / 'knowledge'
knowledge.mkdir(exist_ok=True)
manual = (BASE / 'source/docs/指令手册.md').read_text()
manual = '\n'.join(line for line in manual.splitlines() if '/视频' not in line)
manual = manual.replace('画图／自拍／视频／副脑', '画图／自拍／副脑').replace('画图/自拍/视频', '画图/自拍')
manual = manual.replace('画图 · 自拍 · 视频', '画图 · 自拍')
manual = manual.replace('每日签到 / 清理临时缓存 / 插件完整帮助', '签到本部署未启用 / 清理临时缓存 / 插件完整帮助')
manual = manual.replace('发歌 / 卡片 / 语音条（别名：网易点歌、QQ点歌、酷狗点歌、酷我点歌、全民K歌 等）', '启用网易点歌、酷我点歌、苹果点歌；Apple 为官方试听。发送本地语音、语音链接或文本，不使用付费签名卡片')
manual = re.sub(r'- 已配示例：.*\n', '- 本部署默认每天北京时间20:30通过浏览器逛B站；其他个人提醒需要另行设置。\n', manual)
(knowledge / 'commands.md').write_text(manual)
(knowledge / 'glossary.md').write_text((BASE / 'source/docs/知识库-热梗词典示例.md').read_text())
existing = api.request('GET', '/knowledge-bases')['items']
kb_ids = {}
for name, filename in [('大肥鱼手册', 'commands.md'), ('热梗词典', 'glossary.md')]:
    kb = next((k for k in existing if k.get('kb_name') == name), None)
    if kb is None:
        kb = api.request('POST', '/knowledge-bases', {'name': name, 'embedding_provider_id': 'sf_bge_m3', 'chunk_size': 512, 'chunk_overlap': 64})
    kb_id = kb['kb_id']
    kb_ids[name] = kb_id
    documents = api.request('GET', '/knowledge-bases/' + kb_id + '/documents')
    items = documents.get('items', documents.get('documents', [])) if isinstance(documents, dict) else documents
    if not any(d.get('file_name') == filename for d in items):
        boundary = '----Dafeiyu' + uuid.uuid4().hex
        content = (knowledge / filename).read_bytes()
        body = (('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="' + filename + '"\r\nContent-Type: text/markdown\r\n\r\n').encode()
                + content + ('\r\n--' + boundary + '--\r\n').encode())
        result = api.request('POST', '/knowledge-bases/' + kb_id + '/documents', raw=body, content_type='multipart/form-data; boundary=' + boundary)
        if isinstance(result, dict) and result.get('task_id'):
            for attempt in range(75):
                status = api.request('GET', '/knowledge-bases/tasks/' + result['task_id'])
                if status.get('status') in ('completed', 'success'):
                    break
                if status.get('status') == 'failed':
                    raise RuntimeError('Knowledge ingestion failed: ' + name)
                time.sleep(2)
            else:
                raise RuntimeError('Knowledge ingestion timed out: ' + name)
    print('Knowledge base ready: ' + name, flush=True)

config_path = BASE / 'astrbot/data/cmd_config.json'
config = json.loads(config_path.read_text(encoding='utf-8-sig'))
config['kb_names'] = list(kb_ids)
config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
config_path.chmod(0o600)
owner = str(json.loads((BASE / 'secrets/credentials.json').read_text(encoding='utf-8-sig'))['owner_qq'])
name = '大肥鱼每日浏览B站'
jobs = api.request('GET', '/cron/jobs')
job = next((j for j in jobs if j.get('name') == name), None)
if not job:
    note = ('现在请通过 browser_task 打开 https://www.bilibili.com/v/popular/all/ 实际浏览 B站公开热门页，结合最近聊天选择轻松内容；最多选三条。'
            '单次浏览最多八步、三分钟，匿名只读；遇到验证码或登录要求立即结束。'
            '只根据可核对的标题、UP主、简介和链接写简短推荐，不把简介说成看完视频，不编造观看经历。'
            '不要生成图片、自拍、视频或语音，不进行评论、收藏、关注、投币。'
            '仅推荐已经核实标题、UP主及完整视频链接的条目，不能用首页链接代替视频链接；无完整链接则不推荐。'
            '最后用发消息工具向当前主人私聊发一条简短分享，附真实链接；失败就如实说明。')
    job = api.request('POST', '/cron/jobs', {'name': name, 'cron_expression': '30 20 * * *', 'timezone': 'Asia/Shanghai',
        'session': 'qq:FriendMessage:' + owner, 'persona_id': persona_id, 'provider_id': 'deepseek_flash', 'note': note, 'enabled': False})
(BASE / 'incoming/setup-state.json').write_text(json.dumps({'kb_ids': kb_ids, 'bili_job_id': job['job_id']}, ensure_ascii=False, indent=2))
print('Daily Bilibili job prepared, pending browser acceptance', flush=True)
