import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client('http://browser:8010/Browser', timeout=15, sse_read_timeout=220) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            names = [tool.name for tool in (await session.list_tools()).tools]
            print('MCP tools: ' + ', '.join(names), flush=True)
            tool = 'browser_task' if '--bili' in sys.argv else 'browser_health'
            arguments = {'task': '打开 https://www.bilibili.com/v/popular/all/ ，读取公开页面，最多返回三条视频的真实标题、UP主和完整视频链接。只读已有页面，不播放、不登录，遇到验证码或访问限制立即结束。明确这些是页面信息，不是已经观看视频。', 'max_steps': 8} if tool == 'browser_task' else {}
            result = await session.call_tool(tool, arguments)
            texts = [item.text for item in result.content if hasattr(item, 'text')]
            output = {'tool': tool, 'is_error': result.isError, 'text': '\n'.join(texts)}
            Path('/AstrBot/data/browser-' + ('bili' if '--bili' in sys.argv else 'health') + '-validation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
            print(json.dumps(output, ensure_ascii=False), flush=True)

asyncio.run(main())
