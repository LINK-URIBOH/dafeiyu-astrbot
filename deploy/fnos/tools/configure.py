import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from urllib.parse import urlsplit

base = Path(__file__).resolve().parents[1]
data = base / 'astrbot/data'
secret_dir = base / 'secrets'
if (data / 'cmd_config.json').exists():
    raise RuntimeError('Initialization refused: an existing runtime configuration was found. Use a reviewed incremental update instead.')
credentials = json.loads((secret_dir / 'credentials.json').read_text(encoding='utf-8-sig'))
owner = str(credentials['owner_qq']).strip()
robot = str(credentials['robot_qq']).strip()
if not owner.isdigit() or not robot.isdigit() or owner == robot:
    raise ValueError('Robot and owner QQ must be different numeric IDs')
old = subprocess.run(['docker', 'inspect', 'napcat'], capture_output=True, text=True)
if old.returncode == 0:
    for mount in json.loads(old.stdout)[0].get('Mounts', []):
        if mount.get('Destination') == '/app/napcat/config':
            if (Path(mount['Source']) / ('onebot11_' + robot + '.json')).exists():
                raise ValueError('New robot QQ also exists in old NapCat configuration; refusing dual login')
for field in ('deepseek_api_key', 'dashscope_api_key', 'siliconflow_api_key'):
    credentials[field] = credentials[field].strip()
    if not credentials[field] or any(c in credentials[field] for c in '\r\n'):
        raise ValueError('Missing or invalid credential field: ' + field)

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)

def schema_defaults(schema):
    return {name: schema_defaults(spec.get('items', {})) if spec.get('type') == 'object'
            else copy.deepcopy(spec.get('default'))
            for name, spec in schema.items() if spec.get('type') != 'hint'}

def plugin_config(name):
    schema = json.loads((base / 'vendor/plugins' / name / '_conf_schema.json').read_text())
    return schema_defaults(schema)

access_path = secret_dir / 'admin-access.json'
if access_path.exists():
    access = json.loads(access_path.read_text())
else:
    access = {'astrbot_username': 'dafeiyu_admin', 'astrbot_password': 'Df9' + secrets.token_urlsafe(20),
              'napcat_token': secrets.token_urlsafe(32), 'onebot_token': secrets.token_urlsafe(32)}
    write_json(access_path, access)

endpoint = credentials.get('dashscope_base_url', '').strip().rstrip('/')
if not endpoint:
    workspace = credentials.get('dashscope_workspace_id', '').strip()
    endpoint = ('https://' + workspace + '.cn-beijing.maas.aliyuncs.com/compatible-mode/v1') if workspace else 'https://dashscope.aliyuncs.com/compatible-mode/v1'
url = urlsplit(endpoint)
if url.scheme != 'https' or not (url.hostname == 'dashscope.aliyuncs.com' or url.hostname.endswith('.cn-beijing.maas.aliyuncs.com')):
    raise ValueError('Unexpected Beijing DashScope API endpoint')
origin = url.scheme + '://' + url.netloc
runtime_env = {'DAFEIYU_GROUP_ID': str(credentials.get('context_group_id', '')).strip(), 'DEEPSEEK_API_KEY': credentials['deepseek_api_key'], 'DASHSCOPE_API_KEY': credentials['dashscope_api_key'],
               'DASHSCOPE_BASE_HTTP_API_URL': origin + '/api/v1',
               'DASHSCOPE_BASE_WEBSOCKET_API_URL': 'wss://' + url.netloc + '/api-ws/v1/inference'}
for filename, fields in [('runtime.env', runtime_env), ('browser.env', {'DEEPSEEK_API_KEY': credentials['deepseek_api_key']}),
                         ('napcat.env', {'ACCOUNT': robot, 'NAPCAT_QUICK_ACCOUNT': robot})]:
    path = secret_dir / filename
    path.write_text(''.join(k + '=' + v + '\n' for k, v in fields.items()))
    path.chmod(0o600)

config_path = data / 'cmd_config.json'
config = json.loads((base / 'incoming/default-config.json').read_text())
if config_path.exists():
    config.update(json.loads(config_path.read_text(encoding='utf-8-sig')))
config.update({'admins_id': [owner], 'timezone': 'Asia/Shanghai', 'wake_prefix': ['/', '大肥鱼'],
               'disable_metrics': True})
