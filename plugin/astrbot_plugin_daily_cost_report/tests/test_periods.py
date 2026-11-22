"""Calendar-week and lifetime balance statistics with synthetic amounts."""
import json,tempfile
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from test_cost_report import Store,Engine,ZONE,stamp,date_end,snap

END=date_end('2026-11-23')
FIRST=stamp(datetime(2026,10,27,23,43,tzinfo=ZONE))
MONDAYS=[stamp(datetime(2026,11,day,tzinfo=ZONE)) for day in (2,9,16,23)]

class PeriodTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'stats.sqlite3';self.store=Store(self.path,FIRST)
        self.engine=Engine(self.store,SimpleNamespace(collect=AsyncMock()),{},None,lambda:False,lambda:datetime.fromtimestamp(END-3600,ZONE))
        for provider in ('deepseek','bailian','siliconflow'):
            for moment,value in [(FIRST,'20'),*zip(MONDAYS,['18','17','14','12']),(END-86400,'13'),(END,'11')]:
                self.put(provider,moment,value)
    def put(self,provider,moment,value,**extra):
        item=snap(value,**extra)
        if provider=='bailian':item.update(cash=value,balance=None,available='999')
        self.store.snapshot(provider,moment,moment,item)
    def stats(self,provider='deepseek',end=END):return self.engine.build(end)['providers'][provider]['statistics']
    def test_cumulative_starts_at_earliest_compatible_sample(self):
        s=self.stats();self.assertEqual(s['cumulative_change'],'-9');self.assertEqual(s['cumulative_start'],FIRST)
    def test_full_monday_weeks_exclude_first_partial_and_current_week(self):
        s=self.stats();self.assertEqual(s['weekly_change'],'-2');self.assertEqual(s['week_count'],3)
        self.assertEqual(s['weekly_start'],MONDAYS[0]);self.assertEqual(s['weekly_end'],MONDAYS[-1])
    def test_aliyun_uses_cash_not_available_credit(self):
        self.assertEqual(self.stats('bailian')['cumulative_change'],'-9');self.assertEqual(self.stats('bailian')['weekly_change'],'-2')
    def test_siliconflow_statistics_use_cash(self):
        self.assertEqual(self.stats('siliconflow')['weekly_change'],'-2')
    def test_all_three_rows_render_extra_fields_and_week_count(self):
        text=self.engine.render(self.engine.build(END))
        self.assertEqual(text.count('累计：'),3);self.assertEqual(text.count('自然周均：'),3)
        self.assertIn('3个完整自然周',text);self.assertIn('周一00:00',text)
    def test_current_week_change_does_not_change_weekly_average(self):
        self.put('deepseek',END,'7');s=self.stats()
        self.assertEqual(s['cumulative_change'],'-13');self.assertEqual(s['weekly_change'],'-2')
    def test_missing_last_monday_not_zero_or_silent_previous_week(self):
        with self.store.db() as d:d.execute('DELETE FROM snapshots WHERE provider=? AND planned=?',('deepseek',MONDAYS[-1]))
        s=self.stats();self.assertIsNone(s['weekly_change']);self.assertIn('零点',s['reason']);self.assertEqual(s['cumulative_change'],'-9')
    def test_missing_first_monday_starts_with_first_valid_complete_week(self):
        with self.store.db() as d:d.execute('DELETE FROM snapshots WHERE provider=? AND planned=?',('deepseek',MONDAYS[0]))
        s=self.stats();self.assertEqual(s['weekly_start'],MONDAYS[1]);self.assertEqual(s['week_count'],2);self.assertEqual(s['weekly_change'],'-2.5')
    def test_no_internal_boundaries_needed_for_equal_week_net_average(self):
        with self.store.db() as d:d.execute('DELETE FROM snapshots WHERE provider=? AND planned IN (?,?)',('deepseek',MONDAYS[1],MONDAYS[2]))
        s=self.stats();self.assertEqual(s['weekly_change'],'-2');self.assertEqual(s['week_count'],3)
    def test_account_change_never_combines_accounts(self):
        self.put('deepseek',END,'100',account='new-account');s=self.stats()
        self.assertEqual(s['cumulative_change'],'0');self.assertEqual(s['cumulative_start'],END);self.assertIsNone(s['weekly_change'])
    def test_wallet_mapping_change_never_combines_cash_bases(self):
        self.put('siliconflow',END,'100',verified_mapping='new-map');s=self.stats('siliconflow')
        self.assertEqual(s['cumulative_change'],'0');self.assertEqual(s['cumulative_start'],END)
    def test_bad_earliest_money_is_skipped(self):
        self.put('deepseek',FIRST-3600,'NaN');self.assertEqual(self.stats()['cumulative_start'],FIRST)
    def test_registered_topup_does_not_adjust_net_statistics(self):
        self.store.adjustment('deepseek',END-2,'10','充值',END)
        self.assertEqual(self.stats()['cumulative_change'],'-9');self.assertEqual(self.stats()['weekly_change'],'-2')
    def test_increase_and_exact_zero_are_preserved(self):
        self.put('deepseek',END,'22');self.assertEqual(self.stats()['cumulative_change'],'2')
        self.put('siliconflow',END,'20');self.assertEqual(self.stats('siliconflow')['cumulative_change'],'0')
    def test_restart_keeps_baselines_and_original_cutover(self):
        before=self.stats();cutover=self.engine.cutover
        self.engine=Engine(Store(self.path),None,{},None,lambda:False,lambda:datetime.fromtimestamp(END+86400,ZONE))
        self.assertEqual(self.stats(),before);self.assertEqual(self.engine.cutover,cutover)
    def test_retention_does_not_move_remembered_baselines(self):
        initial=self.stats()
        with self.store.db() as d:d.execute('DELETE FROM snapshots WHERE observed<?',(MONDAYS[-1],))
        self.assertEqual(self.stats(),initial)
    def test_before_a_complete_week_no_fake_weekly_zero(self):
        end=date_end('2026-10-28');self.put('deepseek',end,'19')
        # This scenario is a fresh install before that window, not a request
        # to reconstruct a frozen pre-cutover historical report.
        self.engine.cutover=end;self.store.set_meta('balance_report_start',end)
        s=self.stats(end=end);self.assertIsNone(s['weekly_change']);self.assertIn('暂无',s['reason'])
    def test_monday_boundary_tolerance(self):
        self.store.snapshot('deepseek',MONDAYS[-1],MONDAYS[-1]+299,snap('12'))
        self.assertEqual(self.stats()['weekly_change'],'-2')
        self.store.snapshot('deepseek',MONDAYS[-1],MONDAYS[-1]+301,snap('12'))
        self.assertIsNone(self.stats()['weekly_change'])
    def test_partial_today_does_not_use_future_samples(self):
        report=self.engine.build(END,END-30)
        self.assertIsNone(report['providers']['deepseek']['statistics']['cumulative_change'])

if __name__=='__main__':unittest.main()
