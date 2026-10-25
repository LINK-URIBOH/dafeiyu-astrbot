# 自主生活 v0.3：学习笔记与文字创作

这一版让大肥鱼把真实读取过的视频、字幕、弹幕或评论整理成有来源的文字作品，并在后续活动中继续修改。已有目标、人格、会话隔离、免打扰、模型预算、QQ 发送和 LivingMemory 接口继续使用。文字创作默认关闭。

这是文字作品功能：不执行作品中的代码，不安装游戏或软件，也没有新增向公开账号发表作品的入口。当前工作区的测试不能代表云端 AstrBot、Windows 或真实 QQ 已经验收通过。

## 从经历到作品

1. 大肥鱼通过已有浏览工具取得实际内容，形成当前主人私聊下的经历记录。
2. 选择一个持续目标，建立文字作品；同一目标继续使用同一作品。
3. 引用经历 ID 写草稿，每次保存产生不可覆盖的版本。正文分为 `## 资料观察`、`## 我的想法`、`## 待核实`，引用写为 `[E:经历ID]`。
4. 检查引用、来源和正文结构。资料不足时保留草稿并标记需要补充来源，后续继续浏览。
5. 检查通过后，可导出 Markdown，也可以主动在主人私聊分享标题和短摘录。QQ 分享记录实际发送回执，同一版本不会因重复唤醒再次投递。

`df_workshop` 提供 `create/list/read/revise/check/export/share/need_sources`。创建和修改受当前目标、会话、版本号与每轮修改额度约束；工具不能通过传入另一个私聊的 ID 读取其资料。`df_goal` 和 `df_recall` 继续负责目标与经历查询。

来源只接受同一会话中有实际内容的 `video/video_note/read` 经历。已被修订替代的来源不能继续通过检查；导出或分享前重新检查，不能依赖过去缓存的结果。检查通过表示结构和引用有效，不证明每句话在语义上正确，也不表示大肥鱼真的玩过游戏。正文需要区分资料观察、自己的想法和仍待核实的内容。

## 自主续写

调度器沿用原有周期，每次只运行一轮活动。有可继续的文字作品时，直接使用保存的资料续写；这一轮不申请手机操作锁，也不调用 PhoneMCP。因此手机离线或正在处理前台任务时，已有资料的写作仍可进行。需要新资料的作品返回浏览阶段，仍受设备状态和串行操作约束。

续写使用同一套时间、模型调用和主动分享预算，不能通过换活动类型获得额外额度。等待主人答复、待核实或已完成的目标不会被续写流程自动恢复。关闭创作开关、停止后台活动或前台打断后，已保存的版本保留。下一轮从现有目标和版本继续，不重放旧的手机操作或账号写入。

对主人分享的是带标题的文字摘录，使用现有 QQ 文本发送并保留回执；这不等于发送完整 Markdown 文件。导出的文件保存到插件状态目录内的 `works/<作品ID>/r<版本>.md`，工具返回路径及校验信息。Windows 路径、云端文件路径或“导出成功”都不能当作 QQ 文件实收证明。

## 配置和命令

新字段仍位于实际部署的 `plugin_data/astrbot_plugin_bili_activity/control.json`：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `workshop_enabled` | `false` | 文字作品与自主续写开关；同时要求 `life_enabled=true` |
| `workshop_revisions_per_run` | `3` | 每轮允许保存的新版本数，范围 `1..10` |
| `workshop_max_characters` | `12000` | 单个版本正文字符上限，范围 `500..20000` |

已有每日时间、模型调用与分享额度、检查间隔、主人身份和免打扰设置保持原值。开启创作不会自动开启周期，也不会更改公开互动、收藏/关注或截图开关。

先按 [README.md](README.md) 的实际部署流程更新插件与运维脚本并重载插件。以下命令用于实际云端目录；非默认状态目录在子命令前加 `--data-dir /实际目录`。