config['platform_settings'].update({'enable_id_white_list': True, 'id_whitelist': ['qq:FriendMessage:' + owner],
                                    'wl_ignore_admin_on_group': False, 'wl_ignore_admin_on_friend': False,
                                    'friend_message_needs_wake_prefix': False})
for group in credentials.get('allowed_group_ids', []):
    if not str(group).isdigit():
        raise ValueError('Group IDs must be numeric')
    config['platform_settings']['id_whitelist'].append('qq:GroupMessage:' + str(group))
config['platform'] = [{'id': 'qq', 'type': 'aiocqhttp', 'enable': True, 'ws_reverse_host': '0.0.0.0',
                       'ws_reverse_port': 6199, 'ws_reverse_token': access['onebot_token']}]
config['provider_sources'] = [
    {'id': 'deepseek_source', 'provider': 'deepseek', 'type': 'openai_chat_completion', 'provider_type': 'chat_completion',
     'enable': True, 'key': [credentials['deepseek_api_key']], 'api_base': 'https://api.deepseek.com/v1', 'timeout': 90,
     'custom_extra_body': {'thinking': {'type': 'disabled'}, 'max_tokens': 1024}},
    {'id': 'bailian_source', 'provider': 'bailian', 'type': 'openai_chat_completion', 'provider_type': 'chat_completion',
     'enable': True, 'key': [credentials['dashscope_api_key']], 'api_base': endpoint, 'timeout': 90},
]
config['provider'] = [
    {'id': 'deepseek_flash', 'provider_source_id': 'deepseek_source', 'model': 'deepseek-flash', 'enable': True,
     'modalities': ['text', 'image', 'tool_use']},
    {'id': 'bailian_vision', 'provider_source_id': 'bailian_source', 'model': 'qwen3-vl-plus', 'enable': True,
     'modalities': ['text', 'image']},
    {'id': 'sf_bge_m3', 'type': 'openai_embedding', 'provider_type': 'embedding', 'enable': True,
     'embedding_api_key': credentials['siliconflow_api_key'], 'embedding_api_base': 'https://api.siliconflow.cn/v1',
     'embedding_model': 'BAAI/bge-m3', 'embedding_dimensions': 1024, 'embedding_dimensions_mode': 'auto', 'timeout': 60},
    {'id': 'dashscope_tts', 'type': 'dashscope_tts', 'provider': 'dashscope', 'provider_type': 'text_to_speech',
     'enable': True, 'api_key': credentials['dashscope_api_key'], 'model': 'qwen-audio-3.1-tts-flash',
     'dashscope_tts_voice': 'longanhuan_v3.1', 'dashscope_speech_rate': 1.04, 'dashscope_pitch_rate': 1.0, 'timeout': '60'},
]
config['provider_settings'].update({'default_image_caption_provider_id': 'bailian_vision', 'web_search': True,
    'websearch_provider': 'anysearch', 'websearch_anysearch_key': [], 'web_search_link': True,
    'computer_use_runtime': 'none', 'show_tool_use_status': False})
config['provider_tts_settings'].update({'enable': True, 'provider_id': 'dashscope_tts', 'dual_output': True, 'trigger_probability': 0.35})
runner = config['agent_runner']['config']
runner['model'].update({'provider_id': 'deepseek_flash', 'fallback_provider_ids': [], 'request_max_retries': 1})
runner['persona']['persona_id'] = '大肥鱼'
runner['misc'].update({'max_steps': 8, 'tool_call_timeout': 180})
runner['compression'].update({'max_turns': 30, 'provider_id': 'deepseek_flash', 'fallback_max_tokens': 32000})
salt = secrets.token_hex(16)
digest = hashlib.pbkdf2_hmac('sha256', access['astrbot_password'].encode(), bytes.fromhex(salt), 600000).hex()
config['dashboard'].update({'enable': True, 'host': '0.0.0.0', 'port': 6185, 'username': access['astrbot_username'],
    'password': hashlib.md5(access['astrbot_password'].encode()).hexdigest(),
    'pbkdf2_password': 'pbkdf2_sha256$600000$' + salt + '$' + digest,
    'password_storage_upgraded': True, 'password_change_required': False, 'jwt_secret': secrets.token_urlsafe(48)})
write_json(config_path, config)
write_json(data / 'mcp_server.json', {'mcpServers': {'browser-use': {'url': 'http://browser:8010/Browser', 'transport': 'sse', 'active': True}}})

