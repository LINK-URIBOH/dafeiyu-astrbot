import asyncio
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

from PIL import Image
import meme_generator
from data.plugins.astrbot_plugin_face_convert.main import FaceConvertPlugin, VideoAnalysis, DEFAULT_CONFIG

async def main():
    config = json.loads(Path('/AstrBot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
    runtime = json.loads(Path('/AstrBot/data/deployment-validation.json').read_text())
    results = {}
    face = FaceConvertPlugin.__new__(FaceConvertPlugin)
    face.cfg = DEFAULT_CONFIG.copy()
    face.dashscope_key = next(p['api_key'] for p in config['provider'] if p['id'] == 'dashscope_tts')
    with tempfile.TemporaryDirectory() as scratch:
        video = str(Path(scratch) / 'synthetic-test.mp4')
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1',
            '-i', '/AstrBot/data/temp/deployment-vision.jpg', '-i', runtime['tts']['audio_file'],
            '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', video], check=True)
        analysis = VideoAnalysis()
        await face._analyze_video(None, SimpleNamespace(file=video, path=video, url=None), scratch, analysis)
        text = analysis.render()
        results['video'] = {'ok': '6185' in text and ('部署' in text or '语音' in text), 'summary': text[:600]}
    fixture = io.BytesIO()
    Image.new('RGB', (128, 128), 'skyblue').save(fixture, format='PNG')
    for name, images, texts in [('petpet', [meme_generator.Image('test', fixture.getvalue())], []), ('luxun_say', [], ['部署测试成功'])]:
        try:
            result = meme_generator.get_meme(name).generate(images, texts, {})
            if not isinstance(result, (bytes, bytearray)):
                raise RuntimeError(type(result).__name__)
            path = Path('/AstrBot/data/temp/deployment-meme-' + name + '.png')
            path.write_bytes(result)
            with Image.open(io.BytesIO(result)) as image:
                image.verify()
            results[name] = {'ok': True, 'bytes': len(result)}
        except Exception as error:
            results[name] = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)[:250]}
    Path('/AstrBot/data/media-validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False), flush=True)

asyncio.run(main())
