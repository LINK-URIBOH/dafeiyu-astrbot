# 复验方法与已知边界

## 2026-11-22 上游合并与运行适配

上游固定提交 `64274354c4331591620a925b3df498725df4564f`。在固定依赖镜像的无外网临时容器中执行：

- `python -m unittest discover -s tests -p 'test_*.py' -q`：905 tests，OK，2 skipped（平台专用测试）。部署包测试在临时源码副本运行，AstrBot 数据目录隔离；未挂载线上配置或密钥。
- fnOS 专项：媒体 25、真实核心回复管线 4、备份/健康 4、更新与失败回退 4、群上下文 11、费用权限/统计 50；共 98 项通过。
- 上游未适配版本先复现 SnowLuma 回归：10 项媒体测试中 4 failures、4 errors，包含缺失原生 TTS 工具、转换 base64、视频刷新及原始 SILK 处理；重新适配后通过。
- 补丁完整性校验与 `git diff --check` 通过。完整失败/通过日志保留在本次部署的私密升级目录，不上传聊天或费用数据。

生产收发、实际模型调用与备份恢复分别记录在交付验收中；离线测试不替代真人播放/收发确认。没有为测试重启 QQ、修改生产群 reset 边界或启用新可选模块。

## 群上下文回归

在有已安装依赖和 proactive_chat 插件的 AstrBot 4.29.0 测试容器运行。命令只向 `/tmp` 复制公开补丁和合成测试，不改线上配置；测试设置的 QQ 群号是虚构值，不调用模型 API、不发送 QQ 消息。

```bash
tar -czf /tmp/fnos-context-tests.tar.gz patches tools/test_group_context.py
docker exec dafeiyu-astrbot mkdir -p /tmp/fnos-context-tests
docker cp /tmp/fnos-context-tests.tar.gz dafeiyu-astrbot:/tmp/fnos-context-tests/tests.tar.gz
docker exec dafeiyu-astrbot tar -xzf /tmp/fnos-context-tests/tests.tar.gz -C /tmp/fnos-context-tests
docker exec -w /AstrBot -e PYTHONPATH=/tmp/fnos-context-tests/patches:/AstrBot dafeiyu-astrbot python /tmp/fnos-context-tests/tools/test_group_context.py
```

11 项测试覆盖：同群不同成员共享、重复识图去重、新 Python 进程重启恢复、reset 持久边界、命令/其他群/当前消息排除、重复背景清理、10% 概率及夜间判断、主动上下文适配、真实主动聊天夜间门控、非目标群保持原行为、条数和字符预算。

记忆插件还有现有的 `test_memory_scope.py` 与 `test_group_capture_filter.py` 共 27 项测试，应在固定的 livingmemory 源码与运行依赖下执行：

```bash
docker exec -w /AstrBot dafeiyu-astrbot python -m pytest data/plugins/astrbot_plugin_livingmemory/tests/test_memory_scope.py data/plugins/astrbot_plugin_livingmemory/tests/test_group_capture_filter.py -q
```

## 代码发布检查

浏览器访问守卫回归在固定 browser-use 0.13.11 的浏览器镜像中运行：

```bash
# 无网络、无凭据，HOME 指向可写临时目录；真实 Chromium 只访问容器内合成页面。
HOME=/tmp ANONYMIZED_TELEMETRY=false python -m unittest discover -s browser/tests -v
cd tools && python -m unittest test_update_bili_policy -v
```

覆盖真实 Agent 模型调用前入口、可读内容旁的普通登录推荐、阻挡遮罩（含未知类名）、登录表单/二维码、无文字验证码、隐藏节点、观察失败及异常返回。任务更新测试检查只 PATCH note、收件人不变、重复执行幂等和未知旧说明拒绝修改。合成测试不能替代匿名热门页的真实链接核验。

2026-11-22 本修复验证：浏览器 9 项测试（其中 DOM 矩阵 23 个场景）、任务更新 4 项均通过。全仓 905 项回归有 2 项失败、2 项跳过；同环境的修改前 v1.2 源码快照复现完全相同的两个失败：`test_bili_planner.PlannerIntegrationTests.test_exhausted_budget_does_not_plan_or_execute` 和 `test_bili_projects.ProjectIntegrationTests.test_dnd_pause_and_budget_still_prevent_review_round`。二者位于本部署未启用的手机自主活动模块，不作为本次浏览器修复通过证据，也未随本次修复修改。

```bash
python3 tools/verify_patches.py
python3 -m compileall -q browser patches tools
bash -n tools/backup.sh tools/install_timers.sh
git diff --check
```

`tools/validate_group_settings.py` 检查约定配置并记录当前流水条数，不执行真人验收、不宣称旧服务验证通过。若已手动开启群语音，该脚本的默认文字断言会失败，应先确认这是预期配置变化。

`tools/collect_public_report.py` 导出有限字段并检查已知密钥；人工验收项明确标记为未由采集脚本执行。报告仍可能有局域网地址、群号、任务名等部署元数据，发布前需再次检查，不应自动上传到 GitHub。

## 初始部署的验收来源

本目录所依据的固定版本适配已在 fnOS 部署中验收：QQ 文字、图片、语音、语音回复、生图、角色自拍、点歌、真实 QQ 表情、戳一戳；长期记忆重置后召回；两位群成员共享上下文；服务重启后原暗号和图片转述仍能接续。后端请求记录核对过旧消息注入，38 项相关自动测试通过。

这些是固定版本原部署的历史结果。全群闲聊采集已检查，但自然达到 10 轮阈值后的群长期总结尚未单独完成真人验收。生产群未为了测试而执行 reset；reset 使用临时 SQLite 数据库及独立进程验证。后续升级或新部署必须重新实测，不继承历史验收结论。

原部署备份曾在隔离目录解包并检查 SQLite 完整性。没有自动将备份覆盖到在线目录；更新时须保留旧镜像与完整私密备份。


## SnowLuma 2.2.1 迁移验证

官方 amd64 镜像摘要与下载镜像一致，镜像内 Node.js v24.22.1、SnowLuma 2.2.1。23 项媒体回归、2 项备份回归及 2 项重连回归通过：覆盖转码 base64 优先、嵌套返回、错误/超限/未转换输入、NapCat 文件兼容、视频原消息刷新、含 WAL 的已提交数据以及复制失败后的 unpause。测试在部署使用的 AstrBot 镜像内执行，不访问模型。

配置、端口与真实 QQ 人工验收分别记录在部署私密交付材料中；源码测试不等同于真人收发验收。历史 NapCat 验收不能替代 SnowLuma 的媒体及互动验收。原核心及插件配置保持原值。

真人测试发现明确要求语音时模型误用文件发送工具，现提供原生 tts_speak 和当前请求提示；增加合成/投递、重复调用、请求限制、失败返回及提示隔离测试。运行配置不变。
