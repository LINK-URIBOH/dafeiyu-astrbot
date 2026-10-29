# SnowLuma 增量迁移

适配 AstrBot 4.29.0，SnowLuma 2.2.1 / Linux amd64。保留平台 ID、数据库、模型、插件配置及会话标识。本目录不包含或重新分发 SnowLuma 修改版。

官方 amd64 镜像摘要：`sha256:74d6874a4240636dca700734f31fbce7d0735cbce6bb43780dd8e3788eddccc9`；多架构索引摘要：`sha256:29536cd34e9c9c3f8a942be4e5cd6a17d366acd9b2096aa56b5863d024a80d23`。加速源必须返回相同摘要。

## 现有部署迁移

先取得镜像并运行兼容测试。`configure_snowluma.py prepare` 保存回退副本，已存在时拒绝覆盖。随后关闭旧自愈定时器，停止 AstrBot 和选定 NapCat，执行冷备份并验证恢复，再执行 `install`。该脚本要求 `dafeiyu-astrbot`、`dafeiyu-napcat` 和 `napcat` 均已停止，只适用于此迁移范围；它不会替代冷备份和恢复检查。

```bash
export SNOWLUMA_IMAGE=motricseven7/snowluma@sha256:74d6874a4240636dca700734f31fbce7d0735cbce6bb43780dd8e3788eddccc9
export DAFEIYU_LAN_IP=你的局域网地址
python3 tools/configure_snowluma.py prepare
# 停止服务、完成并验证冷备份后：
python3 tools/configure_snowluma.py install
docker update --restart=no dafeiyu-napcat napcat
docker compose up -d --no-deps --pull never astrbot snowluma
```

脚本设置 `.env` 的 Compose 列表，默认组合核心、费用日报及 SnowLuma 三份配置，因此要求已有费用日报适配。旧大肥鱼 NapCat 改为 `legacy-napcat` profile；普通启动不启动它。独立旧 `napcat` 另行关闭自动启动。不会删除旧容器、镜像或数据，不重跑初始化脚本。

新 QQ 使用独立 `snowluma/config` 和 `snowluma/share`，不复制 NapCat 登录态。WebUI 为 5099，扫码桌面为 6081；只发布回环和明确指定的私有地址。HTTP 健康接口只监听容器回环，反向 WS 使用已有 Token，不发布 OneBot 端口。首次协议确认、扫码与安全验证由运营者完成，不设置自动接受条款变量。遥测、状态指令、历史同步和自发消息上报关闭。密码、登录数据、gateway.json 和数据库不得提交 Git。

## 媒体与运维

`face_convert_main.py` 基于固定项目版本。优先读取 `get_record` 转码后的 base64，校验格式、大小和音频头；拒绝将 SILK/AMR 冒充 MP3。保留旧 NapCat 文件返回兼容。视频通过原消息刷新下载地址。

健康检查核对连接与 `get_status`；SnowLuma 使用自身 WS 重连和 supervisor 恢复，离线或风控不触发循环重启 QQ，也不启动旧 NapCat。`gateway.json` 选择后端，缺失时沿用 NapCat。

备份停止 AstrBot，短暂冻结当前协议容器以复制独立快照，随后恢复协议容器。快照中的明文 SQLite 用 backup API 归并 WAL 后压缩；加密数据库保留冻结时的数据库及日志文件。归档包括新旧协议数据、配置、私密环境与费用数据库，应按私密数据保护。

## 验证与回退

```bash
python3 tools/verify_patches.py
python3 -m unittest discover -s tools -p 'test_snowluma_*.py'
python3 tools/heal_ws.py
```

测试需固定 source/、aiohttp 和 ffmpeg；19 项覆盖原视频处理及新增音频 payload、视频地址刷新，不调用模型或发送 QQ。真实验收检查收件端文字、图片、语音、视频、点歌、表情、戳一戳、管理员命令，另测共享上下文、重启重连与备份恢复，不继承旧 NapCat 人工验收结论。

回退先停止 SnowLuma，保留其数据；恢复 `incoming/snowluma-before` 中的 Compose、环境、工具和版本文件，移走 gateway.json，恢复 AstrBot 原媒体挂载，再按需启动大肥鱼 NapCat。不要覆盖迁移后业务数据库。独立旧 NapCat 默认继续停用，禁止两个接入端同时登录同一 QQ。
