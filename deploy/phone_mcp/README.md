# PhoneMCP → 云端 AstrBot：本地安卓模拟器控制

让大肥鱼（云端 AstrBot）通过 **MCP** 操作本地 Windows 上的雷电模拟器：
看截图、读 UI、点击、启动应用。ADB 和 PhoneMCP **都不暴露公网端口**，
只走 SSH 反向隧道。

## 架构

```text
Windows 本地
  雷电 14 模拟器 (emulator-5554)
        ↑ adb
  PhoneMCP 127.0.0.1:8009/Phone
        │
        │ ssh -R 8009:127.0.0.1:8009
        ▼
云端主机
  sshd 127.0.0.1:8009
        ↑
  phone_mcp_proxy.py  172.18.0.1:8009 → 127.0.0.1:8009
        ↑
  AstrBot 容器（Docker 网络 dafeiyu_default，网关 172.18.0.1）
```

为什么需要代理：Docker 容器里的 `127.0.0.1` 指容器自身，到不了宿主的回环；
SSH `-R` 默认也只绑宿主回环。代理把 Docker 网关地址 `172.18.0.1:8009`
转发到宿主 `127.0.0.1:8009`，容器就能访问。

## 已验证组合（2026-10-20）

- LDPlayer 14.0.31（Android 14），实例 `720×1280 / 320 dpi / 30 fps`，默认 6 vCPU / 6 GB
- PhoneMCP **v0.5.0 源码运行**（Python 3.14 venv，fastmcp 4.1.1）
- AstrBot v4.29.0 Docker，MCP 配置走 SSE
- 实测工具：`list_devices` / `get_current_app` / `get_screenshot` /
  `get_ui_elements` / `launch_app` / `search_apps`
- 模型：DeepSeek（实测可接受图片输入，截图能进上下文）

## 1. 本地模拟器

1. 安装雷电 14，启动一个实例。
2. 设置分辨率 `720×1280`、DPI `320`、帧率 `30`（默认性能即可）。
3. 确认 ADB 能看到设备：

```bat
cd /d D:\leidian\LDPlayer14
adb devices
:: emulator-5554    device
```

## 2. 运行 PhoneMCP（源码版）

官方 Windows exe 在中文控制台会在启动横幅的 emoji 上崩溃：

```text
UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'
```

v0.5.0 和 v0.3.4 都有这个问题。因此从源码运行，并在 `main.py` 入口强制
stdout/stderr 使用 UTF-8：

```powershell
git clone https://github.com/kengerlwl/phoneMcp.git D:\AI\PhoneMCP\src
python D:\GitHub\dafeiyu-astrbot\deploy\phone_mcp\patch_phone_mcp_main.py D:\AI\PhoneMCP\src

cd D:\AI\PhoneMCP
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r src\requirements.txt
# 固定 fastmcp 4.1.1：2.x 与当前 mcp 2.3 存在导入冲突
.\venv\Scripts\python.exe -m pip install "fastmcp==4.1.1"

# 启动（复用雷电自带的 adb）
.\deploy\phone_mcp\start_phone_mcp.ps1
```

`fastmcp 4.x` 的实际 SSE 端点是 **`/Phone`**，不是 PhoneMCP 打印的
`/Phone/sse`；以 `GET /Phone` 返回的 `event: endpoint` 为准。

## 3. 云端代理

把 `phone_mcp_proxy.py` 放到云端（例如 `/opt/dafeiyu/tools/`），运行：

```bash
nohup python3 /opt/dafeiyu/tools/phone_mcp_proxy.py \
  > /opt/dafeiyu/tools/phone_mcp_proxy.log 2>&1 &
```

默认监听 `172.18.0.1:8009`，转发到 `127.0.0.1:8009`。
如果 compose 网络名不是 `dafeiyu_default`，用
`docker network inspect <网络名> | grep Gateway` 确认网关地址后改脚本顶部常量。

## 4. SSH 反向隧道（Windows 侧）

```powershell
.\deploy\phone_mcp\start_reverse_tunnel.ps1 -Server <server-ip>
```

脚本带 `ServerAliveInterval=15`、`ExitOnForwardFailure` 和断线 3 秒重试循环。
也可以手动执行：

```bash
ssh -N -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -R 8009:127.0.0.1:8009 <user>@<server-ip>
```

## 5. AstrBot MCP 配置

`astrbot/data/mcp_server.json`：

```json
{
  "mcpServers": {
    "phone-mcp": {
      "url": "http://172.18.0.1:8009/Phone",
      "transport": "sse",
      "active": true
    }
  }
}
```

改完重启 AstrBot，日志应出现：

```text
Connected to MCP server phone-mcp, Tools: ['list_devices', ...]
MCP services initialization completed: 1/1 successful, 0 failed.
```

大肥鱼人格的 `tools` 为空（null）时默认拥有全部工具，无需额外勾选；
若人格设置了工具白名单，需要把 `list_devices`、`get_ui_elements`、
`get_screenshot`、`launch_app` 等加入白名单。

## 6. 验收

从 AstrBot 容器直接验证链路：

```bash
docker exec -i astrbot python3 - <<'PY'
import asyncio
from mcp.client.sse import sse_client
from mcp import ClientSession

async def main():
    async with sse_client("http://172.18.0.1:8009/Phone") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
            print(await s.call_tool("list_devices", {}))

asyncio.run(main())
PY
```

QQ 实测话术：

> 肥鱼，看看你的虚拟手机现在是什么页面，然后打开设置，告诉我屏幕上实际显示的两个选项。

三条验收：模拟器画面真的变化、AstrBot 日志出现上述工具调用、回答与截图文字一致。

## 安全注意

- ADB 只在本机使用，不要 `adb tcpip` 或把 5555 端口映射到公网。
- PhoneMCP 只绑 `127.0.0.1`；云端只绑 Docker 网关，不绑 `0.0.0.0`。
- SSH 反向隧道只转发这一个端口；服务器安全组不要放行 8009。
- PhoneMCP 源码和雷电均由用户本机运行，不随本仓库分发。
