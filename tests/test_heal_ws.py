# -*- coding: utf-8 -*-
"""heal_ws 回归：连接判定不看时间窗、只动 AstrBot 连接、保留 enable 状态。

跑法（纯标准库，不需要 Docker / 服务器）：
    python tests/test_heal_ws.py
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "deploy", "heal_ws.py")

failures = []


def check(label, cond, detail=None):
    if cond:
        print("OK  ", label)
    else:
        failures.append(label)
        print("FAIL", label, "" if detail is None else detail)


def load():
    spec = importlib.util.spec_from_file_location("heal_ws_under_test", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = load()


class _Out:
    def __init__(self, rc, data=b""):
        self.returncode = rc
        self.stdout = data


# ---------- 1. /proc/net/tcp 解析 ----------
EST = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 3500007F:0035 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1
   1: 0200000A:1837 0100000A:9C40 01 00000000:00000000 00:00000000 00000000     0        0 23456 1
"""
check("proc: ESTABLISHED on 6199 -> connected", mod._established_from_proc(EST))

LISTEN_ONLY = """  sl  local_address rem_address   st
   0: 0200000A:1837 00000000:0000 0A 00000000:00000000 00:00000000 00000000
"""
check("proc: LISTEN-only is not connected", not mod._established_from_proc(LISTEN_ONLY))

OTHER_PORT = """  sl  local_address rem_address   st
   1: 0200000A:0BB8 0100000A:9C40 01 00000000:00000000 00:00000000 00000000
"""
check("proc: other port ignored", not mod._established_from_proc(OTHER_PORT))

V6 = """  sl  local_address rem_address   st
   1: 0000000000000000FFFF00000200000A:1837 0100000000000000FFFF00000100000A:9C40 01 00000000:00000000
"""
check("proc: ipv6 ESTABLISHED on 6199", mod._established_from_proc(V6))

# ---------- 2. socket 探测的三种结果 ----------
real_subprocess = mod.subprocess
try:
    mod.subprocess = types.SimpleNamespace(run=lambda *a, **k: _Out(0, EST.encode()))
    check("socket: established -> True", mod.connected_from_socket() is True)

    mod.subprocess = types.SimpleNamespace(run=lambda *a, **k: _Out(1))
    check("socket: exec failed -> None", mod.connected_from_socket() is None)
finally:
    mod.subprocess = real_subprocess

# ---------- 3. 日志兜底按先后顺序判断 ----------
def logs(text):
    mod.subprocess = types.SimpleNamespace(
        run=lambda *a, **k: _Out(0, text.encode("utf-8"))
    )
    try:
        return mod.connected_from_logs()
    finally:
        mod.subprocess = real_subprocess


check(
    "logs: connect then disconnect -> False (old bug)",
    not logs("适配器已连接\n其他日志\n适配器已断开\n"),
)
check("logs: disconnect then connect -> True", logs("适配器已断开\n适配器已连接\n"))
check("logs: no marker -> False", not logs("启动完成\n"))

# ---------- 4. 目标连接选择 ----------
check("target: ws://astrbot:6199/ws", mod.is_astrbot_client({"url": "ws://astrbot:6199/ws"}))
check("target: other port ignored", not mod.is_astrbot_client({"url": "ws://example:3001"}))
check("target: missing url ignored", not mod.is_astrbot_client({}))

# ---------- 5. main：只动目标、保留 enable、成功返回 0 ----------
CFG = {
    "network": {
        "websocketClients": [
            {"name": "astrbot", "enable": True, "url": "ws://astrbot:6199/ws"},
            {"name": "other", "enable": False, "url": "ws://example:3001"},
            {"name": "astrbot-disabled", "enable": False, "url": "ws://astrbot:6199/ws"},
        ]
    }
}


def run_main(conn_sequence, cfg=None):
    calls = []

    def fake_call(opener, cred, path, body=None):
        calls.append((path, body))
        if path.endswith("GetConfig"):
            return {"data": copy.deepcopy(cfg if cfg is not None else CFG)}
        return {"data": {}}

    seq = list(conn_sequence)

    def fake_conn():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    mod.napcat_call = fake_call
    mod._login = lambda: (None, "cred")
    mod.adapter_connected = fake_conn
    real_time = mod.time
    mod.time = types.SimpleNamespace(sleep=lambda s: None)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mod.main()
    finally:
        mod.time = real_time
    return rc, calls


def enables(call):
    cfg = json.loads(call[1]["config"])
    return {c["name"]: c["enable"] for c in cfg["network"]["websocketClients"]}


rc, calls = run_main([False, True])
sets = [c for c in calls if c[0].endswith("SetConfig")]
check("main: success returns 0", rc == 0, rc)
check("main: one GetConfig first", calls[0][0].endswith("GetConfig"))
check("main: exactly two SetConfig", len(sets) == 2, len(sets))
check(
    "main: only enabled target toggled off",
    enables(sets[0])
    == {"astrbot": False, "other": False, "astrbot-disabled": False},
    enables(sets[0]),
)
check(
    "main: enables restored, others untouched",
    enables(sets[1])
    == {"astrbot": True, "other": False, "astrbot-disabled": False},
    enables(sets[1]),
)

# ---------- 6. main：30 秒没重连 -> 1，且配置已还原 ----------
rc, calls = run_main([False])
sets = [c for c in calls if c[0].endswith("SetConfig")]
check("main: unreconnected returns 1", rc == 1, rc)
check(
    "main: enables still restored on failure",
    enables(sets[-1])
    == {"astrbot": True, "other": False, "astrbot-disabled": False},
    enables(sets[-1]),
)

# ---------- 7. main：没有目标 / 目标本来就关闭 ----------
NO_TARGET = {"network": {"websocketClients": [{"name": "x", "enable": True, "url": "ws://x:3001"}]}}
rc, calls = run_main([False], NO_TARGET)
check("main: no target returns 1", rc == 1, rc)
check("main: no target writes nothing", not any(c[0].endswith("SetConfig") for c in calls))

OFF_TARGET = {
    "network": {
        "websocketClients": [{"name": "astrbot", "enable": False, "url": "ws://astrbot:6199/ws"}]
    }
}
rc, calls = run_main([False], OFF_TARGET)
check("main: disabled target returns 1", rc == 1, rc)
check("main: disabled target not enabled", not any(c[0].endswith("SetConfig") for c in calls))

print()
if failures:
    print("结果：%d 项失败" % len(failures))
    sys.exit(1)
print("结果：全部通过 OK")
