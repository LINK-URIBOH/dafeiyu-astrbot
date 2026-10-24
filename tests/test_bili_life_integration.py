"""Exercise real plugin methods with local transport/model substitutes.

These tests do not assert live QQ delivery or a production deployment.
"""
import asyncio
import base64
import json
import types
import unittest
from unittest.mock import AsyncMock, patch

import test_bili_activity as fixtures

main, core = fixtures.main, fixtures.core
SCOPE, OTHER_SCOPE, FakeEvent = fixtures.SCOPE, fixtures.OTHER_SCOPE, fixtures.FakeEvent


class LifeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.PluginTests.asyncSetUp(self)
        self.config.update(life_enabled=True, one_shot_verified=True, chat_cooldown_seconds=0,
                           collection_management=True)
        self.save_config()
        self.plugin.gate = main.PhoneGate()
        self.plugin.life_runs, self.plugin.run_goals = set(), {}
        self.plugin.flush_memory = AsyncMock()
        self.calls = []

        async def json_call(name, args):
            self.calls.append((name, args))
            if name == "bili_phone":
                return {"online": True}
            if name == "bili_prepare_video":
                return {"identity": {"bvid": args["bvid"], "cid": args["cid"]}, "range": [0, 20],
                        "subtitles": [{"from": 0, "to": 20, "content": "合作建造演示"}],
                        "frames": [], "audios": []}
            if name == "bili_preview":
                return {"ok": True, "args": args["args"], "target": {"title": "演示"}}
            if name == "bili_execute":
                return {"verified": True}
            if name == "bili_read":
                return {"identity": {"bvid": "BVexample", "cid": 1}, "items": ["实机演示"]}
            raise AssertionError(name)

        async def call(name, args):
            self.calls.append((name, args))
            return types.SimpleNamespace(isError=False, structuredContent={
                "online": True, "identity_verified": False, "reason": "bilibili_not_focused"})

        self.backend = types.SimpleNamespace(json_call=AsyncMock(side_effect=json_call), call=AsyncMock(side_effect=call))
        self.plugin.bili = lambda *args: self.backend
        self.plugin.face_plugin = lambda: None

    async def asyncTearDown(self):
        await fixtures.PluginTests.asyncTearDown(self)

    def save_config(self):
        self.plugin.control.write_text(json.dumps(self.config))

    def begin(self, run_id="run"):
        self.plugin.activity_budget().start_run(SCOPE, run_id, 600, self.config)
        self.plugin.life_runs.add(run_id)
        self.plugin.run_videos[run_id] = set()
        return FakeEvent(run_id=run_id)

    async def create(self, event):
        return json.loads(await self.plugin.goal(event, "create", title="研究建造玩法",
                                                why="想弄清合作机制", next_step="看实机演示"))

    async def watched(self, event):
        await self.plugin.watch(event, "BVexample", "1", 0, 20)
        return json.loads(await self.plugin.activity_note(event, "BVexample", "1", 20, "想再查合作机制"))

    async def test_two_runs_keep_goal_checkpoint_interest_and_approval_once(self):
        self.plugin.make_event = AsyncMock(side_effect=lambda run_id: FakeEvent(run_id=run_id))
        captured = {}

        async def agent(event, prompt, tools, max_steps):
            self.assertIn("bilibili_not_focused", prompt)
            self.assertIn('"identity_verified":false', prompt)
            self.assertTrue(main.LIFE_TOOLS <= tools)
            captured["goal"] = await self.create(event)
            note = await self.watched(event)
            await self.plugin.interest(event, note["episode_id"], "合作建造", thought="这段配合挺有意思")
            proposal = json.loads(await self.plugin.propose(event, "follow", '{"uid":99}', "想继续看演示"))
            captured["proposal_id"] = proposal["proposal_id"]
            return "已看演示，等待主人答复是否关注。"

        self.plugin.agent = agent
        await self.plugin.run_activity("once")
        goal_id = captured["goal"]["id"]
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal_id)["status"], "waiting_approval")
        self.assertEqual(self.plugin.store.db.execute("SELECT status FROM runs").fetchone()[0], "completed")
        self.assertTrue(self.plugin.store.db.execute("SELECT 1 FROM memories WHERE id LIKE 'episode:%'").fetchone())
        await self.plugin.incoming(FakeEvent(event_id="approved", text="可以"))
        await self.plugin.incoming(FakeEvent(event_id="approved", text="可以"))
        self.assertEqual(sum(n == "bili_execute" for n, _ in self.calls), 1)
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal_id)["status"], "paused")
        self.assertEqual(self.plugin.store.life.interests(SCOPE, "user"), [])
        self.plugin.store.close()
        self.plugin.store = core.Store(self.plugin.folder)
        self.plugin.budget = main.Budget(self.plugin.store)
        event = self.begin("second-run")
        resumed = json.loads(await self.plugin.goal(event, "select", goal_id=goal_id, why="继续查昨天的问题"))
        self.assertEqual(resumed["checkpoint"]["position"], 20)
        self.assertEqual(resumed["next_step"], "看实机演示")
        self.assertEqual(len(self.plugin.store.life.interests(SCOPE)), 1)
        self.assertIn("合作建造", await self.plugin.recall(event, "合作建造"))
        self.assertEqual(sum(n == "bili_execute" for n, _ in self.calls), 1)

    async def test_known_disabled_write_frees_slot_and_says_not_executed(self):
        event = FakeEvent(event_id="proposal")
        await self.plugin.propose(event, "follow", '{"uid":99}', "想关注")
        self.config["collection_management"] = False
        self.save_config()
        answer = FakeEvent(event_id="answer", text="可以")
        await self.plugin.incoming(answer)
        self.assertEqual(self.plugin.store.db.execute("SELECT status FROM proposals").fetchone()[0], "blocked")
        self.assertEqual(sum(n == "bili_execute" for n, _ in self.calls), 0)
        self.assertIn("没有执行", answer.send.await_args.args[0])
        self.config["collection_management"] = True
        self.save_config()
        await self.plugin.propose(FakeEvent(event_id="new-proposal"), "follow", '{"uid":100}', "新提议")
        self.assertEqual(self.plugin.store.db.execute("SELECT count(*) FROM proposals").fetchone()[0], 2)

    async def test_preemption_failure_does_not_claim_approval(self):
        await self.plugin.propose(FakeEvent(), "follow", '{"uid":99}', "想关注")
        self.plugin.pause_background = AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):
            await self.plugin.incoming(FakeEvent(event_id="answer", text="可以"))
        self.assertEqual(self.plugin.store.db.execute("SELECT status FROM proposals").fetchone()[0], "offered")
        self.assertEqual(sum(n == "bili_execute" for n, _ in self.calls), 0)

    async def test_operation_switch_is_reread_after_awaiting_preemption(self):
        await self.plugin.propose(FakeEvent(), "follow", '{"uid":99}', "想关注")

        async def switch_off(reason):
            self.config["collection_management"] = False
            self.save_config()

        self.plugin.pause_background = switch_off
        await self.plugin.incoming(FakeEvent(event_id="answer", text="可以"))
        self.assertEqual(sum(n == "bili_execute" for n, _ in self.calls), 0)
        self.assertEqual(self.plugin.store.db.execute("SELECT status FROM proposals").fetchone()[0], "blocked")

    async def test_expired_offer_releases_goal_without_executing(self):
        event = self.begin()
        goal = await self.create(event)
        await self.plugin.propose(event, "follow", '{"uid":99}', "想关注")
        self.plugin.store.db.execute("UPDATE proposals SET expires=0")
        await self.plugin.goal(event, "list")
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["status"], "paused")
        self.assertEqual(sum(n == "bili_execute" for n, _ in self.calls), 0)

    async def test_foreground_explicit_preference_and_scope_are_separate(self):
        await self.plugin.incoming(FakeEvent(text="我喜欢合作建造", event_id="preference"))
        await self.plugin.incoming(FakeEvent(text="我喜欢合作建造", event_id="preference"))
        self.assertEqual(len(self.plugin.store.life.interests(SCOPE, "user")), 1)
        self.assertEqual(self.plugin.store.life.interests(SCOPE), [])
        await self.plugin.incoming(FakeEvent(scope=OTHER_SCOPE, text="我喜欢别的话题", event_id="other"))
        self.assertEqual(self.plugin.store.life.interests(OTHER_SCOPE, "user"), [])
        with self.assertRaises(PermissionError):
            await self.plugin.recall(FakeEvent(scope=OTHER_SCOPE))

    async def test_unselected_goal_blocks_reads_before_network(self):
        event = self.begin()
        with self.assertRaises(ValueError):
            await self.plugin.read(event, "home")
        self.assertEqual(self.calls, [])

    async def test_empty_observation_cannot_create_interest(self):
        event = self.begin()
        await self.create(event)
        episode = self.plugin.record_video(event, {"bvid": "BVempty", "cid": 1, "observations": [], "subtitles": []})
        with self.assertRaises(ValueError):
            await self.plugin.interest(event, episode["id"], "游戏")

    async def test_media_calls_share_budget_and_keep_partial_evidence(self):
        self.config["max_model_calls_per_run"] = 1
        self.save_config()
        event = self.begin()
        await self.create(event)
        self.backend.json_call.side_effect = None
        self.backend.json_call.return_value = {
            "identity": {"bvid": "BVexample", "cid": 1}, "range": [0, 20],
            "subtitles": [{"from": 0, "to": 20, "content": "已读取字幕"}],
            "frames": [{"at": i, "data": base64.b64encode(b"image").decode()} for i in range(5)]}
        face = types.SimpleNamespace(_vl_describe=AsyncMock(return_value="第一批真实画面"), _asr_file=AsyncMock())
        self.plugin.face_plugin = lambda: face
        with self.assertRaises(main.BudgetExceeded):
            await self.plugin.watch(event, "BVexample", "1", 0, 20)
        self.assertEqual(face._vl_describe.await_count, 1)
        self.assertEqual(len(self.plugin.store.history(SCOPE)[0]["observations"]), 1)
        self.assertIn("第一批真实画面", await self.plugin.recall(event, "第一批"))

    async def test_zero_share_budget_blocks_send_but_not_passive_screenshot(self):
        self.config["daily_shares"] = 0
        self.save_config()
        event = self.begin()
        await self.create(event)
        with self.assertRaises(main.BudgetExceeded):
            await self.plugin.share_thought(event, "这个机制挺好玩")
        self.delivery.send.assert_not_called()
        fixtures.PluginTests.snapshot(self, owner=None)
        await self.plugin.share(FakeEvent(event_id="passive"), "shot", "你要的截图", passive=True)
        self.assertEqual(self.delivery.send.await_count, 1)

    async def test_pause_cancels_run_preserves_goal_and_resumes_with_cooldown(self):
        self.config["chat_cooldown_seconds"] = 300
        self.save_config()
        event = self.begin()
        goal = await self.create(event)
        entered = asyncio.Event()

        async def background():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                self.plugin.store.life.pause_run(SCOPE, "run", "cancelled")

        self.plugin.live = asyncio.create_task(background())
        await entered.wait()
        await self.plugin.incoming(FakeEvent(text="暂停自主活动"))
        self.assertTrue(self.plugin.live.done())
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["status"], "paused")
        self.assertFalse(self.plugin.life_ready(self.config))
        await self.plugin.incoming(FakeEvent(text="继续自主活动", event_id="resume"))
        self.assertFalse(self.plugin.store.get_setting("life_paused:" + SCOPE))
        self.assertFalse(self.plugin.life_ready(self.config))

    async def test_silent_run_does_not_invent_goal_or_send_message(self):
        self.plugin.make_event = AsyncMock(side_effect=lambda run_id: FakeEvent(run_id=run_id))
        self.plugin.agent = AsyncMock(return_value="暂无想做的事，安静结束。")
        await self.plugin.run_activity("once")
        self.assertEqual(self.plugin.store.life.goals(SCOPE), [])
        self.delivery.send.assert_not_called()
        self.assertEqual(self.plugin.store.db.execute("SELECT status FROM runs").fetchone()[0], "completed")
        self.assertFalse(self.plugin.life_runs)

    async def test_feature_switch_off_stops_existing_life_calls(self):
        event = self.begin()
        await self.create(event)
        self.config["life_enabled"] = False
        self.save_config()
        with self.assertRaises(PermissionError):
            await self.plugin.read(event, "home")
        with self.assertRaises(PermissionError):
            self.plugin.charge_model(event)
        self.assertEqual(self.calls, [])

    async def test_other_session_cannot_preempt_owner_activity(self):
        original = types.SimpleNamespace(name="list_devices", description="devices", active=True,
                                         parameters={"type": "object", "properties": {}},
                                         mcp_tool=types.SimpleNamespace(name="list_devices"))
        self.plugin.pause_background = AsyncMock()
        self.plugin.gate = types.SimpleNamespace(call=AsyncMock(return_value="ok"))
        self.plugin.phone = lambda: "phone"
        tool = main.GuardedPhoneTool(original, self.plugin)
        context = types.SimpleNamespace(context=types.SimpleNamespace(event=FakeEvent(scope=OTHER_SCOPE)))
        await tool.call(context)
        self.plugin.pause_background.assert_not_called()
        context.context.event = FakeEvent()
        await tool.call(context)
        self.plugin.pause_background.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
