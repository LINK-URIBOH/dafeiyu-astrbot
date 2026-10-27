import asyncio
import json
from pathlib import Path
from astrbot.core.tools.web_search_tools import _anysearch_search
from data.plugins.astrbot_plugin_music.core.config import PluginConfig
from data.plugins.astrbot_plugin_music.core.platform.netease import NetEaseMusic
from data.plugins.astrbot_plugin_music.core.platform.kuwo import KuwoMusic
from data.plugins.astrbot_plugin_music.core.platform.apple import AppleMusic

async def main():
    results = {}
    try:
        found = await asyncio.wait_for(_anysearch_search({}, {'query': 'AstrBot 官方文档', 'max_results': 3, 'format': 'json'}), 45)
        results['anysearch'] = {'ok': bool(found), 'results': [{'title': r.title, 'url': r.url} for r in found]}
    except Exception as error:
        results['anysearch'] = {'ok': False, 'error': str(error)[:300]}
    raw = json.loads(Path('/AstrBot/data/config/astrbot_plugin_music_config.json').read_text(encoding='utf-8-sig'))
    config = PluginConfig(raw, None)
    for cls in (NetEaseMusic, KuwoMusic, AppleMusic):
        player = cls(config)
        try:
            songs = await asyncio.wait_for(player.fetch_songs('茉莉花', 1), 35)
            results[cls.platform.name] = {'ok': bool(songs), 'count': len(songs),
                'title': songs[0].name if songs else None, 'has_audio': bool(songs and songs[0].audio_url)}
        except Exception as error:
            results[cls.platform.name] = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)[:150]}
        finally:
            if player.session:
                await player.session.close()
    Path('/AstrBot/data/search-music-validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False))

asyncio.run(main())