manifest = json.loads((base / 'versions.lock.json').read_text())
for plugin in manifest['plugins']:
    name = plugin['directory']
    shutil.copytree(base / 'vendor/plugins' / name, data / 'plugins' / name, dirs_exist_ok=True)
for name in ('astrbot_plugin_face_convert', 'astrbot_plugin_schedule_awareness'):
    shutil.copytree(base / 'source/plugin' / name, data / 'plugins' / name, dirs_exist_ok=True)
for filename in ('dashscope_tts.py', 'stage.py'):
    shutil.copy2(base / 'source/deploy/patches' / filename, base / 'patches' / filename)
for relative in ('core/adapters/astrbot_provider.py', 'core/services/llm_service.py'):
    shutil.copy2(base / 'source/deploy/patches/proactive_chat' / Path(relative).name,
                 data / 'plugins/astrbot_plugin_proactive_chat' / relative)

memory = plugin_config('astrbot_plugin_livingmemory')
memory['provider_settings'].update({'embedding_provider_id': 'sf_bge_m3', 'llm_provider_id': 'deepseek_flash'})
memory['filtering_settings'].update({'memory_scope_mode': 'session', 'use_persona_filtering': True, 'use_session_filtering': True})
memory['session_manager']['enable_full_group_capture'] = False
memory['graph_memory']['enabled'] = False
memory['agent_tools'].update({'enable_recall_tool': True, 'enable_memorize_tool': True})
write_json(data / 'config/astrbot_plugin_livingmemory_config.json', memory)

proactive = plugin_config('astrbot_plugin_proactive_chat')
proactive['friend_settings'].update({'enable': True, 'session_list': ['qq:FriendMessage:' + owner]})
proactive['friend_settings']['schedule_settings'].update({'min_interval_minutes': 120, 'max_interval_minutes': 240, 'quiet_hours': '23-8', 'max_unanswered_times': 2})
proactive['friend_settings']['auto_trigger_settings'].update({'enable_auto_trigger': True, 'auto_trigger_after_minutes': 30})
proactive['friend_settings']['tts_settings']['enable_tts'] = False
proactive['friend_settings']['context_settings']['source_mode'] = 'conversation_history'
proactive['friend_settings']['proactive_prompt'] += '\n想聊新鲜话题时可以先联网搜索。没有实际检索结果时不声称已经查过。'
proactive['group_settings']['enable'] = False
proactive['web_admin']['enabled'] = False
proactive['notification_settings']['enabled'] = False
proactive['telemetry_config']['enabled'] = False
write_json(data / 'config/astrbot_plugin_proactive_chat_config.json', proactive)

poke = plugin_config('astrbot_plugin_pokepro')
poke['scheduler'].update({'enabled': False, 'target': []})
poke['ban']['weight'] = 0
poke['command']['weight'] = 0
write_json(data / 'config/astrbot_plugin_pokepro_config.json', poke)
parser = plugin_config('astrbot_plugin_parser')
parser.update({'source_max_size': 80, 'source_max_minute': 5, 'download_retry_times': 1})
write_json(data / 'config/astrbot_plugin_parser_config.json', parser)

stealer = plugin_config('astrbot_plugin_stealer')
stealer.update({'steal_meme': True, 'steal_chance': 0.25, 'audit_required': False, 'content_filtration': True,
    'vision_provider_id': 'bailian_vision', 'emotion_analysis_provider_id': 'deepseek_flash',
    'embedding_provider_id': 'sf_bge_m3', 'enable_embedding_search': True,
    'send_target_whitelist': ['user:' + owner], 'steal_target_whitelist': ['user:' + owner], 'model_request_interval': 15,
    'external_sources_enabled': False})
write_json(data / 'config/astrbot_plugin_stealer_config.json', stealer)

music = plugin_config('astrbot_plugin_music')
music_schema = json.loads((base / 'vendor/plugins/astrbot_plugin_music/_conf_schema.json').read_text())
music['players_template'] = [dict(schema_defaults(music_schema['players_template']['templates'][name]['items']), __template_key=name)
    for name in ('netease', 'kuwo', 'apple')]
music['send_config'].update({'send_modes': ['record_local(本地语音)', 'record_link(语音链接)', 'text(文本模式)'], 'enable_comments': False})
write_json(data / 'config/astrbot_plugin_music_config.json', music)

