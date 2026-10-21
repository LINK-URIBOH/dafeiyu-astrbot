# 本次验证与部署记录

日期：2026-10-21。执行位置：Codex Linux `/workspace/dafeiyu-astrbot`。源码基线：`46638f9822ec8233090959e419176b640d658da7`。

交付新分支时已同步远程 `main` 的 `e5298bbee0a5de1da260a55a1eb8b91a1c600fc9`，保留其中新增的浏览器服务、手机音频链路、人格与标点修正；本次提交只新增本功能文件。原有源码审查记录仍以各表列出的版本为准。

**结论：新增实现已通过下述本地检查；真实部署、B 站账号联调、真实模型视觉回流和 QQ 图片验收尚未完成。** 本报告不将测试替身算作真实运行。

## 最终本地结果

| 检查 | 最终结果 | 证据与范围 |
| --- | --- | --- |
| `python -m unittest discover -s tests -p 'test_bili_*.py' -v` | 84 项通过，0 失败 | 活动、审批、去重、媒体、MCP、QQ 接口处理与部署运维；约 4.1 秒 |
| `python tests/test_phone_video.py` | 13 项通过，0 失败 | ADB 输出替身下的身份、离线与导航规则 |
| `python tests/test_face_rules.py` | 22 条断言通过 | 同步远程最新标点修正后的规则回归；最初基线为 10 条 |
| `python tests/test_video_processing.py` | 13 项通过，0 失败 | 原有真实 ffmpeg / 本地 HTTP 媒体处理回归 |
| 候选项目 `npm run build`、`npm test` | 构建成功，5 个测试文件、63 项通过 | 固定审查提交，未接入真实账号 |
| `pip check` | 无依赖冲突 | 当前开发 venv，不代表生产 AstrBot 容器依赖已核对 |
| Python `compileall` | 通过 | 新插件与部署 Python 文件 |
| `bash -n` | 通过 | `deploy.sh`、`cloud_service.sh` |
| PhoneMCP `git apply --check` | 通过 | 针对审查的 v0.5.0 提交；没有应用到用户 Windows |
| qrcode / Pillow | 本地 PNG 生成及解码通过 | 离线测试地址，未生成真实登录二维码或登录 |
| Windows PowerShell 脚本 | 未执行 | 当前环境没有 PowerShell、Windows 或 ADB 设备 |
| AstrBot 宿主加载与真实 Agent | 未执行 | 本地插件测试使用 SDK 替身；仅对照了 v4.29.0 原生源码 |

新增测试共 **97 项**。既有测试与候选项目测试分别列出，避免混算实际能力覆盖。

最终日志和当时源文件 SHA-256 清单保存在开发环境：

```text
/workspace/dafeiyu-work/validation/dafeiyu-bili-final-tests.log
/workspace/dafeiyu-work/validation/dafeiyu-phone-final-tests.log
/workspace/dafeiyu-work/validation/dafeiyu-face-final-tests.log
/workspace/dafeiyu-work/validation/dafeiyu-video-final-tests.log
/workspace/dafeiyu-work/validation/bilibili-build.log
/workspace/dafeiyu-work/validation/bilibili-test.log
/workspace/dafeiyu-work/validation/source-sha256.json
```

测试中的 MCP SSE / Streamable HTTP 初始化、列工具和调用使用真实本地服务；媒体测试使用真实 ffmpeg。QQ、B 站、模型、ADB 业务响应采用测试替身。当前 SDK 有非致命弃用/类型解析提示，不能据此省略真实宿主依赖验证。

## 本轮复核修正

- 移除自主 Agent 结束时按旧快照写回聊天历史的行为，避免覆盖活动期间的新聊天；活动通过独立账本及记忆摘要保存。
- 已分析位置需要画面、字幕或转写时间证据；仅有请求区间不能算已看过。
- 内部执行 MCP 工具不直接留给聊天模型；提议目标核对失败时不生成待批准写入。
- 补齐二维码依赖并验证离线生成链路。
- 增加部署文档、各能力的未验边界与运维命令。

