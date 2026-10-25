# 自主生活 v0.4：研究方法复用

这一版让大肥鱼从已经完成、仍能核对来源的文字作品中总结研究步骤，并在另一个目标中尝试复用。方法保存适用条件、步骤、限制和来源版本；每次尝试保留对应目标、运行、产物及结果。原生 AstrBot Agent、人格、目标、作品、会话隔离、免打扰、活动预算和 LivingMemory 继续使用。

`methods_enabled` 默认关闭。本次是代码与离线测试交付，生产加载、真实模型选择方法、QQ 实收和 LivingMemory 召回需要现场验证。工作区恢复不代表已经连接生产 AstrBot 或 Windows。

## 方法的来源与使用

1. 先完成一个真实研究目标，留下通过当前来源和结构检查的文字作品。
2. 用 `df_method create` 提炼方法，填写适用条件、限制与步骤。方法引用具体作品版本、正文哈希和来源目标；刚保存的方法标为 `candidate`，不能自称已验证有效。
3. 在另一个已领取的目标上用 `select` 选择方法。尝试绑定目标和方法版本，现有 Agent 用本轮已有工具推进工作；步骤不会变成新的执行接口。
4. 根据实际资料创建或继续作品。保存尝试开始之后产生的新版本，保留新的内容和来源，再完成目标。
5. 通过 `df_goal` 完成目标时自动核对并记录方法结果，也可以用 `result` 记录或重查结果。成功必须经代码回查当前作品和来源，不能仅由模型说“成功了”；失败或放弃保留原因，也不能伪装成已通过的测试。结果调用返回的是保存的尝试记录，当前有效次数通过 `list/read` 重新核对。

`df_method` 提供 `create/revise/list/read/select/result/retire`。方法步骤是声明式文本，最多 6 步，类型限于 `gather`（搜集）、`verify`（核对）、`compare`（比较）、`write`（写作）、`review`（复查）。每步包含 `kind` 和 `instruction`。修改产生新版本，旧版尝试继续引用旧版，不会被悄悄替换。

方法不会安装程序、执行脚本、生成额外工具权限或扩大预算。评论、回复、收藏和关注仍走原有的具体提议及真实主人答复；外部资料和方法正文不能解除审批。私聊中的方法、步骤、产物和结果不会注入群聊或另一个私聊。

## 怎样计数

每个目标只保存一条方法尝试，不能通过重复调用、切换方法或重复唤醒刷次数。来源目标不能当作它自己的复用证据。成功产物需要属于尝试的目标、在尝试开始后产生、超出开始时已有版本，并区别于原作品和开始时的内容；仅改标题或拿旧作品冒充新成果不够。

运行时会重新核对来源和结果，来源被修订、失效或无法核实时，历史成功记录不会继续充当当前有效次数。`success_count` 表示当前证据仍成立的不同目标数量：0 次为 `candidate`，1 次为 `reused_once`，至少 2 次为 `reused_multiple`。这些标记只说明有几次符合要求的作品产出记录，不证明该方法在科学上有效，也不证明新作品的全部结论正确。

新方法版本单独统计，旧版记录继续保留。暂停或中断不会自动算成功；恢复时仍需领取目标并核对来源，再继续同一条尝试。停用方法会阻止新的复用，保留历史版本和记录。

## 运行与开关

新配置位于实际插件状态目录的 `control.json`：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `methods_enabled` | `false` | 研究方法工具与后台方法复用；同时需要 `life_enabled`、`workshop_enabled` |

没有新增第二个调度器或独立模型服务。模型调用、时间、分享和作品修订继续计入原有额度。仅根据已保存资料写作时，仍沿用 v0.3 的无手机续写流程；需要新资料时返回受设备锁保护的浏览流程。

运行中关闭方法开关，会停止已选用方法的后台活动并保留草稿与尝试进度。关闭方法开关不会改动浏览、公开互动、收藏/关注或截图开关。所有已暂停的其他任务继续保持原状态。

