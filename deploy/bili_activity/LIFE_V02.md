# 自主生活 v0.2：目标、经历与活动预算

这一版扩展现有 B 站活动插件：让大肥鱼保存一个自己的小目标，在后续活动中重新观察设备后继续推进，并通过带来源的经历解释进展。继续使用当前 AstrBot Agent、人格、PhoneMCP、B 站服务、QQ 发送和 LivingMemory。

本文描述代码能力和操作方法。开发环境的离线测试不代表已经完成 Windows、云端 AstrBot、真实 QQ 或 B 站账号验收；新代码不会自动打开线上开关。

## 新增能力与边界

- **持续目标**：保存目标、理由、下一步、状态、检查点和证据引用。重启后的运行中目标转为暂停；恢复前重新核对设备和视频身份，不直接重放旧点击或写操作。
- **历次经历**：追加记录视频标识、实际分析范围、来源、时间和自己的感想。原视频表仍是最近状态缓存，新的经历表供长期查询；纠错通过修订关系保留来源。
- **兴趣归属**：Agent 工具只能记录大肥鱼自己的兴趣，且须引用已有经历。主人明确表达的偏好由真实 QQ 消息入口识别并保存消息来源；“可以收藏”仍仅是一次操作授权。不同会话独立检索。
- **活动预算**：按上海自然日持久化时间、模型调用次数和主动分享次数。先预留再执行；崩溃或未知发送结果不退还可能已消耗的额度，避免重启绕过预算。
- **前台优先**：前台设备请求或停止会让后台在可中断边界保存进度并让出设备。断线后结束当前轮次，后续条件恢复时重新观察再继续。

`df_goal` 支持创建、选择、更新和查看目标；`df_recall` 查询当前私聊的经历；`df_interest` 记录有经历来源的自身兴趣。具体参数以 AstrBot 实际注册的工具说明为准，模型不能通过这些工具批准账号操作。

在主人私聊说“暂停自主活动”可暂停本轮并保存进度；说“继续自主活动”后，会等现有周期、聊天冷却和预算条件满足再运行。目标在等待答复时不会自行恢复；提议过期或被拒绝后可以继续只读活动，未知写入仍保持待核实状态。

所有评论、回复、关注和收藏变更仍走原来的具体提议 → 主人明确答复 → 执行一次 → 回读核实。结果不确定时继续保留原 operation_id，不能借目标恢复重发。确认前关闭操作开关属于确定未执行，结束该提议并释放未决位置。

## 配置与启停

仍使用现有 `plugin_data/astrbot_plugin_bili_activity/control.json`。升级保留已有字段、检查间隔、免打扰、周期状态和其他暂停任务。缺少的新字段采用以下默认值：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `life_enabled` | `false` | 持续目标和新活动预算总开关 |
| `daily_minutes` | `30` | 每天自主活动分钟数上限 |
| `max_model_calls_per_run` | `20` | 单轮模型调用次数上限 |
| `daily_model_calls` | `60` | 每天模型调用次数上限 |
| `daily_shares` | `3` | 每天主动分享额度；`0` 禁止主动分享 |
| `screenshots_per_run` | `1` | 单轮主动截图额度；`0` 禁止主动截图 |
| `chat_cooldown_seconds` | `300` | 收到聊天后的后台冷却时间；`0` 关闭冷却 |

旧字段 `max_videos/max_minutes` 继续控制单轮视频数和时长。现有实际检查间隔保持不变：分支默认是 `120±60` 分钟，不能用早期的 30 分钟要求覆盖现场已调整的值。

以下命令在实际云端部署目录执行；非默认状态目录在子命令前加 `--data-dir /实际目录`：

首次验证新版本前，先记录当前周期开关。若它原来开启，可用 `disable-periodic` 暂停本插件周期，再安排一次性活动；完成验收后仅恢复原来开启的周期，不启用其他已暂停任务。

