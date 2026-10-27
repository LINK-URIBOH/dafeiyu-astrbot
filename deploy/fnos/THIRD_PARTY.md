# 来源与修改说明

本目录是独立的 Linux 部署适配，新增代码按 GNU AGPL v3 提供；第三方来源文件保留各自权利及适用许可，不因本目录 LICENSE 被重新授权。上游项目根目录的 MIT 许可证及原有文件不变。

| 文件 | 来源及基线 | 本目录修改 |
|---|---|---|
| patches/group_chat_context.py | AstrBotDevs/AstrBot v4.29.0，astrbot/builtin_stars/astrbot/group_chat_context.py | 指定群的持久上下文、reset 边界、夜间随机回复限制 |
| patches/proactive_context_service.py | Pancakes-Labs/astrbot_plugin_proactive_chat，77a1d408ccd003a9d34ad4f51acfb8fc17bc35f5，core/services/context_service.py | 主动聊天复用同一份持久背景，清理重复背景 |
| patches/dafeiyu_group_context.py | 本次新增 | 单群选择、持久转述、截断预算、重启恢复与 reset 水位 |
| patches/omnidraw_custom_endpoint_impl.py | diaomin66/astrbot_plugin_omnidraw，91a3555b5103baea759b12261ced52fd18d433bd，providers/custom_endpoint_impl.py | SiliconFlow 普通生图与编辑自拍请求适配；保留文件内来源说明 |
| patches/dashscope_tts.py、stage.py | whyever77/dafeiyu-astrbot，662cd5dd096ce0c0cf2f599b51e82efff80da24d，deploy/patches | 使用上游提供的对应版本补丁 |
| patches/sitecustomize.py | 本次新增 | SDK 使用配置好的百炼地域接入地址 |
| browser/server.py | 参考上游 deploy/browser_use/browser_mcp_server.py，改为 Linux | 无 Windows 代理；独立 Chromium；只读动作和登录限制；工具名兼容 |

AstrBot 和主动聊天插件的许可证原文随目录保存在 LICENSES/。OmniDraw 固定提交未发现独立 LICENSE 文件，本目录保留其来源标注，不将该第三方文件声明为由本项目重新授权。其他下载依赖保留其自己的许可证，版本见 versions.lock.json。原始文件的校验值与下载地址见 patches.lock.json。完整依赖源码可按固定提交从对应公开仓库获取。

完整模块覆盖是为了匹配已经验证的运行版本。升级 AstrBot 或插件时，应对照原始文件逐项重新应用修改，不能将旧模块直接盖到新版上。本文及公开源码提供了这些修改的来源。
