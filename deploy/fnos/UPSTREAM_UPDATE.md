# 跟随上游，同时保留 fnOS 运行配置

## 2026-11-22 基线

本次合并上游 main 的 `64274354c4331591620a925b3df498725df4564f`，包含 v3.1.0 及其后的聊天分段修复。AstrBot 仍为 4.29.0，社区插件、浏览器与 SnowLuma 镜像不连带升级。

运行更新包括：完整回复只合成一条语音、成对标点内不拆气泡、打断后停止剩余回复、保留识别不确定性与代码/链接、消息数组拆壳、管理员私聊身份标记、ASR 与 TTS 凭据解耦、日程标签清理，以及新版主动聊天补丁。联系协调桥在生活插件未安装/未开启时不改变发送规则。

SnowLuma 的转码 base64、SILK/AMR 拒绝、原消息视频刷新和原生 `tts_speak` 已重新适配。显式工具已发送语音时，核心管线不再二次合成。全部沿用已有模型和音色。

手机、账号互动、情感核心、记忆观测台等源码随合并保留，不由本次升级脚本自动安装、启用或开放端口。人格和知识库也不自动替换：上游人格包含当前部署没有的手机能力，不能整段覆盖。

## 更新已有服务

先在独立代码分支合并并测试，再发布到自己的 `fnos-linux` 分支。不得向上游推送。仓库默认的维护者发布流水线针对另一套服务器；此套件使用下面的增量流程，不运行初始化器或维护者的远程部署脚本。

1. 保留旧镜像、代码和配置；执行现有一致性备份并隔离恢复检查。
2. 把审核过的仓库快照放入运行目录下独立的 `incoming/update-日期`，不要覆盖旧 `source/`。
3. 运行只读预检（以 root 执行，路径替换为本次目录）：

```bash
python3 incoming/update-日期/deploy/fnos/tools/apply_source_update.py \
  --source incoming/update-日期 --base .
```

4. 停止 AstrBot；传入已验证的备份路径，加 `--apply`。工具要求 AstrBot 已停止，保存代码级回退目录，仅复制指定业务代码并增量加入挂载。不读取或重写 API Key、管理员、白名单、群配置、人格、记忆和费用数据库。
5. 执行 `docker compose config --quiet` 后，使用 `docker compose up -d --no-deps --pull never --force-recreate astrbot`。不要重启 SnowLuma、启动 legacy-napcat profile 或执行全项目初始化。
6. 检查面板、插件加载、WebSocket、群背景与定时任务，再做真人文字/图片/语音/视频及 `/费用 状态` 验收。

`versions.lock.json` 的项目提交表示当前业务源码基线，镜像名称中的旧短提交仅代表仍复用的固定依赖镜像。运行中的覆盖模块以挂载及 `patches.lock.json` 为准。

## 代码级回退

先停 AstrBot。升级工具打印的私密回退目录中，`files.json` 列出变更前存在/不存在的文件；恢复存在的文件副本、移除本次新增的对应文件，然后按上一步重建 AstrBot。不要恢复旧聊天/记忆/费用数据库来代替代码回退，避免丢失升级后的消息。QQ 接入容器保持运行。

若新版确实迁移了业务数据库，须另行审查数据回退；本次没有数据库迁移。

## 隔离验证

使用固定 AstrBot 依赖镜像、无模型凭据和独立临时数据运行：上游 `tests/test_*.py`、`tools/test_snowluma_media.py`/`test_snowluma_video.py`、`test_chat_pipeline.py`、`test_group_context.py`、`test_gateway_*.py`、`test_apply_source_update.py` 以及费用插件 tests。

上游部署包测试会主动制造缓存文件，必须在临时源码副本中运行，不能在生产源码上运行；AstrBot 测试设置 `ASTRBOT_ROOT` 指向临时数据根。真实收发结果与自动测试分别记录，不互相替代。
