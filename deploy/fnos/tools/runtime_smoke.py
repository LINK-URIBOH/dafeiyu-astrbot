"""Run inside the AstrBot container; only synthetic test content is submitted."""
import asyncio
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw
from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
from astrbot.core.provider.sources.openai_embedding_source import OpenAIEmbeddingProvider
from astrbot.core.provider.sources.dashscope_tts import ProviderDashscopeTTSAPI
from data.plugins.astrbot_plugin_face_convert.main import FaceConvertPlugin, DEFAULT_CONFIG

cfg = json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
providers = {p['id']: p for p in cfg['provider']}
sources = {p['id']: p for p in cfg['provider_sources']}
results = {}

def merged(name):
    model = providers[name]
    return {**sources.get(model.get('provider_source_id'), {}), **model}

def safe_error(error):
    text = str(error)
    for provider in list(providers.values()) + list(sources.values()):
        values = list(provider.get('key', [])) + [provider.get('api_key', ''), provider.get('embedding_api_key', '')]
        for value in values:
            if value:
                text = text.replace(value, '[REDACTED]')
    return type(error).__name__ + ': ' + text[:450]

async def main():
    chat = ProviderOpenAIOfficial(merged('deepseek_flash'), cfg['provider_settings'])
    try:
        response = await chat.text_chat(prompt='请只回复：部署连通成功', contexts=[])
        text = response.completion_text
        results['chat'] = {'ok': bool(text), 'reply': text[:80]}
    except Exception as error:
        results['chat'] = {'ok': False, 'error': safe_error(error)}
    try:
        embedding = OpenAIEmbeddingProvider(merged('sf_bge_m3'), cfg['provider_settings'])
        vector = await embedding.get_embedding('这是部署向量验证，不是用户记忆。')
        results['embedding'] = {'ok': len(vector) == 1024 and all(math.isfinite(n) for n in vector), 'dimensions': len(vector)}
    except Exception as error:
        results['embedding'] = {'ok': False, 'error': safe_error(error)}
    face = FaceConvertPlugin.__new__(FaceConvertPlugin)
    face.cfg = DEFAULT_CONFIG.copy()
    face.dashscope_key = providers['dashscope_tts']['api_key']
    try:
        path = '/AstrBot/data/temp/deployment-vision.jpg'
        image = Image.new('RGB', (640, 240), 'white')
        ImageDraw.Draw(image).text((60, 80), 'DEPLOY TEST 6185', fill='blue', font_size=45)
        image.save(path)
        text = await face._vl_describe([(0, path)])
        results['vision'] = {'ok': bool(text) and '6185' in text, 'description': (text or '')[:180]}
    except Exception as error:
        results['vision'] = {'ok': False, 'error': safe_error(error)}
    try:
        tts = ProviderDashscopeTTSAPI(merged('dashscope_tts'), cfg['provider_settings'])
        audio = await tts.get_audio('部署测试成功，语音服务已经连通。')
        size = Path(audio).stat().st_size
        results['tts'] = {'ok': size > 1000, 'audio_file': audio, 'bytes': size}
        try:
            text = await face._asr_file(audio)
            results['asr'] = {'ok': bool(text), 'transcript': (text or '')[:100]}
        except Exception as error:
            results['asr'] = {'ok': False, 'error': safe_error(error)}
    except Exception as error:
        results['tts'] = {'ok': False, 'error': safe_error(error)}
    Path('/AstrBot/data/deployment-validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)

asyncio.run(main())
