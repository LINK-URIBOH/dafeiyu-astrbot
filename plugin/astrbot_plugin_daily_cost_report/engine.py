from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from .domain import LABELS, PROVIDERS, ZONE, amount, balance_cost, bill_total, display, latest_end, local, money, months_for, stamp
from .providers import SourceError


class Engine:
    def __init__(self, store, adapters, config, send, authorized, clock=None):
        self.store, self.adapters, self.config = store, adapters, config
        self.send, self.authorized = send, authorized
        self.clock = clock or (lambda: datetime.now(ZONE))
        self.capture_lock, self.send_lock = asyncio.Lock(), asyncio.Lock()

    def enabled(self, provider):
        return bool(self.config.get(provider + '_enabled', True))

    async def capture(self, planned=None, history_start=None):
        if not self.config.get('collection_enabled', True):
            return
        async with self.capture_lock:
            now = stamp(self.clock())
            planned = now if planned is None else planned
            start = history_start or stamp(latest_end(self.clock()) - timedelta(days=7))

            async def one(provider):
                if not self.enabled(provider):
                    self.store.state(provider, {'status': 'disabled', 'reason': '此平台已停用'})
                    return
                prior = self.store.state(provider)
                try:
                    data = await asyncio.wait_for(self.adapters.collect(provider, now, start), timeout=65)
                    observed = stamp(self.clock())
                    self.store.snapshot(provider, planned, observed, data)
                    self.store.state(provider, {'status': 'ok', 'last_success': observed, **data})
                except asyncio.CancelledError:
                    raise
                except SourceError as error:
                    self.store.state(provider, {**prior, 'status': error.code, 'reason': error.reason, 'last_attempt': now})
                except Exception:
                    self.store.state(provider, {**prior, 'status': 'error', 'reason': '费用采集失败；未显示上游响应或凭据', 'last_attempt': now})

            await asyncio.gather(*(one(p) for p in PROVIDERS))

    def build(self, ending, until=None):
        start = ending - 86400
        stop = ending if until is None else until
        result = {'ending': ending, 'start': start, 'until': stop, 'providers': {},
                  'first_partial': int(self.store.meta('first_seen')) > start}
        for provider in PROVIDERS:
            state = self.store.state(provider)
            last = self.store.latest(provider, stop + 300)
            row = {'cost': None, 'currency': 'CNY', 'reason': '', 'balance': None,
                   'cash': None, 'available': None, 'observed': None, 'source_status': state.get('status')}
            if last:
                row.update({key: last.get(key) for key in ('balance', 'cash', 'available', 'observed')})
            if not self.enabled(provider):
                row['reason'] = '此平台已停用'
            elif provider == 'bailian':
                account = (last or state).get('account')
                cycles = months_for(start, stop)
                records, covered = self.store.bills(account, cycles) if account else ([], False)
                if covered:
                    row['cost'], row['reason'] = bill_total(records, start, stop)
                    if state.get('status') != 'ok' or not state.get('billing_complete'):
                        row['reason'] += '；本次更新失败，使用已存账单，尚未核齐'
                else:
                    row['reason'] = state.get('billing_error') or state.get('reason') or '账单尚未取得完整月份，不能判定零消费'
            else:
                a = self.store.boundary(provider, start)
                b = self.store.boundary(provider, stop)
                adjustment = self.store.adjustments(provider, start, stop)
                row['cost'], row['reason'] = balance_cost(a, b, adjustment)
                row['adjustment'] = amount(adjustment)
                row['sample_times'] = [a.get('observed') if a else None, b.get('observed') if b else None]
                if provider == 'siliconflow' and b:
                    row['reason'] += '；' + b.get('balance_scope', '现金口径')
                if state.get('status') != 'ok':
                    row['reason'] += '；' + state.get('reason', '当前来源未就绪')
            result['providers'][provider] = row
        return result

    def reconcile(self, ending):
        for offset in range(7, -1, -1):
            target = ending - offset * 86400
            if target >= int(self.store.meta('first_seen')):
                self.store.save_report(self.build(target))

    def render(self, report):
        ending, start = report['ending'], report['start']
        lines = ['三平台费用日报' if report['until'] == ending else '当前统计窗口（尚未结束）',
                 local(start).strftime('%m-%d %H:%M') + ' → ' + local(report['until']).strftime('%m-%d %H:%M') + '（北京时间）']
        if report['first_partial']:
            lines.append('首日数据不完整：安装前余额不追溯补造。')
        for provider, row in report['providers'].items():
            lines.append(LABELS[provider] + '：' + display(row['cost']))
            lines.append('  ' + row['reason'])
            if provider == 'bailian':
                lines.append('  现金余额 ' + display(row['cash']) + '；可用额度 ' + display(row['available']))
            else:
                lines.append('  余额 ' + display(row['balance']))
            if row['observed']:
                lines.append('  余额采样 ' + local(row['observed']).strftime('%m-%d %H:%M:%S'))
        # Total balance, cash spend and unsettled payable are not interchangeable.
        lines.append('口径包含余额差与暂计应付费用，本期不作统一合计。')
        return '\n'.join(lines)

    def status(self):
        lines = ['费用日报：22:00 / Asia/Shanghai',
                 '采集：' + ('开' if self.config.get('collection_enabled', True) else '关'),
                 '推送：' + ('开' if self.config.get('report_enabled', True) else '关')]
        for provider in PROVIDERS:
            row = self.store.state(provider)
            text = row.get('billing_error') or row.get('reason') or row.get('status', '未配置')
            if row.get('last_success'):
                text += '；最后成功 ' + local(row['last_success']).strftime('%m-%d %H:%M:%S')
            lines.append(LABELS[provider] + '：' + text)
        unknown = self.store.meta('delivery_note')
        if unknown:
            lines.append(unknown)
        return '\n'.join(lines)

    async def tick(self):
        now_dt, now = self.clock().astimezone(ZONE), stamp(self.clock())
        hour = now_dt.replace(minute=0, second=0, microsecond=0)
        hour_id = hour.isoformat()
        if self.config.get('collection_enabled', True) and self.store.meta('last_hour') != hour_id:
            await self.capture(stamp(hour))
            self.store.set_meta('last_hour', hour_id)
        ending = stamp(latest_end(now_dt))
        self.reconcile(ending)
        if self.store.meta('last_prune') != now_dt.date().isoformat():
            self.store.prune(now)
            self.store.set_meta('last_prune', now_dt.date().isoformat())
        first_seen = int(self.store.meta('first_seen'))
        due = [ending - i * 86400 for i in range(6, -1, -1) if ending - i * 86400 >= first_seen]
        candidates = []
        for end in due:
            delivery = self.store.delivery(end)
            if delivery is None or (delivery['status'] == 'failed' and delivery['attempts'] < 3 and now - delivery['updated'] >= 600):
                candidates.append(end)
        if not self.config.get('report_enabled', True):
            for end in candidates:
                if self.store.claim([end], now):
                    self.store.finish([end], 'suppressed', now)
            return
        if not candidates or not (8 <= now_dt.hour < 23) or not self.authorized():
            return
        async with self.send_lock:
            if not self.store.claim(candidates, now):
                return
            reports = [self.store.report(end) or self.build(end) for end in candidates]
            corrections = self.store.pending_corrections()
            # A seven-day catch-up remains one QQ message, not seven long reports.
            if len(reports) == 1:
                body = self.render(reports[0])
            else:
                body = '费用日报合并补发（北京时间）\n' + '\n'.join(
                    local(r['ending']).strftime('%Y-%m-%d') + '：' + '；'.join(
                        LABELS[p] + ' ' + display(r['providers'][p]['cost']) for p in PROVIDERS) for r in reports)
                body += '\n仅列已取得数据；不可获取不是零消费。详情可用 /费用 日报 日期 查询。'
            if corrections:
                body += '\n历史补正：\n' + '\n'.join(
                    local(c['ending']).strftime('%m-%d') + ' ' + LABELS[c['provider']] + ' ' + display(c['body']['old']) + ' → ' + display(c['body']['new'])
                    for c in corrections[-21:])
                if len(corrections) > 21:
                    body += '\n其余补正已记入历史，可按日期查询。'
            try:
                # Recheck privileges immediately before the actual send.
                if not self.authorized():
                    self.store.finish(candidates, 'failed', now)
                    return
                sent = await asyncio.wait_for(self.send(body), timeout=20)
                if sent is True:
                    self.store.finish(candidates, 'sent', now, [c['id'] for c in corrections])
                else:
                    self.store.finish(candidates, 'failed', now)
            except asyncio.CancelledError:
                self.store.finish(candidates, 'unknown', now)
                raise
            except Exception:
                self.store.finish(candidates, 'unknown', now)
                self.store.set_meta('delivery_note', '有日报发送结果待确认，未盲目重发；请按日期查询历史。')
