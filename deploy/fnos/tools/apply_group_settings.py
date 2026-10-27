"""Merge the agreed settings only. Run with the new AstrBot stopped."""
import json
import copy
from pathlib import Path
import sqlite3

BASE = Path(__file__).resolve().parents[1]
credentials = json.loads((BASE / 'secrets/credentials.json').read_text(encoding='utf-8-sig'))
group_id = str(credentials.get('context_group_id', '')).strip()
if not group_id.isdigit():
    raise ValueError('Set context_group_id to the explicitly allowed group before applying group settings')
UMO = 'qq:GroupMessage:' + group_id
runtime_env = (BASE / 'secrets/runtime.env').read_text(encoding='utf-8-sig')
runtime_group = next((line.split('=', 1)[1].strip() for line in runtime_env.splitlines()
                      if line.startswith('DAFEIYU_GROUP_ID=')), '')
if runtime_group != group_id:
    raise RuntimeError('Set only DAFEIYU_GROUP_ID in secrets/runtime.env to match context_group_id, then recreate AstrBot; do not rerun initialization')
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def save(path, value):
    target = path.with_suffix(path.suffix + '.tmp')
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    target.chmod(0o600)
    target.replace(path)

path = BASE / 'astrbot/data/cmd_config.json'
config = load(path)
unrelated = {k:copy.deepcopy(v) for k,v in config.items() if k not in ('platform_settings','provider_ltm_settings')}
owner = str(load(BASE / 'secrets/credentials.json')['owner_qq'])
owner_umo = 'qq:FriendMessage:' + owner
platform = config['platform_settings']
platform.update({'unique_session': False, 'ignore_at_all': True, 'enable_id_white_list': True})
platform['id_whitelist'] = list(dict.fromkeys(platform['id_whitelist'] + [owner_umo, UMO]))
context = config['provider_ltm_settings']
context.update({'group_icl_enable': True, 'group_message_max_cnt': 50,
    'group_message_history_enable': True, 'group_message_history_max_cnt': 700,
    'image_caption': True, 'image_caption_provider_id': 'bailian_vision'})
context['active_reply'].update({'enable': True, 'method': 'possibility_reply', 'possibility_reply': 0.1, 'whitelist': [UMO]})
assert unrelated == {k:v for k,v in config.items() if k not in ('platform_settings','provider_ltm_settings')}
save(path, config)

path = BASE / 'astrbot/data/config/astrbot_plugin_proactive_chat_config.json'
config = load(path)
friend_before = copy.deepcopy(config['friend_settings'])
group = config['group_settings']
group.update({'enable': True, 'session_list': [UMO], 'group_idle_trigger_minutes': 120})
group['auto_trigger_settings'].update({'enable_auto_trigger': True, 'auto_trigger_after_minutes': 5})
group['schedule_settings'].update({'min_interval_minutes': 90, 'max_interval_minutes': 360,
    'max_unanswered_times': 2, 'quiet_hours': '23-8'})
group['context_settings'].update({'source_mode': 'hybrid', 'platform_history_count': 50, 'include_bot_messages': True, 'platform_context_max_chars': 12000})
group['tts_settings']['enable_tts'] = False
assert config['friend_settings'] == friend_before
save(path, config)

path = BASE / 'astrbot/data/config/astrbot_plugin_livingmemory_config.json'
config = load(path)
config['session_manager']['enable_full_group_capture'] = True
config['filtering_settings'].update({'memory_scope_mode': 'session', 'use_session_filtering': True, 'use_persona_filtering': True})
config['access_control'].update({'whitelist_enabled': True, 'allowed_ids': owner_umo + '\n' + UMO})
config['reflection_engine']['summary_trigger_rounds'] = 10
save(path, config)

with sqlite3.connect(BASE / 'astrbot/data/data_v4.db') as db:
    row = db.execute("SELECT value FROM preferences WHERE scope='umo' AND scope_id=? AND key='session_service_config'", (UMO,)).fetchone()
    value = json.loads(row[0]) if row else {'val': {}}
    value.setdefault('val', {})['tts_enabled'] = False
    if row:
        db.execute("UPDATE preferences SET value=?, updated_at=CURRENT_TIMESTAMP WHERE scope='umo' AND scope_id=? AND key='session_service_config'", (json.dumps(value), UMO))
    else:
        db.execute("INSERT INTO preferences(created_at,updated_at,scope,scope_id,key,value) VALUES(CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'umo',?,'session_service_config',?)", (UMO, json.dumps(value)))
print('Agreed group settings merged; unrelated settings preserved')
