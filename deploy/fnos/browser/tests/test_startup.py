import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class StartupTests(unittest.IsolatedAsyncioTestCase):
    def test_launch_uses_blank_and_preserves_allowlist(self):
        with patch.object(server, 'Browser') as ctor:
            server.create_browser()
        self.assertEqual(ctor.call_args.kwargs['executable_path'], str(server.HERE / 'chromium-blank.sh'))
        self.assertEqual(ctor.call_args.kwargs['allowed_domains'], server._load_allowlist())
        self.assertNotIn('chrome://*', ctor.call_args.kwargs['allowed_domains'])

    async def test_inner_timeout_is_not_reported_as_180_seconds(self):
        with patch.object(server, '_run_task', new=AsyncMock(side_effect=TimeoutError)), \
                patch.object(server, 'monotonic', side_effect=[100.0, 138.0]):
            result = await server.browser_task('read public page')
        self.assertIn('启动', result)
        self.assertIn('38.0', result)
        self.assertNotIn('任务超时（180 秒）', result)

    async def test_overall_deadline_is_distinct(self):
        async def wait_forever(*args):
            await asyncio.Event().wait()
        with patch.object(server, '_run_task', side_effect=wait_forever), patch.object(server, 'TASK_TIMEOUT', 0.02):
            result = await server.browser_task('read public page')
        self.assertIn('整体任务', result)
        self.assertIn('启动', result)

    async def test_start_failure_cleans_up_without_running_agent(self):
        browser = SimpleNamespace(start=AsyncMock(side_effect=TimeoutError), kill=AsyncMock())
        with patch.object(server, 'Browser', return_value=browser), patch.object(server, 'ReadOnlyAgent') as ctor:
            with self.assertRaises(TimeoutError): await server._run_task('read public page', 8)
        browser.kill.assert_awaited_once()
        ctor.assert_not_called()

    async def test_phase_is_local_to_each_task(self):
        async def fail_in_phase(task, steps, progress):
            progress.phase = '模型调用' if task == 'model' else '网页读取'
            raise TimeoutError
        with patch.object(server, '_run_task', side_effect=fail_in_phase):
            a, b = await asyncio.gather(server.browser_task('model'), server.browser_task('page'))
        self.assertIn('模型调用', a)
        self.assertIn('网页读取', b)

    async def test_real_chromium_cold_and_reused_profile_start_blank(self):
        import tempfile
        import time
        with tempfile.TemporaryDirectory() as root:
            profile = Path(root)
            (profile / 'Default').mkdir()
            # Reproduce a profile configured to open Chrome's internal new tab.
            (profile / 'Default/Preferences').write_text(json.dumps({
                'session': {'restore_on_startup': 4, 'startup_urls': ['chrome://newtab/']}}))
            with patch.object(server, 'PROFILE_DIR', profile):
                for i in range(5):
                    browser = server.create_browser()
                    started = time.monotonic()
                    try:
                        await asyncio.wait_for(browser.start(), timeout=15)
                        # Agent.run calls start again: it must remain idempotent.
                        await asyncio.wait_for(browser.start(), timeout=15)
                        page = await browser.get_current_page()
                        self.assertEqual(await page.evaluate('() => location.href'), 'about:blank')
                        print(f'Start cycle {i + 1}: {time.monotonic() - started:.2f}s; about:blank')
                    finally:
                        await asyncio.wait_for(browser.kill(), timeout=10)


if __name__ == '__main__':
    unittest.main()