```bash
# 查看当前配置和最近活动；此命令只读，不会初始化或迁移数据库。
python3 /opt/dafeiyu/tools/bili_activity/ops.py status

# 调整新增预算；保存前自动备份 control.json。
python3 /opt/dafeiyu/tools/bili_activity/ops.py configure \
  --daily-minutes 30 --max-model-calls-per-run 20 --daily-model-calls 60 \
  --daily-shares 3 --screenshots-per-run 1 --chat-cooldown-seconds 300

# 已有 B 站一次性活动验收通过后，才允许开启此增强功能。
python3 /opt/dafeiyu/tools/bili_activity/ops.py switch life_enabled on

# 安排一次新版本的实际验证；是否启用周期仍保持原配置。
python3 /opt/dafeiyu/tools/bili_activity/ops.py once --delay-seconds 180

# 查看持续目标、经历索引和结构化日志。
python3 /opt/dafeiyu/tools/bili_activity/ops.py goals
python3 /opt/dafeiyu/tools/bili_activity/ops.py goals --all --limit 20
python3 /opt/dafeiyu/tools/bili_activity/ops.py episodes --limit 20
python3 /opt/dafeiyu/tools/bili_activity/ops.py logs --lines 100

# 立即停止本插件后台活动及周期；被动截图仍受截图开关控制。
python3 /opt/dafeiyu/tools/bili_activity/ops.py stop
```

`switch life_enabled on` 本身不启动活动，也不打开周期。它要求原有 `one_shot_verified=true` 以及已核对的主人私聊和免打扰设置。首次 B 站验收仍按 [README.md](README.md) 的 `once`、QQ 实收与 `accept-one-shot` 流程完成，不能通过直接修改验收字段代替。

`switch life_enabled off` 只关闭增强功能，保留原有浏览和周期开关；如果要停止所有后台浏览，应使用 `stop`。`switch screenshot_enabled off` 控制主动与被动截图分享。公开互动和收藏/关注管理仍分别由 `public_interactions`、`collection_management` 控制，开关开启不等于批准某次操作。

新预算适用于开启持续目标功能后的本插件后台活动，提议消息也占主动分享额度。主人主动请求截图不占主动分享额度。现有 `proactive_chat` 是独立插件，当前没有与本插件共享每日预算；不能把这里的 `daily_shares` 当作整个 QQ 机器人的全局上限。模型调用数统计原生 Agent 的 Provider 调用（含备用提供商）及本轮显式视觉/ASR 调用；不等同于供应商内部 HTTP 请求数、LivingMemory 内部调用或账单金额。

主人偏好入口目前只自动识别有真实 QQ 消息 ID 的“我喜欢/我不喜欢/我更喜欢/我讨厌……”完整短句；无法明确识别时保留普通聊天，不自动推断。经历表支持追加修订，当前工具侧提供查询和兴趣记录，未增加自然语言批量修改历史的入口。

## 数据升级与回退

现有 `activity.sqlite3` 加法迁移到带版本的目标/经历结构。迁移前通过 SQLite 一致性备份保存 `schema_backups/activity-v0-*.sqlite3`，包含 WAL 中已提交的数据。原提议、防重、回执、视频和记忆队列继续保留；预算使用同库的独立表。

`status/goals/episodes` 以只读方式打开数据库，旧版本没有新表时返回空项，不进行迁移、不重置运行租约。数据库损坏或已有表结构错误会明确报错，不伪装成空状态。

回退前先停止活动，保留最新外部写入、防重和发送账本。不能把整库还原到外部操作发生前，再重新运行旧任务。更高数据库版本会被拒绝打开，避免旧代码不理解新状态仍继续执行。恢复备份需要核对这些状态，不能只替换数据库文件。

## 实际验收

1. 在一轮真实活动中保存有限目标、来源和下一步；截图分享以 QQ 可打开的图片和 message_id 为证。
2. 重启 AstrBot，再次运行能继续同一目标；BV/cid 和实际分析范围重新核对，未知播放位置保持未知。
3. 插入前台设备请求、断线、停止和预算耗尽，确认不再发新命令，后续恢复不重复发送或写入。
4. 分别测试“她喜欢”“主人明确喜欢”和“主人同意一次操作”，再在其他会话查询，核对归属和隔离。
5. 主人询问“你最近在忙什么”“为什么还想继续”，回答对应实际目标及经历；LivingMemory 保存后实际召回一次。
6. 保留跨日记录，以及重复答复、关闭互动开关、写入结果未知的处理证据。单元测试中的时间推进不能冒充跨日生产运行。

记录代码版本、goal_id、run_id、视频身份和范围、QQ 回执、proposal_id、真实答复、回读结果及记忆召回。没有发生的活动或分享不能补写为成功。
