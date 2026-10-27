"""Exercise the deployed plugin's actual provider adapter using two explicit test requests."""
import asyncio
import json
from pathlib import Path

import aiohttp
from data.plugins.astrbot_plugin_omnidraw.models import ProviderConfig
from data.plugins.astrbot_plugin_omnidraw.providers.custom_endpoint_impl import CustomEndpointProvider

async def main():
    config = json.loads(Path('/AstrBot/data/config/astrbot_plugin_omnidraw_config.json').read_text(encoding='utf-8-sig'))
    refs = config['persona_config']['profiles'][0]['persona_ref_image']
    results = {}
    async with aiohttp.ClientSession(trust_env=True) as session:
        for node in config['providers']:
            selfie = node['id'] == 'sf_selfie'
            provider_config = ProviderConfig(id=node['id'], api_type='custom_endpoint', base_url=node['base_url'],
                api_keys=[node['api_keys']], model=node['model'], timeout=180)
            provider = CustomEndpointProvider(provider_config, session)
            try:
                kwargs = {'persona_refs': refs} if selfie else {'size': '1328x1328'}
                prompt = '保持参考立绘中同一个蓝色鲸鱼娘角色，站在明亮的窗边，二次元插画风，半身像。' if selfie else '一只可爱的蓝色小鲸鱼在白色背景上招手，简洁的二次元插画，无文字。'
                url = await provider.generate_image(prompt, num_inference_steps=20, **kwargs)
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    response.raise_for_status()
                    content = await response.read()
                import io
                from PIL import Image
                with Image.open(io.BytesIO(content)) as image:
                    image.verify()
                output = Path('/AstrBot/data/temp/deployment-' + node['id'] + '.png')
                output.write_bytes(content)
                results[node['id']] = {'ok': len(content) > 1000, 'bytes': len(content), 'file': str(output)}
            except Exception as error:
                message = str(error).replace(node['api_keys'], '[REDACTED]')
                results[node['id']] = {'ok': False, 'error': type(error).__name__ + ': ' + message[:500]}
            print(json.dumps({node['id']: results[node['id']]}, ensure_ascii=False), flush=True)
    Path('/AstrBot/data/image-validation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))

asyncio.run(main())
