#!/usr/bin/env python3
"""把 AstrBot 的嵌入 provider 从本地 Ollama 切到硅基流动 bge-m3（OpenAI 兼容）。

背景：大肥鱼的长期记忆 / 知识库都用 bge-m3（1024 维）。云端不跑 Ollama 时，
换成硅基流动托管的同款 bge-m3 —— 同模型同维度，实测余弦 0.9999+，
旧记忆与知识库**无需重新嵌入**即可直接使用。

用法：python3 apply_sf_embedding.py [data_dir]
      data_dir 默认为 /opt/dafeiyu/astrbot/data
幂等：可重复执行。

说明：
- 硅基流动 API Key 从插件配置（omnidraw 的持久化配置）中自动读取，
  请先把含 key 的数据目录准备好，再运行本脚本。
- 需要修改的文件：cmd_config.json、astrbot_plugin_livingmemory_config.json、
  astrbot_plugin_stealer_config.json（后两者把 embedding_provider_id 指到新 provider）。
"""
import glob
import json
import re
import sys

D = sys.argv[1] if len(sys.argv) > 1 else "/opt/dafeiyu/astrbot/data"

# 1. 从插件配置里捞硅基流动 key（不打印明文）
sfkey = None
for f in glob.glob(f"{D}/plugin_data/**/*.json", recursive=True) + glob.glob(f"{D}/config/*.json"):
    try:
        s = open(f, encoding="utf-8-sig", errors="ignore").read()
    except Exception:
        continue
    if "siliconflow" in s.lower():
        m = re.search(r"sk-[A-Za-z0-9]{20,}", s)
        if m:
            sfkey = m.group(0)
            break
if not sfkey:
    sys.exit("未找到硅基流动 key（检查 plugin_data 下的 omnidraw 配置）")

# 2. cmd_config：注册 openai_embedding，禁用本地 ollama 嵌入
p = f"{D}/cmd_config.json"
d = json.load(open(p, encoding="utf-8-sig"))
prov = d["provider"]
for e in prov:
    if e.get("id") == "ollama_embedding":
        e["enable"] = False
if not any(e.get("id") == "sf_bge_m3" for e in prov):
    prov.append({
        "id": "sf_bge_m3",
        "type": "openai_embedding",
        "provider": "openai",
        "provider_type": "embedding",
        "enable": True,
        "embedding_api_base": "https://api.siliconflow.cn/v1",
        "embedding_api_key": sfkey,
        "embedding_model": "BAAI/bge-m3",
        "embedding_dimensions": 1024,
        "timeout": 60,
    })
json.dump(d, open(p, "w", encoding="utf-8-sig"), ensure_ascii=False, indent=2)

# 3. 插件配置指向新 provider
def fix(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if k == "embedding_provider_id":
                o[k] = "sf_bge_m3"
            else:
                fix(v)
    elif isinstance(o, list):
        for v in o:
            fix(v)

for f in [f"{D}/config/astrbot_plugin_livingmemory_config.json",
          f"{D}/config/astrbot_plugin_stealer_config.json"]:
    c = json.load(open(f, encoding="utf-8-sig"))
    fix(c)
    json.dump(c, open(f, "w", encoding="utf-8-sig"), ensure_ascii=False, indent=2)

print("SF embedding 配置已应用 ✅")
