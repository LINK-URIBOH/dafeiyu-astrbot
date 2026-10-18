# -*- coding: utf-8 -*-
"""face_convert 回归测试：嘴硬橡皮擦不误删 + file:// 路径解析。

跑法（纯标准库，不需要 AstrBot 环境）：
    python tests/test_face_rules.py
原理：用空壳模块把 astrbot 依赖桩掉，直接加载插件源码，测纯逻辑。
"""
import importlib.util
import logging
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "plugin", "astrbot_plugin_face_convert", "main.py")


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _Star:
    def __init__(self, *a, **k):
        pass


def _register(*a, **k):
    def deco(cls):
        return cls

    return deco


class _Filter:  # filter.xxx(...) 全都变成空装饰器
    EventMessageType = types.SimpleNamespace(ALL="ALL")

    def __getattr__(self, _):
        def deco(*a, **k):
            def wrap(fn):
                return fn

            return wrap

        return deco


logging.basicConfig(level=logging.CRITICAL)
_stub(
    "aiohttp",
    ClientSession=object,
    ClientTimeout=lambda *a, **k: None,
    ClientError=Exception,
)
_stub("astrbot", api=types.ModuleType("astrbot.api"))
_stub("astrbot.api", logger=logging.getLogger("t"))
_stub("astrbot.api.event", AstrMessageEvent=object, filter=_Filter())
_stub("astrbot.api.star", Context=object, Star=_Star, register=_register)
_stub("astrbot.core")
_stub("astrbot.core.message")
_stub(
    "astrbot.core.message.components",
    At=object,
    Face=object,
    Image=object,
    Plain=object,
    Record=object,
    Reply=object,
    Video=object,
)
_stub("astrbot.core.star")
_stub("astrbot.core.star.session_llm_manager", SessionServiceManager=object)

spec = importlib.util.spec_from_file_location("face_plugin", MAIN)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + detail) if detail and not cond else ""))
    if not cond:
        failures.append(name)


# 与插件里保持一致的请求词守卫
REQ = re.compile(r"重发|再发|再说|再听|再看|发一遍|发一张|换一张|重新发|发个")
HEDGE = mod.FaceConvertPlugin.HEDGE_RE


def scrub(text):
    """复刻插件的实际行为：含请求词整条放行，否则过 HEDGE_RE。"""
    return text if REQ.search(text) else HEDGE.sub("", text)


# 1) 真实识别失败请求：必须原样保留（审阅案例，不许再误删）
for s in (
    "我看不清，你能重发一张吗？",
    "这段录音没听清，请再说一次。",
    "没听清，能再说一遍吗？",
):
    check("keep: " + s, scrub(s) == s, repr(scrub(s)))

# 2) 回声型小尾巴：应被擦掉
for s, want in (
    ("看不太清诶", ""),
    ("模模糊糊的", ""),
    ("隐约飘进来一句：你好", "你好"),
):
    got = scrub(s)
    check("strip: " + s, got == want, repr(got))

# 3) 不跨逗号吃下一句
got = scrub("昨天的事模模糊糊的，今天想起来了")
check("cross-clause", "今天想起来了" in got and "模模糊糊" not in got, repr(got))

# 4) file:// 路径三种形态
P = mod.file_uri_to_path
check("path win", P("file:///C:/a/b.mp3") == "C:/a/b.mp3", P("file:///C:/a/b.mp3"))
check("path linux", P("file:///tmp/a.mp3") == "/tmp/a.mp3", P("file:///tmp/a.mp3"))
check("path http", P("https://x/y.mp3") == "https://x/y.mp3", P("https://x/y.mp3"))

print()
if failures:
    print("结果：%d 项失败" % len(failures))
    sys.exit(1)
print("结果：全部通过 ✓")
