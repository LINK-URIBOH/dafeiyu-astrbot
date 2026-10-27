import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

# Local core tests use only injected HTTP; the deployment image has real aiohttp.
if importlib.util.find_spec('aiohttp') is None:
    sys.modules['aiohttp'] = SimpleNamespace()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from astrbot_plugin_daily_cost_report.domain import ZONE, balance_cost, bill_total, date_end, latest_end, money, months_for, stamp
from astrbot_plugin_daily_cost_report.engine import Engine
from astrbot_plugin_daily_cost_report.providers import Adapters, SourceError, http_json, normalize_bills
from astrbot_plugin_daily_cost_report.store import Store


END = date_end('2026-10-28')

def snap(balance='10', account='account', **extra):
    return {'balance': balance, 'account': account, 'currency': 'CNY', **extra}

def bill(rid='1', start='2026-10-28 20:00:00', end='2026-10-28 21:00:00', value='1', **extra):
    return {'RecordID': rid, 'SubOrderId': '1', 'ProductCode': 'model-service', 'ProductName': '大模型服务平台百炼',
            'Item': 'PayAsYouGoBill', 'Currency': 'CNY', 'PretaxAmount': value,
            'UsageStartTime': start, 'UsageEndTime': end, **extra}


class MathTests(unittest.TestCase):
    def test_money_exact(self):
        self.assertEqual(money('0.1') + money('0.2'), Decimal('0.3'))

    def test_money_rejects_missing_nan_bool(self):
        for value in (None, True, 'NaN', 'Infinity', ''):
            with self.assertRaises(ValueError): money(value)

    def test_22_boundaries(self):
        for hour, minute, day in [(21, 59, 27), (22, 0, 28), (23, 0, 28)]:
            now = datetime(2026, 10, 28, hour, minute, tzinfo=ZONE)
            self.assertEqual(latest_end(now).day, day)

    def test_cross_month(self):
        self.assertEqual(months_for(date_end('2026-10-31'), date_end('2026-11-01')), ['2026-10', '2026-11'])

    def test_topup_corrected(self):
        self.assertEqual(balance_cost(snap('10'), snap('18'), Decimal(10))[0], '2')

    def test_expiry_corrected(self):
        self.assertEqual(balance_cost(snap('10'), snap('7'), Decimal(-2))[0], '1')

    def test_unexplained_increase_not_clamped(self):
        self.assertIsNone(balance_cost(snap('10'), snap('12'), Decimal(0))[0])

    def test_cumulative_ignores_topup_adjustment(self):
        self.assertEqual(balance_cost(snap('10', used='1'), snap('30', used='3'), Decimal(22))[0], '2')

    def test_rotated_account_and_currency(self):
        self.assertIsNone(balance_cost(snap(), snap(account='new'), Decimal(0))[0])
        self.assertIsNone(balance_cost(snap(), snap(currency='USD'), Decimal(0))[0])

    def test_incomplete_is_not_zero(self):
        self.assertIsNone(balance_cost(None, snap(), Decimal(0))[0])

    def test_bill_half_open_and_exact_end(self):
        rows = [{'start': END - 3600, 'end': END, 'cost': '0.1', 'currency': 'CNY'},
                {'start': END, 'end': END + 3600, 'cost': '99', 'currency': 'CNY'}]
        self.assertEqual(bill_total(rows, END - 86400, END)[0], '0.1')

    def test_no_apportioning(self):
        rows = [{'start': END - 3600, 'end': END + 3600, 'cost': '2', 'currency': 'CNY'}]
        self.assertIsNone(bill_total(rows, END - 86400, END)[0])

    def test_missing_bill_time(self):
        self.assertIsNone(bill_total([{'start': None, 'end': None}], END - 86400, END)[0])

    def test_bill_dedupe_refund_and_exclude_other_products(self):
        rows, codes = normalize_bills([bill(), bill(), bill('2', value='0.2', Item='Refund'),
                                      bill('3', ProductCode='ecs', ProductName='云服务器')])
        self.assertEqual(len(rows), 2)
        self.assertEqual(bill_total(rows, END - 86400, END)[0], '0.8')

    def test_conflicting_bill_ids_fail(self):
        with self.assertRaises(SourceError): normalize_bills([bill(value='1'), bill(value='2')])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'costs.sqlite3'
        self.store = Store(self.path, END - 100000)

    def tearDown(self): self.temp.cleanup()

    def test_boundary_tolerance(self):
        self.store.snapshot('deepseek', END, END + 301, snap())
        self.assertIsNone(self.store.boundary('deepseek', END))
        self.store.snapshot('deepseek', END, END + 299, snap())
        self.assertIsNotNone(self.store.boundary('deepseek', END))

    def test_adjustment_audit_revoke(self):
        rid = self.store.adjustment('deepseek', END - 1, '10', '充值', END)
        self.assertEqual(self.store.adjustments('deepseek', END - 86400, END), Decimal(10))
        self.assertTrue(self.store.revoke(rid, END + 1))
        self.assertFalse(self.store.revoke(rid, END + 2))
        self.assertEqual(self.store.adjustments('deepseek', END - 86400, END), Decimal(0))
        db = sqlite3.connect(self.path)
        try: self.assertEqual(db.execute('SELECT COUNT(*) FROM adjustments').fetchone()[0], 1)
        finally: db.close()

    def test_restart_delivery_unknown(self):
        self.assertTrue(self.store.claim([END], END))
        second = Store(self.path)
        second.recover(END + 1)
        self.assertEqual(second.delivery(END)['status'], 'unknown')
        self.assertFalse(second.claim([END], END + 1000))

    def test_retry_throttle_and_limit(self):
        for n in range(3):
            self.assertTrue(self.store.claim([END], END + n * 600))
            self.store.finish([END], 'failed', END + n * 600)
        self.assertFalse(self.store.claim([END], END + 1800))

    def test_month_replacement_atomic(self):
        self.store.replace_bills('a', '2026-10', [{'id': 'x', 'cost': '1'}], END)
        self.store.replace_bills('a', '2026-10', [{'id': 'x', 'cost': '2'}], END + 1)
        rows, covered = self.store.bills('a', ['2026-10'])
        self.assertTrue(covered); self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['cost'], '2')

    def test_retention(self):
        self.store.snapshot('deepseek', 1, 1, snap())
        self.store.prune(END)
        self.assertIsNone(self.store.latest('deepseek'))


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'db.sqlite3', END - 80000)
        self.secret = Path(self.temp.name) / 'secrets.json'
        self.secret.write_text('{}'); self.secret.chmod(0o600)
        self.now = datetime.fromtimestamp(END, ZONE)
        self.sender = AsyncMock(return_value=True)
        self.adapters = SimpleNamespace(collect=AsyncMock(return_value=snap('8')))
        self.config = {'report_enabled': True, 'collection_enabled': True}
        self.engine = Engine(self.store, self.adapters, self.config, self.sender, lambda: True, lambda: self.now)
        self.http = AsyncMock()

    async def asyncTearDown(self): self.temp.cleanup()

    def adapter(self, env=None, factory=None):
        return Adapters(self.store, self.secret, environ=env or {}, get_json=self.http, bss_factory=factory)

    def secrets(self, value):
        self.secret.write_text(json.dumps(value)); self.secret.chmod(0o600)

    async def test_deepseek_no_model_call(self):
        self.http.return_value = {'balance_infos': [{'currency': 'CNY', 'total_balance': '1.25'}]}
        row = await self.adapter({'DEEPSEEK_API_KEY': 'synthetic-key'}).collect('deepseek', END, END - 86400)
        self.assertEqual(row['balance'], '1.25')
        self.assertEqual(self.http.call_args.args[0], 'https://api.deepseek.com/user/balance')

    async def test_other_invalid_secrets_do_not_break_deepseek(self):
        self.secret.write_text('invalid')
        self.http.return_value = {'balance_infos': [{'currency': 'CNY', 'total_balance': '0'}]}
        self.assertEqual((await self.adapter({'DEEPSEEK_API_KEY': 'x'}).collect('deepseek', END, 1))['balance'], '0')

    async def test_missing_credentials_not_zero(self):
        with self.assertRaises(SourceError): await self.adapter().collect('siliconflow', END, 1)
        self.http.assert_not_called()

    def sf_config(self, **extra):
        return {'siliconflow': {'cookie': 'synthetic-cookie', 'subject_id': 'synthetic-subject',
            'currency': 'CNY', 'amount_scale': '0.000000000001', 'reference_cash_balance_cny': '2', **extra}}

    async def test_sf_cash_mapping_verified(self):
        self.secrets(self.sf_config())
        self.http.return_value = {'data': {'financialInfo': {'balance': '2000000000000', 'used': '99000000000000'}}}
        row = await self.adapter().collect('siliconflow', END, 1)
        self.assertEqual(money(row['balance']), 2); self.assertIsNone(row['used'])
        self.assertIn('cloud.siliconflow.cn/', self.http.call_args.args[0])

    async def test_sf_cumulative_requires_reference(self):
        self.secrets(self.sf_config(reference_cumulative_used_cny='3'))
        self.http.return_value = {'data': {'financialInfo': {'balance': '2000000000000', 'used': '3000000000000'}}}
        row = await self.adapter().collect('siliconflow', END, 1)
        self.assertEqual(money(row['used']), 3)

    async def test_sf_bad_units_fail_closed(self):
        self.secrets(self.sf_config(amount_scale='1'))
        self.http.return_value = {'data': {'financialInfo': {'balance': '2000000000000'}}}
        with self.assertRaises(SourceError): await self.adapter().collect('siliconflow', END, 1)

    async def test_sf_missing_fields_not_zero(self):
        self.secrets(self.sf_config())
        self.http.return_value = {'data': {}}
        with self.assertRaises(SourceError): await self.adapter().collect('siliconflow', END, 1)

    async def test_sf_verified_mapping_survives_restart(self):
        self.secrets(self.sf_config())
        self.http.return_value = {'data': {'financialInfo': {'balance': '2000000000000'}}}
        row = await self.adapter().collect('siliconflow', END, 1)
        self.store.state('siliconflow', {'status': 'ok', **row})
        self.http.return_value = {'data': {'financialInfo': {'balance': '1000000000000'}}}
        row = await self.adapter().collect('siliconflow', END + 3600, 1)
        self.assertEqual(money(row['balance']), 1)

    async def test_redirect_destination_rejected(self):
        with self.assertRaises(SourceError): await http_json('https://example.com/', {'Authorization': 'secret'})

    async def test_bailian_pagination_and_dedup(self):
        self.secrets({'bailian': {'access_key_id': 'synthetic', 'access_key_secret': 'synthetic', 'product_codes': ['model-service']}})
        def client(operation, params):
            if operation == 'balance': return {'Success': True, 'Data': {'Currency': 'CNY', 'AvailableAmount': '8', 'AvailableCashAmount': '10'}}
            rows = [bill(str(i)) for i in range(300)] if params['page_num'] == 1 else [bill('300')]
            return {'Success': True, 'Data': {'Items': {'Item': rows}, 'TotalCount': 301}}
        row = await self.adapter(factory=lambda _: client).collect('bailian', END, END - 86400)
        records, covered = self.store.bills(row['account'], ['2026-10'])
        self.assertTrue(covered); self.assertEqual(len(records), 301); self.assertEqual(row['cash'], '10')

    async def test_bailian_empty_unidentified_not_zero(self):
        self.secrets({'bailian': {'access_key_id': 'x', 'access_key_secret': 'x'}})
        def client(operation, params):
            return {'Success': True, 'Data': {'Currency': 'CNY', 'AvailableAmount': '8', 'AvailableCashAmount': '10'} if operation == 'balance' else {'Items': {'Item': []}, 'TotalCount': 0}}
        row = await self.adapter(factory=lambda _: client).collect('bailian', END, END - 86400)
        self.assertFalse(row['billing_complete']); self.assertEqual(row['cash'], '10')

    async def test_partial_platform_failure_still_sends(self):
        async def collect(provider, *_):
            if provider == 'siliconflow': raise SourceError('authentication', '登录态失效')
            return snap('8')
        self.adapters.collect.side_effect = collect
        await self.engine.tick()
        self.sender.assert_awaited_once()
        self.assertIn('登录态失效', self.sender.call_args.args[0])
        self.assertEqual(self.store.delivery(END)['status'], 'sent')

    async def test_duplicate_tick_does_not_send_twice(self):
        await self.engine.tick(); await self.engine.tick()
        self.sender.assert_awaited_once()

    async def test_off_does_not_disable_capture_or_catch_up_muted_reports(self):
        self.config['report_enabled'] = False
        await self.engine.tick()
        self.assertEqual(self.adapters.collect.await_count, 3)
        self.sender.assert_not_called()
        self.config['report_enabled'] = True
        await self.engine.tick()
        self.sender.assert_not_called()

    async def test_collection_pause_has_no_queries(self):
        self.config['collection_enabled'] = False
        await self.engine.tick()
        self.adapters.collect.assert_not_called()
        self.assertIn('缺少22点', self.sender.call_args.args[0])

    async def test_night_restart_waits_until_8(self):
        self.now = datetime(2026, 10, 29, 2, tzinfo=ZONE)
        await self.engine.tick(); self.sender.assert_not_called()
        self.now = datetime(2026, 10, 29, 8, tzinfo=ZONE)
        await self.engine.tick(); self.sender.assert_awaited_once()

    async def test_seven_day_catchup_is_one_message(self):
        self.store.set_meta('first_seen', END - 10 * 86400)
        await self.engine.tick()
        self.sender.assert_awaited_once(); self.assertIn('合并补发', self.sender.call_args.args[0])
        self.assertEqual(len([i for i in range(7) if self.store.delivery(END - i * 86400)]), 7)

    async def test_first_day_not_fabricated(self):
        self.store.set_meta('first_seen', END - 300)
        await self.engine.tick()
        self.assertIn('首日数据不完整', self.sender.call_args.args[0])

    async def test_removal_of_admin_blocks_send(self):
        self.engine.authorized = lambda: False
        await self.engine.tick(); self.sender.assert_not_called()

    async def test_timeout_marks_unknown_no_retry(self):
        self.sender.side_effect = TimeoutError()
        await self.engine.tick(); await self.engine.tick()
        self.sender.assert_awaited_once(); self.assertEqual(self.store.delivery(END)['status'], 'unknown')

    async def test_late_bill_correction(self):
        self.store.snapshot('deepseek', END - 86400, END - 86400, snap('10'))
        self.store.snapshot('deepseek', END, END, snap('8'))
        self.store.state('bailian', {'status': 'ok', 'billing_complete': True, 'account': 'a'})
        self.store.replace_bills('a', '2026-10', [], END)
        self.engine.reconcile(END)
        self.store.claim([END], END); self.store.finish([END], 'sent', END)
        self.store.replace_bills('a', '2026-10', [{'id': 'x', 'start': END - 100, 'end': END, 'currency': 'CNY', 'cost': '2'}], END + 1)
        self.engine.reconcile(END)
        changes = self.store.pending_corrections()
        self.assertEqual(len(changes), 1); self.assertEqual(changes[0]['body'], {'old': '0', 'new': '2'})


if __name__ == '__main__': unittest.main(verbosity=2)
