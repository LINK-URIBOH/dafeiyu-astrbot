from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import re
import shlex

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain
from astrbot.api.message_components import Plain

from .domain import ALIASES, ZONE, date_end, latest_end, money, parse_time, stamp
from .engine import Engine
from .providers import Adapters
from .store import Store

HELP = ('费用管理（仅指定超级管理员私聊）\n/费用 状态\n/费用 今日\n/费用 日报 YYYY-MM-DD\n'
        '/费用 刷新\n/费用 推送 开|关\n/费用 采集 开|关\n'
        '/费用 调整 平台 有符号金额 YYYY-MM-DDTHH:MM 类型\n'
        '例：/费用 调整 deepseek +10 2026-10-28T12:30 充值\n'
        '资金进入填正数，失效或提现填负数；不是直接修改消费金额。\n/费用 撤销 调整编号')


def permitted(event, recipient, platform, admins):
    return (bool(recipient) and str(recipient) in {str(a) for a in admins}
            and event.is_private_chat() and not event.get_group_id()
            and str(event.get_sender_id()) == str(recipient) and event.get_platform_id() == platform)


@register('astrbot_plugin_daily_cost_report', 'LINK-URIBOH', '超级管理员私聊三平台费用日报，不调用模型', '1.0.0')
class DailyCostReport(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self.task = None
        self.lock_file = None
        self.engine = None

    def authorized(self):
        recipient = str(self.config.get('recipient_qq', '')).strip()
        return bool(recipient) and recipient in {str(a) for a in self.context.get_config().get('admins_id', [])}

    async def initialize(self):
        import fcntl
        data = Path(__file__).resolve().parents[2] / 'plugin_data/astrbot_plugin_daily_cost_report'
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_file = (data / 'scheduler.lock').open('a')
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            self.lock_file = None
            logger.warning('[daily_cost_report] 已有活动实例，本实例不启动定时器')
            return
        store = Store(data / 'costs.sqlite3')
        store.recover(stamp(datetime.now(ZONE)))
        adapters = Adapters(store, self.config.get('secrets_file', '/run/secrets/daily-cost-report.json'))

        async def send(text):
            if not self.authorized():
                return False
            session = self.config.get('platform_id', 'qq') + ':FriendMessage:' + str(self.config.get('recipient_qq', ''))
            return await self.context.send_message(session, MessageChain(chain=[Plain(text)]))

        self.engine = Engine(store, adapters, self.config, send, self.authorized)
        self.task = asyncio.create_task(self.loop(), name='daily-cost-report')
        logger.info('[daily_cost_report] 私聊费用日报已加载；22:00 Asia/Shanghai；不调用模型')

    async def loop(self):
        while True:
            try:
                await self.engine.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning('[daily_cost_report] 后台检查失败：' + type(error).__name__)
            await asyncio.sleep(20)

    async def terminate(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    @filter.regex(r'^/?费用(?:\s|$)', priority=100000)
    async def cost_commands(self, event: AstrMessageEvent):
        text = event.message_str.strip()
        # AstrBot's waking stage removes the configured '/' prefix before
        # evaluating plugin filters and invoking handlers.
        if not re.match(r'^/?费用(?:\s|$)', text):
            return
        event.stop_event()
        if not permitted(event, str(self.config.get('recipient_qq', '')), self.config.get('platform_id', 'qq'), self.context.get_config().get('admins_id', [])):
            return  # Never reveal financial details in groups or unauthorized chats.
        if not self.engine:
            await event.send(event.plain_result('费用插件尚未就绪，请检查实例锁及日志。'))
            return
        try:
            args = shlex.split(text)[1:]
            action = args[0] if args else '帮助'
            now = datetime.now(ZONE)
            if action == '状态':
                result = self.engine.status()
            elif action == '刷新':
                await self.engine.capture()
                self.engine.reconcile(stamp(latest_end(now)))
                result = '已只读刷新，未额外推送日报。\n' + self.engine.status()
            elif action == '今日':
                await self.engine.capture()
                end = stamp(latest_end(now) + timedelta(days=1))
                result = self.engine.render(self.engine.build(end, stamp(datetime.now(ZONE))))
            elif action == '日报' and len(args) == 2:
                end = date_end(args[1])
                if not stamp(now) - 365 * 86400 <= end <= stamp(latest_end(now)):
                    raise ValueError('只支持一年内已经结束的日报窗口')
                await self.engine.capture(history_start=end - 86400)
                report = self.engine.build(end)
                self.engine.store.save_report(report)
                result = self.engine.render(report)
            elif action in ('推送', '采集') and len(args) == 2 and args[1] in ('开', '关'):
                key = 'report_enabled' if action == '推送' else 'collection_enabled'
                self.config[key] = args[1] == '开'
                if hasattr(self.config, 'save_config'):
                    self.config.save_config()
                result = action + '已' + args[1] + ('；关闭推送仍会继续采集。' if action == '推送' else '；暂停期间不补造余额快照。')
            elif action == '调整' and len(args) == 5:
                provider = ALIASES.get(args[1].lower())
                if provider not in ('deepseek', 'siliconflow'):
                    raise ValueError('仅余额差来源需要资金调整；百炼按平台账单统计')
                moment = parse_time(args[3])
                if moment > stamp(now) or moment < stamp(now) - 365 * 86400:
                    raise ValueError('调整时间须在过去一年内，不接受未来资金记录')
                kind = args[4]
                if kind not in ('充值', '赠金', '退款', '失效', '提现', '调账'):
                    raise ValueError('类型：充值、赠金、退款、失效、提现、调账')
                value = money(args[2])
                if (kind in ('充值', '赠金', '退款') and value <= 0) or (kind in ('失效', '提现') and value >= 0):
                    raise ValueError('资金流入填正数，失效或提现填负数')
                row_id = self.engine.store.adjustment(provider, moment, value, kind, stamp(now))
                self.engine.reconcile(stamp(latest_end(now)))
                result = f'已登记资金调整 #{row_id}，保留审计记录；历史费用变化将列入日报补正。'
            elif action == '撤销' and len(args) == 2:
                ok = self.engine.store.revoke(int(args[1]), stamp(now))
                self.engine.reconcile(stamp(latest_end(now)))
                result = '已撤销调整并保留审计记录。' if ok else '未找到可撤销的调整编号。'
            else:
                result = HELP
        except ValueError as error:
            # Local validation errors contain no request bodies or credentials.
            result = '参数错误：' + str(error)[:160]
        except Exception as error:
            logger.warning('[daily_cost_report] 管理操作失败：' + type(error).__name__)
            result = '费用操作失败，请查看脱敏状态；未显示密钥或接口原文。'
        # stop_event deliberately blocks the result pipeline and all lower-priority
        # handlers. Send directly so stopping also cannot suppress our own reply.
        await event.send(event.plain_result(result))
