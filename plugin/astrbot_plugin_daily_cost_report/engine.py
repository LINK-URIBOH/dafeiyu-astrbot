from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from .domain import BALANCE_LABELS, BOUNDARY_TOLERANCE, movement, LABELS, PROVIDERS, ZONE, amount, balance_cost, bill_total, display, latest_end, local, money, months_for, stamp
from .providers import SourceError
from .periods import summarize


class Engine:
    def __init__(self, store, adapters, config, send, authorized, clock=None):
        self.store, self.adapters, self.config = store, adapters, config
        self.send, self.authorized = send, authorized
        self.clock = clock or (lambda: datetime.now(ZONE))
        self.capture_lock, self.send_lock = asyncio.Lock(), asyncio.Lock()
        self.cutover = store.establish_balance_cutover(stamp(latest_end(self.clock()) + timedelta(days=1)))

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
        if until is None and ending < self.cutover:
            saved = self.store.report(ending)
            if saved is None:
                raise ValueError('该日期没有已保存的历史日报；旧窗口不重新计算')
            return saved
        start, stop = ending - 86400, ending if until is None else until
        result = {'schema_version': 2, 'ending': ending, 'start': start, 'until': stop,
                  'first_partial': int(self.store.meta('first_seen')) > start, 'providers': {}}
        for provider in PROVIDERS:
            state = self.store.state(provider)
            a = self.store.boundary(provider, start)
            b = self.store.boundary(provider, stop) if until is None else self.store.latest(provider, stop)
            if until is not None and b and stop - b['observed'] > BOUNDARY_TOLERANCE:
                b = None
            field = 'cash' if provider == 'bailian' else 'balance'
            row = {'balance_change': None, 'opening_balance': None, 'closing_balance': None,
                   'sample_times': [a.get('observed') if a else None, b.get('observed') if b else None],
                   'currency': 'CNY', 'reason': '', 'source_status': state.get('status'),
                   'events': self.store.events(provider, start, stop)}
            if not self.enabled(provider):
                row['reason'] = '此平台已停用'
            elif not a or not b:
                missing = []
                if not a: missing.append('缺少期初22点有效采样')
                if not b: missing.append('缺少期末22点有效采样' if until is None else '最近5分钟没有成功采样')
                row['reason'] = '；'.join(missing)
                if state.get('status') != 'ok':
                    row['reason'] += '；' + state.get('reason', '采集尚未就绪')
            elif not a.get('account') or a.get('account') != b.get('account'):
                row['reason'] = '两端账户不一致，不能计算余额差'
            elif a.get('currency') != 'CNY' or b.get('currency') != 'CNY':
                row['reason'] = '两端币种不是同一人民币口径，不能计算余额差'
            elif provider == 'siliconflow' and a.get('verified_mapping') != b.get('verified_mapping'):
                row['reason'] = '两端现金字段或金额单位发生变化，需要重新建立同口径基线'
            else:
                try:
                    opening, closing = money(a.get(field)), money(b.get(field))
                    row.update(opening_balance=amount(opening), closing_balance=amount(closing),
                               balance_change=amount(closing - opening))
                except ValueError:
                    row['reason'] = '缺少有效现金余额字段' if provider == 'bailian' else '缺少有效余额字段'
            result['providers'][provider] = row
            if self.enabled(provider):
                row['statistics'] = summarize(self.store, provider, b, stop)
        return result

    async def historical(self, ending):
        if ending < self.cutover:
            return self.build(ending)  # Frozen report: no refresh or database write.
        await self.capture()
        report = self.build(ending)
        self.store.save_report(report)
        return report

    def reconcile(self, ending):
        for offset in range(7, -1, -1):
            target = ending - offset * 86400
            if target >= max(self.cutover, int(self.store.meta('first_seen'))):
                self.store.save_report(self.build(target))

    def render(self, report):
        if report.get('schema_version') != 2:
            return self.render_legacy(report)
        complete = report['until'] == report['ending']
        lines = ['三平台余额日报' if complete else '当前余额变化（截至当前采样，窗口尚未结束）',
                 local(report['start']).strftime('%m-%d %H:%M') + ' → ' + local(report['until']).strftime('%m-%d %H:%M') + '（北京时间）']
        if report['first_partial']:
            lines.append('首日数据不完整：缺少安装前的有效采样。')
        for provider, row in report['providers'].items():
            cash = provider != 'deepseek'
            lines += ['', BALANCE_LABELS[provider] + '：' + movement(row['balance_change'], cash)]
            if row['balance_change'] is None:
                lines.append('  ' + row['reason'])
            else:
                prefix = '现金 ' if cash else '余额 '
                suffix = '（现金＋赠金）' if not cash else ('（不含代金券）' if provider == 'siliconflow' else '')
                lines.append('  ' + prefix + display(row['opening_balance']) + ' → ' + display(row['closing_balance']) + suffix)
            for event in row.get('events', []):
                value = money(event['value'])
                lines.append('  已登记：' + event['kind'] + (' +' if value > 0 else ' -') + display(abs(value)) + '（不改变余额差）')
            stats=row.get('statistics')
            if stats:
                if stats['cumulative_change'] is not None:
                    lines.append('  累计：' + movement(stats['cumulative_change'],cash) + '（自' + local(stats['cumulative_start']).strftime('%Y-%m-%d %H:%M') + '）')
                else:
                    lines.append('  累计：无法计算，' + stats['reason'])
                if stats['weekly_change'] is not None:
                    lines.append('  自然周均：' + movement(stats['weekly_change'],cash) + '／周（' + str(stats['week_count']) + '个完整自然周）')
                else:
                    lines.append('  自然周均：' + stats['reason'])
        lines += ['', '以上为余额变化，不等同于本期调用费用。', '阿里云包含账户内其他产品，扣款也可能延迟。']
        lines.append('自然周：周一00:00至下周一00:00；首个不足周和当前周不计入周均。')
        return '\n'.join(lines)

    def render_legacy(self, report):
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
        lines = ['三平台余额日报：22:00 / Asia/Shanghai',
                 '新版首个日报截止：' + local(self.cutover).strftime('%Y-%m-%d %H:%M'),
                 '旧版历史日报：冻结保存，不重算、不补发',
                 '采集：' + ('开' if self.config.get('collection_enabled', True) else '关'),
                 '推送：' + ('开' if self.config.get('report_enabled', True) else '关')]
        for provider in PROVIDERS:
            row = self.store.state(provider)
            text = '余额采集正常' if row.get('status') == 'ok' else row.get('reason', '尚未配置或采集')
            if row.get('last_success'):
                text += '；最后成功 ' + local(row['last_success']).strftime('%m-%d %H:%M:%S')
            sample = self.store.latest(provider)
            if sample:
                if provider == 'bailian':
                    text += '；现金 ' + display(sample.get('cash')) + '；可用额度 ' + display(sample.get('available'))
                else:
                    text += '；余额 ' + display(sample.get('balance'))
            lines.append(BALANCE_LABELS[provider] + '：' + text)
        unknown = self.store.meta('delivery_note')
        if unknown: lines.append(unknown)
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
        due = [ending - i * 86400 for i in range(6, -1, -1) if ending - i * 86400 >= max(first_seen, self.cutover)]
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
            corrections = self.store.pending_corrections(self.cutover)
            # A seven-day catch-up remains one QQ message, not seven long reports.
            if len(reports) == 1:
                body = self.render(reports[0])
            else:
                body = '余额日报合并补发（北京时间）\n' + '\n'.join(
                    local(r['ending']).strftime('%Y-%m-%d') + '：' + '；'.join(
                        BALANCE_LABELS[p] + ' ' + movement(r['providers'][p]['balance_change'], p != 'deepseek') for p in PROVIDERS) for r in reports)
                body += '\n余额缺失不等于未变化；阿里云为账户级现金。详情用 /费用 日报 日期 查询。'
            if corrections:
                body += '\n新版窗口余额补正：\n' + '\n'.join(
                    local(c['ending']).strftime('%m-%d') + ' ' + BALANCE_LABELS[c['provider']] + ' ' + movement(c['body']['old']) + ' → ' + movement(c['body']['new'])
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