```bash
# 查看实际配置和最近作品；只读，不迁移数据库或重置运行目标。
python3 /opt/dafeiyu/tools/bili_activity/ops.py status
python3 /opt/dafeiyu/tools/bili_activity/ops.py works --limit 12
python3 /opt/dafeiyu/tools/bili_activity/ops.py work <作品ID>
python3 /opt/dafeiyu/tools/bili_activity/ops.py work <作品ID> --revision 1

# 调整创作额度；修改前自动备份原 control.json。
python3 /opt/dafeiyu/tools/bili_activity/ops.py configure \
  --workshop-revisions-per-run 3 --workshop-max-characters 12000

# 原有一次性 B 站活动已实际验收且 life_enabled 已开启后，开启文字创作。
python3 /opt/dafeiyu/tools/bili_activity/ops.py switch workshop_enabled on

# 安排一次新版本验证。此命令不会替你打开周期。
python3 /opt/dafeiyu/tools/bili_activity/ops.py once --delay-seconds 180

# 查看目标、经历、发送账本和日志。
python3 /opt/dafeiyu/tools/bili_activity/ops.py goals --all
python3 /opt/dafeiyu/tools/bili_activity/ops.py episodes --limit 20
python3 /opt/dafeiyu/tools/bili_activity/ops.py logs --lines 100

# 只关闭创作功能，保留已有浏览设置。
python3 /opt/dafeiyu/tools/bili_activity/ops.py switch workshop_enabled off

# 停止整个插件的后台活动，并关闭其周期和待执行的一次性任务。
python3 /opt/dafeiyu/tools/bili_activity/ops.py stop
```

`work` 输出的 `validation_is_cached=true` 表明它仅展示该版本保存的检查结果，不在只读运维命令中重新验证。需要当前检查、导出或分享时，通过实际 AstrBot Agent 调用 `df_workshop`。只有原有 B 站一次性活动已验收、主人私聊和免打扰已配置、`life_enabled=true` 时，运维命令才允许开启创作；开关操作不代替任何验收记录。

首次验证前先记录周期开关，必要时用 `disable-periodic` 暂停本插件周期，再安排一次性任务。验证后只恢复原来启用的周期，保留其他已暂停任务。

## 保存与回退

作品和版本保存在原 `activity.sqlite3` 内的独立 `creative_*` 表，按会话隔离。首次新增结构前保留一致性数据库备份；已有目标、提议、发送防重和记忆队列继续保留。正文和来源 ID 随版本一起保存，更新需要预期版本号，避免前台和后台互相覆盖。

`status/works/work` 用只读 SQLite 连接查询，不实例化插件 Store，不进行崩溃恢复，不迁移数据库。旧库尚无作品表时作品列表为空；已有表损坏或缺列时明确报错。

回退前停止活动并备份最新状态，特别是外部写入、发送回执和防重账本。不能通过还原到旧库来重新发送已投递的版本或重复执行已经批准的账号操作。作品正文只是数据，旧版忽略新增表不代表旧版具备续写能力。

## 生产验收记录

需要在实际环境保留以下记录，不能以离线模拟测试代替：

1. 真实浏览来源的 `run_id`、`goal_id`、经历 ID、视频身份及实际分析范围。
2. `work_id`、草稿版本、正文、引用清单及当前检查结果；对不支持的推断写入“待核实”。
3. 停止并重启 AstrBot 后，继续同一作品，保存新版本并能读取旧版。
4. 手机不可用时，已有资料的续写正常完成；需要新资料时回到浏览阶段，不伪造读取成功。
5. 私聊实际收到贴合内容的文字摘录，记录 message_id；重复调用同一版本没有再次投递，后续活动仍能继续。
6. 导出文件的实际路径、版本和校验信息；LivingMemory 保存后实际召回一次作品进展。
7. 关闭开关、额度耗尽、来源被修订、错误版本号和其他会话查询均正确停止或拒绝，不覆盖已有草稿。

公开评论、回复、收藏和关注仍使用原有“具体提议 → 主人答复 → 执行一次 → 回读核实”流程。创作工具没有增加这些操作的权限。
