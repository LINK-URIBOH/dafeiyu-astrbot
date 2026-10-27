"""Assert the agreed policy and emit only non-secret acceptance evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

BASE = Path(__file__).resolve().parents[1]
credentials = json.loads((BASE / 'secrets/credentials.json').read_text(encoding='utf-8-sig'))
group_id = str(credentials.get('context_group_id', '')).strip()
if not group_id.isdigit():
    raise ValueError('Set context_group_id to the explicitly allowed group before applying group settings')
UMO = 'qq:GroupMessage:' + group_id
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
c = read(BASE / 'astrbot/data/cmd_config.json')
p = read(BASE / 'astrbot/data/config/astrbot_plugin_proactive_chat_config.json')
m = read(BASE / 'astrbot/data/config/astrbot_plugin_livingmemory_config.json')
assert c['platform_settings']['unique_session'] is False
assert c['platform_settings']['ignore_at_all'] is True
assert UMO in c['platform_settings']['id_whitelist']
assert c['provider_ltm_settings']['active_reply'] == {'enable': True, 'method': 'possibility_reply', 'possibility_reply': 0.1, 'whitelist': [UMO]}
assert c['provider_ltm_settings']['group_message_max_cnt'] == 50
assert c['provider_ltm_settings']['group_message_history_max_cnt'] == 700
assert c['provider_ltm_settings']['image_caption'] is True
assert c['provider_ltm_settings']['image_caption_provider_id'] == 'bailian_vision'
g = p['group_settings']
assert g['session_list'] == [UMO] and g['enable']
assert g['schedule_settings']['quiet_hours'] == '23-8'
assert g['context_settings']['source_mode'] == 'hybrid'
assert g['context_settings']['platform_history_count'] == 50
assert g['schedule_settings']['max_unanswered_times'] == 2
assert m['session_manager']['enable_full_group_capture'] is True
assert m['filtering_settings']['memory_scope_mode'] == 'session'
assert m['access_control']['whitelist_enabled'] is True
assert UMO in m['access_control']['allowed_ids'].splitlines()
assert m['reflection_engine']['summary_trigger_rounds'] == 10
with sqlite3.connect('file:' + str(BASE / 'astrbot/data/data_v4.db') + '?mode=ro', uri=True) as db:
    row = db.execute("SELECT value FROM preferences WHERE scope='umo' AND scope_id=? AND key='session_service_config'", (UMO,)).fetchone()
    assert row and json.loads(row[0])['val']['tts_enabled'] is False
    count = db.execute('SELECT COUNT(*) FROM platform_message_history WHERE platform_id=? AND user_id=?', ('qq', UMO)).fetchone()[0]
record = {'checked_at': datetime.now(timezone.utc).isoformat(), 'group': group_id, 'configuration_checks_passed': True,
    'shared_conversation': True, 'random_reply_probability': 0.1, 'quiet_hours_shanghai': '23:00-08:00',
    'background_max_rows': 50, 'persistent_history_max_rows': 700, 'all_group_image_captioning': True,
    'full_group_memory_capture': True, 'memory_summary_trigger_rounds': 10, 'group_auto_tts': False,
    'group_idle_minutes': g['group_idle_trigger_minutes'], 'group_interval_minutes': [g['schedule_settings']['min_interval_minutes'], g['schedule_settings']['max_interval_minutes']],
    'current_group_history_rows': count, 'human_group_checks': 'not_run_by_this_script',
    'patch_sha256': {name: hashlib.sha256((BASE / 'patches' / name).read_bytes()).hexdigest()
                     for name in ['group_chat_context.py','dafeiyu_group_context.py','proactive_context_service.py']}}
path = BASE / 'incoming/group-policy-validation.json'
if path.exists():
    previous = read(path)
    record['human_group_checks'] = previous.get('human_group_checks', 'pending')
    for key in ('live_context_capture', 'live_restart_check', 'preserved_configuration', 'self_heal_serialization', 'postchange_backup', 'group_knowledge_updated'):
        if key in previous: record[key] = previous[key]
path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
path.chmod(0o600)
print(json.dumps(record, ensure_ascii=False))