按 [README.md](README.md) 先备份并更新插件、运维脚本，再在实际 AstrBot 中重载插件。此版本没有新增 Windows 服务依赖。以下为默认云端路径；非默认状态目录在子命令前指定 `--data-dir /实际目录`：

```bash
# 查看实际状态及当前主人私聊的方法；均只读。
python3 /opt/dafeiyu/tools/bili_activity/ops.py status
python3 /opt/dafeiyu/tools/bili_activity/ops.py methods --limit 8
python3 /opt/dafeiyu/tools/bili_activity/ops.py method <方法ID>
python3 /opt/dafeiyu/tools/bili_activity/ops.py method <方法ID> --revision 1
python3 /opt/dafeiyu/tools/bili_activity/ops.py method-attempts --limit 20
python3 /opt/dafeiyu/tools/bili_activity/ops.py method-attempts --goal-id <目标ID>

# 已有一次性活动验收完成，life 与 workshop 已开启后，启用方法复用。
python3 /opt/dafeiyu/tools/bili_activity/ops.py switch methods_enabled on

# 根据原周期状态安排一次性现场验证；不会自动打开周期。
python3 /opt/dafeiyu/tools/bili_activity/ops.py once --delay-seconds 180
python3 /opt/dafeiyu/tools/bili_activity/ops.py logs --lines 100

# 关闭方法复用，保留其余功能开关。
python3 /opt/dafeiyu/tools/bili_activity/ops.py switch methods_enabled off

# 如需停止整个活动插件，用原有停止命令。
python3 /opt/dafeiyu/tools/bili_activity/ops.py stop
```

开启命令会检查主人私聊、免打扰、`one_shot_verified=true`、`life_enabled=true` 和 `workshop_enabled=true`；不会自动启用这些前置开关，也不会改动周期开关。已有一次性标记不能代替 v0.3/v0.4 的生产验收。验证前记录原周期状态，必要时只暂停本插件周期，验证后只恢复原本启用的周期。

运维输出的 `recorded_success_count` 是数据库中记载的次数，`evidence_rechecked=false` 表示本次只读查询没有重新验证来源。它可能大于运行时当前有效的 `success_count`。需要当前结果时调用实际 Agent 的 `df_method list/read`；不能把 CLI 历史次数当成现时能力证明。

## 保存、回退与验收

方法保存在原 `activity.sqlite3` 内的独立 `method_*`、`research_methods` 表。新增结构前进行一致性数据库备份，不改变主库版本或重置旧提议、发送账本与暂停状态。只读运维命令不实例化插件 Store，不迁移数据库，不把运行中目标或尝试改成暂停。旧库没有方法表时列表为空；已有结构损坏则明确报错。

回退前停止活动并备份最新状态。保留已执行账号操作和 QQ 发送回执，不能通过回滚旧库重复执行。停用方法不会删除历史证据；旧版插件忽略新增表不等于具备方法复用能力。

生产验收需保留以下实际证据：

1. 原目标完成记录、来源作品版本和哈希、当前来源检查结果。
2. 提炼的方法 ID、版本、步骤、适用条件和限制，初始有效复用次数为 0。
3. 另一个真实目标上的尝试 ID、运行 ID、开始时间和开始时的产物基线。
4. 本次尝试后的新资料与新作品、完成目标及成功回查结果；模型自报成功不能替代这些记录。
5. 重新启动后同一尝试继续推进，重复调用不新增次数；错误作用域、旧作品、已修订来源正确拒绝。
6. 关闭开关、暂停活动和预算耗尽后，草稿与尝试保留；公开账号写入权限没有变化。
7. 方法进展写入 LivingMemory 后实际召回；若分享作品，还要有真实 QQ 接收和发送回执。

离线测试只验证控制器、状态与接口规则。没有实际模型、生产设备、QQ 与记忆服务证据时，不能把上述现场项目标记为通过。
