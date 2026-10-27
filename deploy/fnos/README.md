# fnOS / Debian 纯 Linux 部署适配

每日22点三平台费用日报为可选插件，安装与凭据说明见仓库 `plugin/astrbot_plugin_daily_cost_report/README.md`，使用 `compose.cost-report.yaml` 增量覆盖；SDK 在独立 Python 环境中运行，不修改核心依赖。

本分支保存实际部署中使用的业务补丁、Linux 浏览器和运维脚本。默认仅绑定本机管理端口；可选局域网配置见下文。代码中没有部署凭据、真实群号、管理员 QQ、聊天数据或 QQ 登录状态。

## 分支与运行版本

- `main` 保留上游代码，供同步 `whyever77/dafeiyu-astrbot/main`。
- `fnos-linux` 在上游主分支上增加本目录，保存本地适配。
- 本目录的**运行源码**仍固定在 `662cd5dd096ce0c0cf2f599b51e82efff80da24d`。`main` 同步成功不代表运行源码、AstrBot 或插件已经升级。
- AstrBot 4.29.0、NapCat 4.18.37、browser-use 0.13.11、MCP 2.1.1。社区插件逐个固定提交，见 `versions.lock.json`。
- `patches.lock.json` 记录补丁校验值与适用基线；`tools/verify_patches.py` 会拒绝未核对的版本或补丁变动。

## 保存的功能

独立 AstrBot、NapCat、Linux Chromium；大肥鱼人格；DeepSeek 聊天和工具；百炼图片、视频帧、语音识别及系统音色 TTS；SiliconFlow 记忆向量、知识库、生图与角色自拍；长期记忆、主动聊天和互动插件。

指定群共享对话、10% 随机插话、冷场主动发言；北京时间 23:00–08:00 禁止两类主动发言，明确 @、唤醒词和指令仍能回应。普通回复与主动发言参考最近最多 50 条群背景，保存 700 条流水；单条最多 1,000 字，总背景最多 12,000 字。图片转述持久保存并在重启后复用。`/reset` 清空当前机器人对话及即时群背景，保存重置边界；长期记忆和可查询历史继续保留。记忆按会话隔离，闲聊采集本身不触发回复；仍按机器人回复后的 10 轮阈值检查总结。

浏览器保留 `browser_task`、`browser_health`，匿名只读，最多 8 步、180 秒；遇到登录、验证码、访问限制即结束。每日 20:30 的 B站分享只发管理员私聊，最多三条，区分标题/简介和实际分析内容。没有手机控制、现场听音、手机截图或视频生成。生图、自拍只由明确请求触发，合计每日 3 张；月预算属于配置目标，不是平台硬性扣费上限。

## 新部署准备

要求 Linux、Docker Compose v2、Python 3.11+、systemd；以 root 执行初始化与运维。部署目录可使用 `/vol1/1000/project/dafeiyu`。只在空的新目录初始化；已有部署走后面的更新流程。

将本目录的文件复制到部署目录，然后执行：

```bash
umask 077
python3 tools/prepare.py
cp credentials.example.json secrets/credentials.json
chmod 600 secrets/credentials.json
# 在本机受限编辑器填写 QQ、三家 API Key、百炼北京地域接入信息。
python3 tools/check_credentials.py
```

需要开启单群背景恢复时，将 `context_group_id` 填为明确允许的群号；不填则不启用目标群补丁。`allowed_group_ids` 只是基本白名单，不能替代群上下文开关。初始化生成的 `secrets/runtime.env` 会携带 `DAFEIYU_GROUP_ID`，与 `context_group_id` 保持一致。

```bash
docker pull soulter/astrbot:v4.29.0
docker run --rm --entrypoint python soulter/astrbot:v4.29.0 -c 'import json; from astrbot.core.config.default import DEFAULT_CONFIG; print(json.dumps(DEFAULT_CONFIG))' > incoming/default-config.json
python3 tools/configure.py
docker compose build
docker compose up -d
```

`configure.py` 仅用于首次初始化，遇到已有核心配置会停止，防止更新时覆盖插件配置或生成新的认证盐。初始化的管理账号、密码和令牌保存在 `secrets/admin-access.json`，不要提交或发送到公开渠道。NapCat 首次登录需本人扫码。

首次启动后导入人格、知识库，再按需要启用群设置。`api_setup.py` 初始创建的每日 B站任务默认停用，浏览器实测通过后运行 `tools/enable_bili.py` 启用：

