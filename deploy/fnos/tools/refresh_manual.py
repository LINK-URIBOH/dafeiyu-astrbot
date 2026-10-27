"""Replace only the bundled public commands document with this deployment's version."""
import json
from pathlib import Path
import re
import time
import uuid
from api_client import BASE, Dashboard

api = Dashboard()
state = json.loads((BASE / 'incoming/setup-state.json').read_text())
kb_id = state['kb_ids']['大肥鱼手册']
text = (BASE / 'source/docs/指令手册.md').read_text()
text = '\n'.join(line for line in text.splitlines() if '/视频' not in line)
text = text.replace('画图 · 自拍 · 视频', '画图 · 自拍').replace('画图／自拍／视频／副脑', '画图／自拍／副脑').replace('画图/自拍/视频', '画图/自拍')
text = text.replace('每日签到 / 清理临时缓存 / 插件完整帮助', '签到本部署未启用 / 清理临时缓存 / 插件完整帮助')
text = text.replace('发歌 / 卡片 / 语音条（别名：网易点歌、QQ点歌、酷狗点歌、酷我点歌、全民K歌 等）', '启用网易点歌、酷我点歌、苹果点歌；Apple 为官方试听。发送语音或文本，不使用付费签名卡片')
text = re.sub(r'- 已配示例：.*', '- 本部署每天北京时间20:30通过浏览器逛B站；不预设催睡或起床任务。', text)
runtime = json.loads((BASE / 'astrbot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
groups = [str(x).split(':', 2)[2] for x in runtime['platform_settings']['id_whitelist'] if str(x).startswith('qq:GroupMessage:')]
group_note = ('本部署放行管理员私聊及指定群' + '、'.join(groups) + '；群内共享上下文，群与私聊隔离。') if groups else '本部署仅放行管理员私聊；尚未开放任何群聊。'
text += '\n\n' + group_note + '未启用视频生成、虚拟手机、签到奖励或付费签名卡片。生图和自拍合计每日限3张。\n'
(BASE / 'knowledge/commands.md').write_text(text)
docs = api.request('GET', '/knowledge-bases/' + kb_id + '/documents')
items = docs.get('items', docs.get('documents', [])) if isinstance(docs, dict) else docs
for doc in items:
    if doc.get('file_name') == 'commands.md':
        doc_id = doc.get('doc_id') or doc.get('document_id')
        api.request('DELETE', '/knowledge-bases/' + kb_id + '/documents/' + doc_id)
boundary = 'Dafeiyu' + uuid.uuid4().hex
body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="commands.md"\r\nContent-Type: text/markdown\r\n\r\n').encode() + text.encode() + ('\r\n--' + boundary + '--\r\n').encode()
result = api.request('POST', '/knowledge-bases/' + kb_id + '/documents', raw=body, content_type='multipart/form-data; boundary=' + boundary)
if result.get('task_id'):
    for _ in range(60):
        task = api.request('GET', '/knowledge-bases/tasks/' + result['task_id'])
        if task.get('status') in ('completed', 'success'):
            break
        if task.get('status') == 'failed':
            raise RuntimeError('Public manual ingestion failed')
        time.sleep(2)
    else:
        raise RuntimeError('Public manual ingestion timed out')
job = next(j for j in api.request('GET', '/cron/jobs') if j['job_id'] == state['bili_job_id'])
note = ('请通过 browser_task 打开 https://www.bilibili.com/v/popular/all/ 实际浏览公开热门页，最多选择三条轻松内容。'
        '匿名只读，最多八步、三分钟；遇到登录要求、验证码或页面限制立即结束，不关闭登录浮层、不重试。'
        '仅推荐已经核实标题、UP主和完整视频链接的内容，首页入口不能代替视频链接。'
        '分享标题、UP主、完整视频链接及推荐理由，明确仅参考页面标题/简介，不能声称看过视频。'
        '没有符合要求的条目就不推荐，向当前管理员私聊如实简短说明。'
        '不要生成图片、自拍、视频、语音，不评论、关注、收藏、投币。'
        '最后通过发消息工具向当前管理员私聊发送一条简短分享或失败说明。')
api.request('PATCH', '/cron/jobs/' + state['bili_job_id'], {'note': note})
print('Deployment-specific public manual and daily browser instructions updated')
