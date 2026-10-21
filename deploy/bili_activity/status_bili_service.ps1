param([string]$RuntimeDir = "D:\AI\BiliActivity", [switch]$Logs)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$python = Join-Path $RuntimeDir ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Runtime not installed: $python" }
if ($Logs) {
    Get-Content -LiteralPath (Join-Path $RuntimeDir "logs\service.stderr.log") -Tail 60 -Wait
    exit
}
$probe = @'
import asyncio
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with asyncio.timeout(20):
        async with streamablehttp_client('http://127.0.0.1:8010/mcp') as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                required = {'bili_read','bili_preview','bili_execute','bili_phone','bili_prepare_video'}
                if not required <= names:
                    raise RuntimeError('MCP tool list incomplete')
                result = await session.call_tool('bili_phone', {'operation':'status','args':{}})
                if result.isError:
                    raise RuntimeError('Device readiness call failed')
                data = result.structuredContent
                if data is None:
                    data = json.loads(next(item.text for item in result.content if item.type == 'text'))
                if not data.get('online'):
                    raise RuntimeError('emulator-5554 is not online')
                print('MCP handshake, required tools and emulator-5554: OK')

asyncio.run(main())
'@
$probe | & $python -
if ($LASTEXITCODE -ne 0) { throw "Bilibili MCP is not ready" }
Write-Output "This verifies the local companion only; cloud proxy, AstrBot and QQ receipt still need end-to-end checks."