期间有一次回归失败：旧测试要求聊天历史写回函数被调用。确认该断言与并发聊天保护冲突后，改为检查不得覆盖旧会话快照，并添加位置证据回归。随后最终 84 项全部通过；没有跳过失败项。

## 修改与保留

新增文件位于 `plugin/astrbot_plugin_bili_activity/`、`deploy/bili_activity/`，以及 `tests/test_bili_*.py`、`tests/test_phone_video.py`。原有受版本控制文件未改动；按用户后续要求，通过独立分支交付给接手 Agent，不修改 `main`，不进行生产部署。初始状态及差异记录位于开发环境 `/workspace/dafeiyu-backups/pre-bilibili.*`；这些开发环境日志和备份路径不随 GitHub ZIP 导出。

现场部署脚本已在临时部署树测试备份、保留已有配置与 SQLite 在线备份；**尚未对生产配置做备份或安装**。默认运行目录和一键启动、停止、日志、各功能开关见 [README.md](README.md)。

沿用 `cloud-environment-onboarding:setup`，已保存开发环境的 `install_script` 和 `start_skill` 草稿，包含新增依赖、分进程测试命令与生产联调入口说明。草稿保存不等于执行、生产部署或环境发布；需在环境设置中审阅、保存并发布后，才能声明新的环境快照可供恢复。当前实例的上述检查已经实际执行，未来新实例恢复尚未验证。

## 真实环境阻塞

复核结果：本机不存在 `/opt/dafeiyu`；没有 `/home/agent/.ssh`；`docker ps` 无运行中容器；没有可调用的 Windows 执行入口。现有 PhoneMCP 的“已接入云端 AstrBot”不等于本 Codex 会话能够访问该云端或 Windows。实际人格、免打扰、QQ 接收人和登录态仍需现场读取。

此前对 B 站导航 API 的只读 HTTPS 请求被本环境代理返回 `403 ClientHttpProxyError`。这只能说明当前开发环境的请求被阻断，不能作为用户本地网络结论。

继续部署所缺的是**可由本会话执行的现有云端/Windows 连接入口**。可恢复原远程执行环境，或提供现有 SSH 主机、端口、用户及已安全配置的密钥路径/执行工具；不要在聊天中发送密钥正文、密码或 Cookie。取得入口后按既有授权继续安装、修复与验证，只有扫码及具体写入提议需要用户参与。

## 要求的完整运行记录

以下各项目前均无真实生产证据，不能补写成成功：

| 阶段 | 状态 | 应保留的真实证据 |
| --- | --- | --- |
| 一次性触发 | 未创建 | `run_id`、Asia/Shanghai 时间、触发来源 |
| 打开并选择视频 | 未执行 | 当前手机 UI 来源、BV/aid/cid/page、身份核对结果 |
| 内容理解 | 未执行 | 画面采样时间、字幕或转写范围、弹幕时间、评论分页 |
| 自主截图分享 | 未执行 | 截图时间/指纹、同轮标识、QQ `message_id`、图片读回、主人可打开确认 |
| 主动具体提议 | 未发送 | `proposal_id`、目标、完整正文/变更内容、发送回执 |
| 主人答复 | 未收到 | 同私聊、同主人、真实 QQ 消息 ID 与时间 |
| 实际写入及核实 | 未执行 | 同操作 ID 的本地账本、B 站返回、重新读取核实 |
| 记忆保存 | 未执行 | 活动摘要、归属标记、LivingMemory 成功返回及实际检索 |
| 周期启用 | 未执行 | 一次性验收证据与开关记录；其他暂停任务状态保全 |

被动“截图看看”同样待 QQ 真实收图验收。发送接口成功或返回图片给模型都不能替代主人收到并能打开图片。
