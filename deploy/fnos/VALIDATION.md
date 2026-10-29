# 复验方法与已知边界

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

官方 amd64 镜像摘要与下载镜像一致，镜像内 Node.js v24.22.1、SnowLuma 2.2.1。19 项媒体回归及 2 项备份回归通过：覆盖转码 base64 优先、嵌套返回、错误/超限/未转换输入、NapCat 文件兼容、视频原消息刷新、含 WAL 的已提交数据以及复制失败后的 unpause。测试在部署使用的 AstrBot 镜像内执行，不访问模型。

配置、端口与真实 QQ 人工验收分别记录在部署私密交付材料中；源码测试不等同于真人收发验收。历史 NapCat 验收不能替代 SnowLuma 的媒体及互动验收。原核心及插件配置保持原值。