```bash
python3 tools/api_setup.py
python3 tools/refresh_manual.py
python3 tools/fetch_meme_resources.py
# 仅在 credentials.json 已填写 context_group_id 时执行以下三步：
docker compose stop astrbot
python3 tools/apply_group_settings.py
docker compose start astrbot
```

`apply_group_settings.py` 合并选定配置，不清空数据库或长期记忆，但会将目标群默认自动语音设为关闭。手动 `/语音开` 后不要通过重复运行该脚本更新其他项目。群聊全图识别及全消息记忆会随群活跃度增加调用量。

从原先群号写在代码中的部署迁移时，在保留原 API Key 的情况下，仅向 `secrets/runtime.env` 增加 `DAFEIYU_GROUP_ID=实际群号`，并在 `secrets/credentials.json` 增加同值的 `context_group_id`。复制经审核的代码后用 `docker compose up -d --no-deps --force-recreate astrbot` 重新创建新 AstrBot，让环境变量生效；不运行首次初始化，不改 NapCat 或旧机器人。使用局域网覆盖文件时，重新创建命令也要携带两个 `-f` 参数。

## 管理入口与局域网

默认 AstrBot 为 `127.0.0.1:6185`，NapCat 为 `127.0.0.1:6100/webui/`，通过 SSH 隧道访问。WebSocket 6199 和 MCP 8010 不发布到宿主机。

局域网直连时复制 `.env.example` 为 `.env`，填入服务器实际局域网 IP，再执行：

```bash
docker compose -f compose.yaml -f compose.lan.yaml up -d
```

入口为 `http://服务器局域网IP:6185` 和 `http://服务器局域网IP:6100/webui/`。该覆盖文件保留回环绑定，备份及自愈脚本仍可通过本机地址访问。后续 Compose 操作要使用同样的两个 `-f` 参数；这一步不配置公网端口转发。

## 后续跟随上游

在**代码克隆目录**执行以下命令；运行目录中的 `secrets/`、`astrbot/`、`napcat/`、`backups/` 不参与 Git 同步。

```bash
git remote add upstream https://github.com/whyever77/dafeiyu-astrbot.git
git fetch upstream
git switch main
git merge --ff-only upstream/main
git push origin main
git switch fnos-linux
git merge main
python3 deploy/fnos/tools/verify_patches.py
git push origin fnos-linux
```

已存在 `upstream` 时省略添加远程一行。发生冲突时查看双方改动并解决，不使用强制推送或整文件选择覆盖。保持新增适配在本目录，可减少上游其他目录更新引起的冲突。

要把**运行功能**升级到新的项目提交：建立独立 `update/...` 测试分支；记录 `versions.lock.json` 的旧值；分别比较项目、AstrBot、各插件变化；对照 `patches.lock.json` 的原始基线重新适配覆盖模块；更新版本和校验值后完成下列测试。不要仅把固定提交改为 `main`，也不要点击核心/插件一键更新后继续使用旧覆盖文件。

## 验证、上线与回滚

```bash
python3 tools/verify_patches.py
docker exec -w /AstrBot dafeiyu-astrbot python -m pip check
# 完整群测试的打包路径及运行命令见 VALIDATION.md。
```

发布前在隔离目录测试，验证文字、图片、语音、视频理解、语音回复、生图、自拍、记忆、互动、浏览器返回的真实链接；同群两名成员共享背景；重启后文字和图片可接续；reset 边界；群与私聊隔离；夜间两类主动发言被阻止、明确点名仍可回应。不要把模型口头承诺当作工具实际执行结果。

生产更新前执行 `bash tools/backup.sh` 和 `python3 tools/restore_check.py`，保留旧代码、镜像 ID 和配置副本。只复制经过审核的代码，不替换运行数据；变更源码包时在新目录准备并比较，不覆盖旧 `source/`。停止新 AstrBot 后合并需要的配置和补丁，重建新项目，检查日志和 OneBot，再执行上述验收。失败时停止新服务，恢复更新前代码及匹配数据副本，使用旧镜像重新启动；不要将旧数据库混用到未知新版。

`tools/install_timers.sh` 安装每天北京时间 03:17 备份（保留七份）和两分钟 OneBot 自愈任务。脚本只操作 `dafeiyu-*` 容器与任务，已有同名容器或 systemd 单元必须先核对。备份包含凭据及 QQ 登录数据，应按私密数据保存。`restore_check.py` 在临时目录解包和检查，不覆盖生产数据。

源码与许可证说明见 [THIRD_PARTY.md](THIRD_PARTY.md)。原部署人工验收和服务器状态属于历史验收，不表示未来上游版本已通过验证。
