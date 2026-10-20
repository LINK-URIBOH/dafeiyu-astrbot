#!/usr/bin/env python3
"""在云端 AstrBot 的 mcp_server.json 里注册 browser-use（幂等）。

运行环境：云端主机（Docker 宿主机），python3 即可。
"""

import json
import shutil
from pathlib import Path

CONFIG = Path("/opt/dafeiyu/astrbot/data/mcp_server.json")
BACKUP = Path("/opt/dafeiyu/astrbot/data/mcp_server.json.bak_browser_20261020")
ENTRY = {
    "url": "http://172.18.0.1:8010/Browser",
    "transport": "sse",
    "active": True,
}

data = json.loads(CONFIG.read_text(encoding="utf-8") or "{}") if CONFIG.exists() else {}

if data.get("mcpServers", {}).get("browser-use") == ENTRY:
    print("browser-use entry already up to date")
    raise SystemExit(0)

if CONFIG.exists():
    shutil.copy2(CONFIG, BACKUP)

data.setdefault("mcpServers", {})["browser-use"] = ENTRY
CONFIG.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)

print(f"updated {CONFIG}")
print(json.dumps(data, ensure_ascii=False, indent=2))
