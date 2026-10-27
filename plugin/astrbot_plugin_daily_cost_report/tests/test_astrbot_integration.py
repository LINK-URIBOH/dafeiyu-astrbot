"""Run in AstrBot's deployment image; no real QQ messages or model calls."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
HAS_ASTRBOT = importlib.util.find_spec('astrbot') is not None


@unittest.skipUnless(HAS_ASTRBOT, 'Run these tests in the pinned AstrBot image')
class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    def event(self, sender='123', private=True, group='', platform='qq', text='/费用 状态'):
        return SimpleNamespace(message_str=text, is_private_chat=lambda: private, get_group_id=lambda: group,
            get_sender_id=lambda: sender, get_platform_id=lambda: platform,
            stop_event=lambda: None, plain_result=lambda s:s, get_message_str=lambda:text,send=AsyncMock())

    async def asyncSetUp(self):
        from astrbot_plugin_daily_cost_report.main import DailyCostReport
        self.plugin = DailyCostReport(SimpleNamespace(get_config=lambda:{'admins_id':['123']}),
                                      {'recipient_qq':'123','platform_id':'qq'})
        self.plugin.engine = SimpleNamespace(status=lambda:'PRIVATE_FINANCIAL_STATE')

    async def test_owner_private_can_query(self):
        event=self.event()
        await self.plugin.cost_commands(event)
        event.send.assert_awaited_once_with('PRIVATE_FINANCIAL_STATE')

    async def test_normal_member_cannot_query(self):
        event=self.event(sender='999')
        await self.plugin.cost_commands(event)
        event.send.assert_not_called()

    async def test_group_admin_and_owner_in_group_cannot_query(self):
        for sender in ('123','999'):
            event=self.event(sender=sender,private=False,group='456')
            await self.plugin.cost_commands(event)
            event.send.assert_not_called()

    async def test_other_platform_cannot_query(self):
        event=self.event(platform='webchat')
        await self.plugin.cost_commands(event)
        event.send.assert_not_called()

    async def test_removed_global_admin_cannot_query(self):
        self.plugin.context.get_config=lambda:{'admins_id':['999']}
        event=self.event()
        await self.plugin.cost_commands(event)
        event.send.assert_not_called()

    async def test_ordinary_message_does_not_activate_filter(self):
        from astrbot.core.star.filter.regex import RegexFilter
        gate = RegexFilter(r'^/?费用(?:\s|$)')
        self.assertFalse(gate.filter(self.event(text='普通群消息'), {}))
        self.assertTrue(gate.filter(self.event(text='/费用 状态'), {}))

    async def test_prefix_removed_by_real_waking_stage(self):
        from astrbot.core.star.filter.regex import RegexFilter
        event=self.event(text='费用 状态')
        self.assertTrue(RegexFilter(r'^/?费用(?:\s|$)').filter(event,{}))
        await self.plugin.cost_commands(event)
        event.send.assert_awaited_once_with('PRIVATE_FINANCIAL_STATE')

    async def test_real_handler_wrapper_sends_even_when_pipeline_stopped(self):
        from astrbot.core.pipeline.context_utils import call_handler
        event=self.event()
        stopped=[]
        event.stop_event=lambda:stopped.append(True)
        async for _ in call_handler(event,self.plugin.cost_commands):
            if stopped:
                break  # The real scheduler does not run response stages here.
        self.assertTrue(stopped)
        event.send.assert_awaited_once_with('PRIVATE_FINANCIAL_STATE')


if __name__ == '__main__': unittest.main(verbosity=2)
