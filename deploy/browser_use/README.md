# 🌐 Browser Use → 云端 AstrBot：只读网页任务

让大肥鱼在 Windows 本机的独立 Chrome 里浏览、搜索、提取网页信息，再通过 MCP 接进云端 AstrBot。
**只读**：不登录、不发帖、不购买；独立 Chrome profile；域名白名单；任务串行。

## 架构

```text
Windows 本机
  BrowserMCP 127.0.0.1:8010/Browser
        │
        │ ssh -R 8010:127.0.0.1:8010
        ▼
云端主机
  sshd 127.0.0.1:8010
        ▲
  browser_mcp_proxy.py  172.18.0.1:8010 → 127.0.0.1:8010
        ▲
  AstrBot 容器（mcp_server.json: browser-use）
```

和 PhoneMCP 同一套隧道模式；8009（手机）与 8010（浏览器）可以同时存在。

## 前提

- conda 环境 `browser-use`（Python 3.12）+ `browser-use==0.13.11`
- 本机 Chrome（`C:\Program Files\Google\Chrome\Application\chrome.exe`）
- DeepSeek key：启动脚本从 `~/.claude/settings.json` 的 `env.ANTHROPIC_AUTH_TOKEN` 读取，
  设为子进程的 `DEEPSEEK_API_KEY`
- 云端 `/opt/dafeiyu/tools/` 可写

## 用法

1. 编辑 `browser_allowlist.txt`：`*.example.com` 同时匹配主域和子域；
   删除文件或清空 = 不限制。
2. 启动（服务 + 隧道 + 云端代理 + AstrBot MCP 注册，幂等）：

   ```powershell
   .\start_browser_service.ps1 -Server <server-ip>
   # 首次安装或重启 AstrBot 后加 -RestartBot 刷新 SSE 会话
   .\start_browser_service.ps1 -Server <server-ip> -RestartBot
   ```

3. 状态 / 停止：

   ```powershell
   .\browser_service_status.ps1
   .\stop_browser_service.ps1
   ```

4. 开机自启（可选）：

   ```powershell
   .\install_browser_autostart.ps1 -Server <server-ip>
   ```

`enable_astrbot_mcp.py` 会幂等写入 AstrBot 的 `mcp_server.json`：

```json
{
  "mcpServers": {
    "browser-use": {
      "url": "http://172.18.0.1:8010/Browser",
      "transport": "sse",
      "active": true
    }
  }
}
```

## 工具

- `browser_task(task, max_steps=15)`：高层只读任务，返回中文结果；内部串行执行。
- `browser_health()`：只检查配置，不消耗模型 token。

## 已踩的坑

- `ChatDeepSeek` 默认模型是 `deepseek-v4-flash`，用户 key 可能没有权限；必须显式传
  `model="deepseek-flash"`。
- `deepseek-flash` 默认开思考，会拒绝 browser-use 的 `tool_choice`（400
  "Thinking mode does not support this tool_choice"）。`ChatDeepSeekNoThinking`
  强制发送 `thinking=disabled`。
- 默认要下载 uBlock 等三个扩展，本机网络连不上时会白等并拖垮 30 秒启动超时；
  `Browser(..., enable_default_extensions=False)`。
- `BrowserProfile` 会把 `user_data_dir` 复制到临时目录（设计如此），不会碰主 Chrome 登录态。
- `conda run` 在这台 Windows 上遇到带引号/换行的内联代码会崩；直接调环境里的 `python.exe`。
- Windows 控制台默认 GBK，跑服务前设 `PYTHONUTF8=1`，脚本里重配 stdout 为 UTF-8。
- 域名白名单是精确匹配：`bilibili.com` 不匹配 `search.bilibili.com`，要写 `*.bilibili.com`。

## 验证

在 AstrBot 容器内：

```python
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://172.18.0.1:8010/Browser") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
            print(await s.call_tool("browser_health", {}))

asyncio.run(main())
```

预期工具：`['browser_task', 'browser_health']`。

## 安全边界

- 只读提示词 + 独立无登录 Chrome + 域名白名单 + 任务串行。
- 不把主 Chrome 的 profile 给自动化；不要放开购物/支付/银行类域名。
- 电脑关机/睡眠或隧道断开时，工具不可用；与 PhoneMCP 一样依赖 Windows 在线。
