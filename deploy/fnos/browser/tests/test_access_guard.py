"""Exercise the actual pre-model guard; no network, models or credentials."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, text, inspection=None, error=None, model_text='{}'):
        agent = object.__new__(server.ReadOnlyAgent)
        page = SimpleNamespace(evaluate=AsyncMock(return_value=inspection, side_effect=error))
        agent.browser_session = SimpleNamespace(get_current_page=AsyncMock(return_value=page))
        agent.state = SimpleNamespace(last_model_output=SimpleNamespace(model_dump_json=lambda: model_text))
        agent.blocked_reason = None
        state = SimpleNamespace(dom_state=SimpleNamespace(llm_representation=lambda: text))
        with patch.object(server.Agent, '_get_next_action', new=AsyncMock(return_value='read-public-content')) as model:
            try:
                value = await agent._get_next_action(state)
                return value, model.await_count, agent.blocked_reason
            except RuntimeError:
                return None, model.await_count, agent.blocked_reason

    async def test_nonblocking_login_tip_does_not_stop_public_reading(self):
        value, calls, reason = await self.invoke(
            '登录后你可以 免费看高清视频 立即登录 综合热门 视频标题 UP主',
            {'text': '综合热门 视频标题 UP主', 'challenge': False})
        self.assertEqual(value, 'read-public-content')
        self.assertEqual(calls, 1)
        self.assertIsNone(reason)

    async def test_model_mentioning_optional_login_popup_is_not_a_wall(self):
        value, calls, _ = await self.invoke('公开视频', {'text': '公开视频', 'challenge': False},
                                          model_text='右上角有非阻挡登录浮层，继续读取公开视频')
        self.assertEqual(value, 'read-public-content')
        self.assertEqual(calls, 1)

    async def test_real_login_wall_stops_before_model(self):
        for text in ('请先登录后查看', '扫码登录', '密码登录', '请登录'):
            with self.subTest(text=text):
                value, calls, reason = await self.invoke(text, {'text': text, 'challenge': False})
                self.assertIsNone(value)
                self.assertEqual(calls, 0)
                self.assertTrue(reason)

    async def test_captcha_or_access_restriction_stops(self):
        for text in ('安全验证', '访问受限', '验证码', 'verify you are human'):
            with self.subTest(text=text):
                value, calls, _ = await self.invoke(text, {'text': text, 'challenge': False})
                self.assertIsNone(value)
                self.assertEqual(calls, 0)

    async def test_visual_challenge_without_text_stops(self):
        value, calls, reason = await self.invoke('公开内容', {'text': '公开内容', 'challenge': True})
        self.assertIsNone(value)
        self.assertEqual(calls, 0)
        self.assertTrue(reason)

    async def test_observation_failure_is_not_permission_to_continue(self):
        value, calls, reason = await self.invoke('公开内容', error=RuntimeError('unavailable'))
        self.assertIsNone(value)
        self.assertEqual(calls, 0)
        self.assertTrue(reason)

    async def test_invalid_observation_stops(self):
        for bad in (None, {}, {'text': '', 'challenge': 'false'}, {'text': 42, 'challenge': False}):
            with self.subTest(value=bad):
                value, calls, reason = await self.invoke('公开内容', bad)
                self.assertIsNone(value)
                self.assertEqual(calls, 0)
                self.assertTrue(reason)

    async def test_blank_page_can_navigate(self):
        value, calls, _ = await self.invoke('', {'text': '', 'challenge': False})
        self.assertEqual(value, 'read-public-content')
        self.assertEqual(calls, 1)


if __name__ == '__main__':
    unittest.main()
