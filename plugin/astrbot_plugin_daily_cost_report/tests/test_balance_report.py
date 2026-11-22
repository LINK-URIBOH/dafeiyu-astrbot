"""Balance-only v2 behavior, using synthetic accounts and isolated SQLite."""
import asyncio,json,sqlite3,tempfile
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from test_cost_report import END,ZONE,Store,Engine,Adapters,snap

class BalanceReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'costs.sqlite3';self.store=Store(self.path,END-90000)
        self.now=datetime.fromtimestamp(END-1800,ZONE)
        self.adapters=SimpleNamespace(collect=AsyncMock(return_value=snap('8')))
        self.sender=AsyncMock(return_value=True);self.config={'report_enabled':True,'collection_enabled':True}
        self.engine=Engine(self.store,self.adapters,self.config,self.sender,lambda:True,lambda:self.now)
    def seed(self,provider,a,b,**extra):
        for ending,value in [(END-86400,a),(END,b)]:
            row=snap(value,**extra)
            if provider=='bailian':row.update(cash=value,balance=None,available='999')
            self.store.snapshot(provider,ending,ending,row)
        self.store.state(provider,{'status':'ok'})
    def legacy(self):
        return {'ending':END-86400,'start':END-172800,'until':END-86400,'first_partial':False,
                'providers':{p:{'cost':None,'reason':'OLD_SAVED_TEXT','balance':None,'cash':None,'available':None,'observed':None} for p in ('deepseek','bailian','siliconflow')}}
    def save_legacy_fixture(self):
        old=self.legacy()
        with self.store.db() as db:
            db.execute('INSERT INTO reports VALUES(?,?,?)',(old['ending'],3,json.dumps(old)))
        self.store.claim([old['ending']],END-86400);self.store.finish([old['ending']],'sent',END-86400)
        return old
    def history_rows(self):
        with self.store.db() as db:
            return [tuple(x) for x in db.execute('SELECT * FROM reports WHERE ending<?',(END,))],[tuple(x) for x in db.execute('SELECT * FROM deliveries WHERE ending<?',(END,))]
    async def test_cash_diff_not_blocked_by_coarse_bills_or_available_credit(self):
        self.seed('bailian','40.10','40.01')
        self.store.replace_bills('account','2026-10',[{'id':'coarse','start':END-90000,'end':END+10000,'cost':'100','currency':'CNY'}],END)
        row=self.engine.build(END)['providers']['bailian']
        self.assertEqual(Decimal(row['balance_change']),Decimal('-0.09'))
        self.assertEqual(row['opening_balance'],'40.10');self.assertEqual(row['closing_balance'],'40.01')
    async def test_render_clear_deltas_without_normal_sampling_noise(self):
        self.seed('deepseek','10.14','10');self.seed('bailian','40.10','40.01');self.seed('siliconflow','7.12345678','7.12345678')
        text=self.engine.render(self.engine.build(END))
        for phrase in ('三平台余额日报','减少 ￥0.1400','减少 ￥0.0900','阿里云账户（百炼等）','现金余额未变化','不等同于本期调用费用'):
            self.assertIn(phrase,text)
        for phrase in ('资金变化需登记','余额差计算','余额采样','可用额度','暂计应付','统一合计'):
            self.assertNotIn(phrase,text)
    async def test_increase_not_missing_or_negative_expense(self):
        self.seed('deepseek','10','18');row=self.engine.build(END)['providers']['deepseek']
        self.assertEqual(Decimal(row['balance_change']),Decimal(8))
        self.assertIn('增加 ￥8.0000',self.engine.render(self.engine.build(END)))
    async def test_event_annotations_do_not_rewrite_delta(self):
        self.seed('bailian','10','18');self.store.adjustment('bailian',END-1,'10','充值',END)
        row=self.engine.build(END)['providers']['bailian']
        self.assertEqual(Decimal(row['balance_change']),Decimal(8))
        self.assertIn('充值',self.engine.render(self.engine.build(END)))
        self.assertNotIn('消费 ￥2',self.engine.render(self.engine.build(END)))
    async def test_missing_opening_or_closing_is_never_zero(self):
        for at,expected in [(END,'期初'),(END-86400,'期末')]:
            with self.store.db() as db:db.execute('DELETE FROM snapshots')
            self.store.snapshot('deepseek',at,at,snap('10'))
            row=self.engine.build(END)['providers']['deepseek']
            self.assertIsNone(row['balance_change']);self.assertIn(expected,row['reason'])
    async def test_both_boundaries_absent_described(self):
        row=self.engine.build(END)['providers']['deepseek']
        self.assertIsNone(row['balance_change']);self.assertIn('期初',row['reason']);self.assertIn('期末',row['reason'])
    async def test_sample_tolerance_account_and_currency(self):
        self.seed('deepseek','10','8')
        self.store.snapshot('deepseek',END,END+301,snap('8'))
        self.assertIsNone(self.engine.build(END)['providers']['deepseek']['balance_change'])
        self.store.snapshot('deepseek',END,END,snap('8',account='other'))
        self.assertIn('账户',self.engine.build(END)['providers']['deepseek']['reason'])
        self.store.snapshot('deepseek',END,END,snap('8',currency='USD'))
        self.assertIn('币种',self.engine.build(END)['providers']['deepseek']['reason'])
    async def test_cash_missing_does_not_fall_back_to_available(self):
        self.seed('bailian','10','8')
        self.store.snapshot('bailian',END,END,snap(None,cash=None,available='8'))
        self.assertIsNone(self.engine.build(END)['providers']['bailian']['balance_change'])

    async def test_wallet_mapping_change_requires_new_same_basis_baseline(self):
        self.seed('siliconflow','10','8',verified_mapping='old-cash-mapping')
        self.store.snapshot('siliconflow',END,END,snap('8',verified_mapping='new-cash-mapping'))
        row=self.engine.build(END)['providers']['siliconflow']
        self.assertIsNone(row['balance_change']);self.assertIn('同口径',row['reason'])
    async def test_used_counter_does_not_replace_cash_change(self):
        self.seed('siliconflow','10','10',used='100')
        self.store.snapshot('siliconflow',END,END,snap('10',used='200'))
        self.assertEqual(Decimal(self.engine.build(END)['providers']['siliconflow']['balance_change']),0)
    async def test_tiny_change_is_not_called_unchanged(self):
        self.seed('siliconflow','10','9.99999')
        text=self.engine.render(self.engine.build(END))
        self.assertIn('不足',text);self.assertNotIn('现金余额未变化',text)
    async def test_current_window_uses_recent_sample_not_22_boundary(self):
        self.now=datetime.fromtimestamp(END-600,ZONE)
        self.store.snapshot('deepseek',END-86400,END-86400,snap('10'))
        self.store.snapshot('deepseek',END-600,END-600,snap('9'))
        report=self.engine.build(END,END-600)
        self.assertEqual(Decimal(report['providers']['deepseek']['balance_change']),-1)
        self.assertIn('截至当前采样',self.engine.render(report))
    async def test_current_window_rejects_stale_sample(self):
        self.store.snapshot('deepseek',END-86400,END-86400,snap('10'))
        self.store.snapshot('deepseek',END-601,END-601,snap('9'))
        self.assertIsNone(self.engine.build(END,END-300)['providers']['deepseek']['balance_change'])
    async def test_history_query_reconcile_and_tick_keep_legacy_bytes_and_delivery(self):
        old=self.save_legacy_fixture();before=self.history_rows()
        self.assertEqual(await self.engine.historical(old['ending']),old)
        self.adapters.collect.assert_not_awaited()
        self.engine.reconcile(END-86400);await self.engine.tick()
        self.assertEqual(self.history_rows(),before);self.sender.assert_not_awaited()
        self.assertIn('OLD_SAVED_TEXT',self.engine.render(old))
    async def test_missing_legacy_history_not_reconstructed(self):
        with self.assertRaisesRegex(ValueError,'历史'):await self.engine.historical(END-86400)
        self.adapters.collect.assert_not_awaited()
    async def test_store_blocks_accidental_old_report_write(self):
        old=self.save_legacy_fixture();old['first_partial']=True
        with self.assertRaisesRegex(ValueError,'历史'):self.store.save_report(old)
    async def test_cutover_is_next_22_and_stable_after_restart(self):
        self.assertEqual(int(self.store.meta('balance_report_start')),END)
        self.now=datetime.fromtimestamp(END+2*86400,ZONE)
        second=Engine(Store(self.path),self.adapters,self.config,self.sender,lambda:True,lambda:self.now)
        self.assertEqual(second.cutover,END)
    async def test_starting_exactly_at_22_does_not_rewrite_just_closed_report(self):
        path=Path(self.tmp.name)/'second.db';now=datetime.fromtimestamp(END,ZONE)
        engine=Engine(Store(path,END),self.adapters,self.config,self.sender,lambda:True,lambda:now)
        self.assertEqual(engine.cutover,END+86400)
    async def test_real_scheduler_sends_v2_only_once(self):
        for provider in ('deepseek','bailian','siliconflow'):self.seed(provider,'10','9')
        self.now=datetime.fromtimestamp(END,ZONE)
        await self.engine.tick();await self.engine.tick()
        self.sender.assert_awaited_once();self.assertIn('三平台余额日报',self.sender.call_args.args[0])
        self.assertEqual(self.store.report(END)['schema_version'],2)
    async def test_new_missing_boundary_correction_does_not_touch_legacy(self):
        self.save_legacy_fixture();before=self.history_rows()
        self.engine.reconcile(END);self.store.claim([END],END);self.store.finish([END],'sent',END)
        self.seed('deepseek','10','8');self.engine.reconcile(END)
        self.assertEqual(self.history_rows(),before)
        changes=self.store.pending_corrections(END)
        self.assertEqual(len(changes),1);self.assertEqual(changes[0]['body']['metric'],'balance_change')
    async def test_bailian_balance_collection_never_queries_bill(self):
        secret=Path(self.tmp.name)/'secret.json';secret.write_text(json.dumps({'bailian':{'access_key_id':'synthetic','access_key_secret':'synthetic'}}));secret.chmod(0o600)
        calls=[]
        def client(operation,params):
            calls.append(operation)
            if operation!='balance':raise AssertionError('No bill calls for balance reporting')
            return {'Success':True,'Data':{'Currency':'CNY','AvailableCashAmount':'40.01','AvailableAmount':'99'}}
        row=await Adapters(self.store,secret,environ={},bss_factory=lambda _:client).collect('bailian',END,END-86400)
        self.assertEqual(calls,['balance']);self.assertEqual(row['cash'],'40.01')
        self.assertEqual(self.store.bills('anything',['2026-10']),([],False))

    async def test_historical_status_failure_does_not_invalidate_complete_boundaries(self):
        self.seed('deepseek','10','9');self.store.state('deepseek',{'status':'network','reason':'当前超时'})
        self.assertEqual(self.engine.build(END)['providers']['deepseek']['balance_change'],'-1')

    async def test_cutover_is_atomic_for_two_engine_instances(self):
        later=datetime.fromtimestamp(END+86400,ZONE)
        other=Engine(Store(self.path),self.adapters,self.config,self.sender,lambda:True,lambda:later)
        self.assertEqual(other.cutover,self.engine.cutover)

    async def test_recover_preserves_legacy_sending_receipt(self):
        self.store.claim([END-86400,END],END)
        Store(self.path).recover(END+10)
        self.assertEqual(self.store.delivery(END-86400)['status'],'sending')
        self.assertEqual(self.store.delivery(END)['status'],'unknown')

    async def test_legacy_corrections_are_not_merged_into_new_push(self):
        with self.store.db() as db:
            db.execute('INSERT INTO corrections(ending,provider,revision,body) VALUES(?,?,?,?)',(END-86400,'bailian',2,json.dumps({'old':'1','new':'2'})))
        self.now=datetime.fromtimestamp(END,ZONE)
        await self.engine.tick()
        self.assertNotIn('补正',self.sender.call_args.args[0])
        self.assertEqual(len(self.store.pending_corrections()),1)

    async def test_cross_month_cash_difference(self):
        from astrbot_plugin_daily_cost_report.domain import date_end
        end=date_end('2026-11-01')
        for moment,value in [(end-86400,'10'),(end,'9.9')]:
            self.store.snapshot('bailian',moment,moment,snap(None,cash=value))
        self.assertEqual(self.engine.build(end)['providers']['bailian']['balance_change'],'-0.1')

    async def test_invalid_nan_and_infinite_balance_not_displayed(self):
        self.seed('bailian','10','9')
        for value in ('NaN','Infinity',True,None):
            self.store.snapshot('bailian',END,END,snap(None,cash=value))
            self.assertIsNone(self.engine.build(END)['providers']['bailian']['balance_change'])

    async def test_event_revoke_removes_note_not_balance_difference(self):
        self.seed('bailian','10','18')
        rid=self.store.adjustment('bailian',END-1,'10','充值',END)
        self.store.revoke(rid,END+1)
        row=self.engine.build(END)['providers']['bailian']
        self.assertEqual(row['balance_change'],'8');self.assertEqual(row['events'],[])

if __name__=='__main__':unittest.main()
