# proactive_chat 主动消息联网补丁

对应插件：`astrbot_plugin_proactive_chat` **v1.2.6**（AGPL-3.0）。
目标：让**主动消息**也能调用 AstrBot 内置网页搜索（本机配置为 AnySearch 匿名额度），
而不是只会接着旧话题开口。

## 为什么需要补丁

插件原本直接构造 `ProviderRequest` 调 `provider.text_chat()`：

- 没有把 `func_tool` 放进请求，模型手里根本没有搜索工具；
- 即使挂上工具，也没有“执行工具 → 带结果重问”的循环，模型返回 tool_call 后拿不到正文。

## 补丁内容

- `astrbot_provider.py`
  - `build_provider_request()` 新增可选 `func_tool` 参数；
  - `invoke_provider()` 透传 `tool_calls_result`（兼容旧 Provider 的签名裁剪逻辑保持不变）。
- `llm_service.py`
  - `attach_web_search_tools()`：复用 AstrBot 的 `_apply_web_search_tools()`，
    按当前 QQ 会话的 `provider_settings` 挂载搜索工具；
  - `run_tool_loop()`：执行模型请求的工具调用，把结果作为 `contexts` 重问，
    最多 3 轮；最终仍只把正文交给主动消息发送流程。

搜索是否真的调用由模型决定。生产提示词末尾已加一句“想聊新鲜话题时可先联网搜索”，
不强制每条主动消息都搜。

## 安装 / 升级后重打

```bash
PLUGIN=/opt/dafeiyu/astrbot/data/plugins/astrbot_plugin_proactive_chat
cp "$PLUGIN/core/adapters/astrbot_provider.py" "$PLUGIN/core/adapters/astrbot_provider.py.bak"
cp "$PLUGIN/core/services/llm_service.py" "$PLUGIN/core/services/llm_service.py.bak"
cp astrbot_provider.py "$PLUGIN/core/adapters/astrbot_provider.py"
cp llm_service.py "$PLUGIN/core/services/llm_service.py"
docker restart astrbot
```

⚠️ 插件升级会覆盖这两个文件。升级后请先对比新版源码，再按本目录版本重打补丁，
不要直接覆盖不同版本的 `llm_service.py`。

来源：https://github.com/Pancakes-Labs/astrbot_plugin_proactive_chat
本目录仅包含修改后的两个文件，按 AGPL-3.0 随本项目一同分发。
