# -*- coding: utf-8 -*-
"""云端 NapCat <-> AstrBot WS 自愈（Docker 容器版）。

原理同本地 heal-connection.py：通过 NapCat WebUI API 把指向 AstrBot 的
websocket 客户端"关一下再开"，不重启 QQ、不需要重新扫码。

连接判定优先看 astrbot 容器内 6199 端口有没有 ESTABLISHED 连接；拿不到
（容器没起、没有 cat）时退回日志里最后一条连接/断开记录。不再用"最近 3
分钟日志里出现过已连接"这种时间窗判断——那样连上又断开会被当成正常，
连了 3 分钟没新日志又会被当成异常。

修复只动指向 AstrBot(6199) 的客户端，其余连接和各自的 enable 状态原样保留。
退出码：连接正常或修复成功 = 0；没修好、配置里没有目标 = 1。

用法（服务器上）：python3 /opt/dafeiyu/heal_ws.py
"""
import hashlib
from pathlib import Path
import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:6100"
PROJECT_BASE = Path(__file__).resolve().parents[1]
CONFIG = str(PROJECT_BASE / 'napcat/config/webui.json')
CONTAINER = "dafeiyu-astrbot"
WS_PORT = 6199
LOG_LINES = 500


def _established_from_proc(text, port=WS_PORT):
    """在 /proc/net/tcp{,6} 的输出里找 local port 为 port 的 ESTABLISHED 连接。

    每行格式：sl local_address rem_address st ...
    st = 01 是 ESTABLISHED，0A 是 LISTEN。
    """
    hex_port = "%04X" % port
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[0] == "sl":
            continue
        if fields[3] == "01" and fields[1].rsplit(":", 1)[-1] == hex_port:
            return True
    return False


def connected_from_socket():
    """True/False = 容器内连接状态；None = 探测不可用（容器没起、没有 cat 等）。"""
    try:
        out = subprocess.run(
            ["docker", "exec", CONTAINER, "cat", "/proc/net/tcp", "/proc/net/tcp6"],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return _established_from_proc(out.stdout.decode("utf-8", "ignore"))


def connected_from_logs():
    """兜底：按日志里最后一条连接/断开记录判断，不看时间窗。"""
    try:
        out = subprocess.run(
            ["docker", "logs", "--tail", str(LOG_LINES), CONTAINER],
            capture_output=True,
            timeout=15,
        ).stdout.decode("utf-8", "ignore")
    except Exception:
        return False
    last_connected = -1
    last_broken = -1
    for i, line in enumerate(out.splitlines()):
        if "适配器已连接" in line:
            last_connected = i
        if any(m in line for m in ("适配器已断开", "适配器断开", "连接已断开")):
            last_broken = i
    return last_connected > last_broken


def adapter_connected():
    state = connected_from_socket()
    if state is not None:
        return state
    return connected_from_logs()


def is_astrbot_client(client):
    """配置里的客户端是不是指向 AstrBot 的 WS 端口。"""
    from urllib.parse import urlsplit
    try:
        target = urlsplit(str(client.get("url", "")))
        return target.hostname in {"astrbot", "dafeiyu-astrbot"} and target.port == WS_PORT and target.path == "/ws"
    except ValueError:
        return False


def _login():
    tok = json.load(open(CONFIG, encoding="utf-8")).get("token", "")
    h = hashlib.sha256((tok + ".napcat").encode()).hexdigest()
    opener = urllib.request.build_opener()
    req = urllib.request.Request(
        BASE + "/api/auth/login",
        data=json.dumps({"hash": h}).encode(),
        headers={"Content-Type": "application/json"},
    )
    cred = json.load(opener.open(req, timeout=10))["data"]["Credential"]
    return opener, cred


def napcat_call(opener, cred, path, body=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body or {}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + cred,
        },
    )
    return json.load(opener.open(req, timeout=15))


def _set_config(opener, cred, cfg):
    napcat_call(
        opener,
        cred,
        "/api/OB11Config/SetConfig",
        {"config": json.dumps(cfg, ensure_ascii=False)},
    )


def main():
    from gateway_health import backend, snowluma_health
    if backend() == 'snowluma':
        healthy = adapter_connected() and snowluma_health()
        # AstrBot may expose its dashboard before SnowLuma's next retry.
        # Wait for the existing connection loop; never restart or reconfigure QQ.
        deadline = time.monotonic() + 30
        while not healthy and time.monotonic() < deadline:
            time.sleep(2)
            healthy = adapter_connected() and snowluma_health()
        print('SnowLuma: ' + ('connected and online' if healthy else 'offline or awaiting login; no QQ restart attempted'))
        return 0 if healthy else 1
    if adapter_connected():
        print("连接正常，无需修复")
        return 0

    opener, cred = _login()
    cfg = napcat_call(opener, cred, "/api/OB11Config/GetConfig")["data"]
    clients = cfg.get("network", {}).get("websocketClients") or []
    targets = [c for c in clients if is_astrbot_client(c)]
    if not targets:
        print("配置里没有指向 AstrBot(:%d) 的 websocket 客户端" % WS_PORT)
        return 1
    active = [c for c in targets if c.get("enable", True)]
    if not active:
        print("指向 AstrBot 的连接在配置里是关闭的（%d 条），未做修改" % len(targets))
        return 1

    saved = [c.get("enable", True) for c in active]
    for c in active:
        c["enable"] = False
    _set_config(opener, cred, cfg)
    print("已断开旧连接（%d 条，其他 %d 条不动）..." % (len(active), len(clients) - len(active)))
    time.sleep(2)
    for c, was in zip(active, saved):
        c["enable"] = was
    _set_config(opener, cred, cfg)
    print("已重新连线，等待重连...")
    for i in range(15):
        time.sleep(2)
        if adapter_connected():
            print("修复成功（%d 秒重连）" % (i * 2 + 2))
            return 0
    print("30 秒内未重连成功")
    return 1


if __name__ == "__main__":
    # The timer and post-restart check may overlap. Serialize config toggles so
    # another check cannot mistake the temporary disabled state for user intent.
    import fcntl
    with open(PROJECT_BASE / 'backups/heal.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('已有连接检查正在运行，本次跳过')
            sys.exit(0)
        sys.exit(main())
