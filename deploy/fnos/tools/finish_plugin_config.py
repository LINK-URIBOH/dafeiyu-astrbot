"""Apply only remaining plugin settings; preserve all existing runtime data."""
import copy
import json
from pathlib import Path

base = Path(__file__).resolve().parents[1]
def defaults(schema):
    return {k: defaults(v.get('items', {})) if v.get('type') == 'object' else copy.deepcopy(v.get('default'))
            for k, v in schema.items() if v.get('type') != 'hint'}
def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    path.chmod(0o600)
schema = json.loads((base / 'vendor/plugins/astrbot_plugin_music/_conf_schema.json').read_text())
path = base / 'astrbot/data/config/astrbot_plugin_music_config.json'
music = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else defaults(schema)
music['players_template'] = [dict(defaults(schema['players_template']['templates'][name]['items']), __template_key=name)
                           for name in ('netease', 'kuwo', 'apple')]
music['send_config'].update({'send_modes': ['record_local(本地语音)', 'record_link(语音链接)', 'text(文本模式)'], 'enable_comments': False})
save(path, music)
owner = str(json.loads((base / 'secrets/credentials.json').read_text())['owner_qq'])
path = base / 'astrbot/data/config/astrbot_plugin_stealer_config.json'
config = json.loads(path.read_text(encoding='utf-8-sig'))
config.update({'send_target_whitelist': ['user:' + owner], 'steal_target_whitelist': ['user:' + owner]})
save(path, config)
print('Updated music sources and private-user meme whitelist')
