# 核心补丁（随仓库提供）

这两个文件是 **AstrBot v4.29.0** 核心源码的修改版（对应 `docs/踩坑合集.md` #15 的两个 TTS 补丁），
以修改版文件的形式在 compose 里 bind-mount 进容器，升级镜像不丢补丁。

- `dashscope_tts.py`：补丁 1（qwen-audio → WebSocket 通道）+ 补丁 2（instruction / speech_rate / pitch_rate 接线）
- `stage.py`：补丁 3（TTS 朗读前过滤 `[表情名]` 标记与纯标点）

⚠️ **升级 AstrBot 版本时**，请在新版对应文件上**重新打补丁**，不要直接沿用本目录文件
（版本不匹配可能引入行为差异）。仓库钉的已验证组合见 `../Dockerfile` 与 `../compose.yaml`。

## proactive_chat 插件补丁

`proactive_chat/` 是社区插件 `astrbot_plugin_proactive_chat` v1.2.6 的两个修改版文件，
补上“主动消息也能联网搜索”的工具挂载与工具循环。安装/升级注意事项见
[`proactive_chat/README.md`](proactive_chat/README.md)。

来源：AstrBot（AGPL-3.0）https://github.com/AstrBotDevs/AstrBot
本目录仅包含修改后的文件，按 AGPL-3.0 随本项目一同分发。
