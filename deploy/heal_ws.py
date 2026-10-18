# -*- coding: utf-8 -*-
"""云端 NapCat <-> AstrBot WS 自愈（Docker 容器版）。

原理同本地 heal-connection.py：通过 NapCat WebUI API 把 websocketClients
"关一下再开"，不重启 QQ、不需要重新扫码。
连接判定改用 AstrBot 容器日志里的"适配器已连接"。

用法（服务器上）：python3 /opt/dafeiyu/heal_ws.py
"""
import hashlib
import json
import subprocess
import time
import urllib.request

BASE = "http://127.0.0.1:6099"
CONFIG = "/opt/dafeiyu/napcat/config/webui.json"


def adapter_connected() -> bool:
    try:
        out = subprocess.run(
            ["docker", "logs", "--since", "3m", "astrbot"],
            capture_output=True,
        ).stdout.decode("utf-8", "ignore")
        return "适配器已连接" in out
    except Exception:
        return False


def main() -> None:
    if adapter_connected():
        print("连接正常，无需修复")
        return
    tok = json.load(open(CONFIG, encoding="utf-8")).get("token", "")
    h = hashlib.sha256((tok + ".napcat").encode()).hexdigest()
    opener = urllib.request.build_opener()
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=json.dumps({"hash": h}).encode(),
        headers={"Content-Type": "application/json"},
    )
    cred = json.load(opener.open(req, timeout=10))["data"]["Credential"]

    def call(path, body=None):
        req = urllib.request.Request(
            BASE + path,
            data=json.dumps(body or {}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + cred,
            },
        )
        return json.load(opener.open(req, timeout=15))

    cfg = call("/api/OB11Config/GetConfig")["data"]
    clients = cfg["network"]["websocketClients"]
    if not clients:
        print("配置里没有 websocket 客户端")
        return
    for c in clients:
        c["enable"] = False
    call("/api/OB11Config/SetConfig", {"config": json.dumps(cfg, ensure_ascii=False)})
    print("已断开旧连接...")
    time.sleep(2)
    for c in clients:
        c["enable"] = True
    call("/api/OB11Config/SetConfig", {"config": json.dumps(cfg, ensure_ascii=False)})
    print("已重新连线，等待重连...")
    for i in range(15):
        time.sleep(2)
        if adapter_connected():
            print(f"修复成功（{i * 2 + 2} 秒重连）")
            return
    print("30 秒内未重连成功")


if __name__ == "__main__":
    main()