draw = plugin_config('astrbot_plugin_omnidraw')
draw['permission_config'].update({'usable_users': owner, 'allowed_users': ''})
draw['usage_config'].update({'enable_daily_limit': True, 'daily_image_limit': 3, 'enable_checkin': False})
draw['optimizer_config']['enable_optimizer'] = False
draw['video_providers'] = []
draw['router_config'].update({'chain_text2img': 'sf_draw', 'chain_selfie': 'sf_selfie', 'chain_video': ''})
draw['providers'] = [{'__template_key': 'image_provider', 'id': name, 'api_type': 'custom_endpoint',
    'base_url': 'https://api.siliconflow.cn/v1/images/generations', 'api_keys': credentials['siliconflow_api_key'],
    'model': model, 'available_models': [model], 'timeout': 180, 'default_size': '1328x1328' if name == 'sf_draw' else ''}
    for name, model in [('sf_draw', 'Qwen/Qwen-Image'), ('sf_selfie', 'Qwen/Qwen-Image-Edit-2509')]]
refdir = data / 'plugin_data/astrbot_plugin_omnidraw/files/persona_config/persona_ref_image'
refdir.mkdir(parents=True, exist_ok=True)
refs = sorted((base / 'source/assets/avatars/v3-20261025').glob('0[15]_*.png'))
for ref in refs:
    shutil.copy2(ref, refdir / ref.name)
ref_paths = ['/AstrBot/' + str((refdir / p.name).relative_to(base / 'astrbot')).replace(os.sep, '/') for p in refs]
draw['persona_config'].update({'active_persona_id': 'dafeiyu', 'profiles': [{'__template_key': 'persona', 'id': 'dafeiyu',
    'persona_name': '大肥鱼', 'persona_base_prompt': '蓝色小鲸鱼娘，二次元插画角色，保持参考立绘的脸型、发色、鲸鱼元素和人物身份。', 'persona_ref_image': ref_paths}]})
write_json(data / 'config/astrbot_plugin_omnidraw_config.json', draw)

persona = (base / 'source/persona/大肥鱼-人格.md').read_text()
persona = persona.split('\n---\n', 1)[-1].strip()
persona = re.sub(r'^用户明确要求截图/看屏幕时，.*\n?', '', persona, flags=re.M)
persona = re.sub(r'【用虚拟手机逛 App】.*?(?=【)',
    '【通过浏览器逛 B站】\n使用 browser_task 访问公开网页。收到逛 B站请求时，在同一轮实际调用工具，再根据结果回复。最多推荐三条，提供真实标题、UP主、链接和简短理由。只读到标题或简介时明确说明，不编造视频剧情。遇到验证码、登录要求或访问限制就如实说明。不能进行评论、关注、收藏、投币等操作。\n\n', persona, flags=re.S)
persona = persona.replace('没有实际调用手机或外部工具', '没有实际调用浏览器或外部工具')
persona += '\n\n当前可用能力中没有手机控制、现场系统听音、手机截图或视频生成；不要承诺执行这些操作。生图和自拍仅在用户明确提出请求时调用，不在主动消息或定时浏览中自行生成。\n'
(base / 'persona-deployed.md').write_text(persona)
write_json(base / 'napcat/config/webui.json', {'host': '0.0.0.0', 'port': 6099, 'prefix': '', 'token': access['napcat_token'], 'loginRate': 3})
write_json(base / ('napcat/config/onebot11_' + robot + '.json'), {'network': {'httpServers': [], 'httpSseServers': [], 'httpClients': [], 'websocketServers': [],
    'websocketClients': [{'name': 'dafeiyu-astrbot', 'enable': True, 'url': 'ws://astrbot:6199/ws', 'token': access['onebot_token'],
    'messagePostFormat': 'array', 'reportSelfMessage': False, 'reconnectInterval': 5000, 'heartInterval': 30000, 'debug': False}]},
    'musicSignUrl': '', 'enableLocalFile2Url': True, 'parseMultMsg': True})
for directory in (data / 'temp', data / 'plugin_data'):
    directory.mkdir(parents=True, exist_ok=True)
(base / 'browser/data').mkdir(parents=True, exist_ok=True)
os.chown(base / 'browser/data', 10001, 10001)
print('CONFIGURED: private-only; secrets not displayed')
