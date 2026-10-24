"""Learning/creation integration checks with fake model and QQ transports.

These exercise the real controller and SQLite ledger, not a deployed QQ client.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import types
import unittest
from unittest.mock import AsyncMock, Mock

import test_bili_activity as fixtures


main, core = fixtures.main, fixtures.core
SCOPE, OTHER_SCOPE, FakeEvent = fixtures.SCOPE, fixtures.OTHER_SCOPE, fixtures.FakeEvent


class WorkshopIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.PluginTests.asyncSetUp(self)
        self.config.update(life_enabled=True, workshop_enabled=True,
                           one_shot_verified=True, chat_cooldown_seconds=0)
        self.save_config()
        self.plugin.gate = main.PhoneGate()
        self.plugin.life_runs, self.plugin.run_goals = set(), {}
        self.plugin.writing_runs = set()
        self.plugin.flush_memory = AsyncMock()
        self.plugin.make_event = AsyncMock(side_effect=lambda run_id: FakeEvent(run_id=run_id))
        self.plugin.bili = Mock(side_effect=AssertionError("writing must not contact Bili or PhoneMCP"))
        self.plugin.phone = Mock(side_effect=AssertionError("writing must not contact PhoneMCP"))

    async def asyncTearDown(self):
        await fixtures.PluginTests.asyncTearDown(self)

    def save_config(self):
        self.plugin.control.write_text(json.dumps(self.config))

    @staticmethod
    def body(source, thought="合作建造看起来有意思"):
        return (f"## 资料观察\n已读取的演示提到了合作建造。[E:{source['id']}]\n"
                f"## 我的想法\n{thought}。\n## 待核实\n暂未验证网络联机人数。")

    async def seed(self):
        goal = self.plugin.store.life.create_goal(SCOPE, "整理合作建造笔记",
            "把看过的资料留成笔记", "整理证据并列出待核实问题", "workshop-goal")
        source = self.plugin.store.life.record_episode(SCOPE, kind="read", source_id="real-read",
            goal_id=goal["id"], evidence={"operation": "info", "result_excerpt":
                '{"bvid":"BVexample","cid":1,"description":"合作建造演示"}'})
        work = json.loads(await self.plugin.workshop(FakeEvent(), "create", goal_id=goal["id"], title="合作建造研究笔记"))
        return goal, source, work

    async def write(self, work, source, event=None, thought="合作建造看起来有意思"):
        return json.loads(await self.plugin.workshop(event or FakeEvent(), "revise", work_id=work["id"],
            body=self.body(source, thought), source_ids=json.dumps([source["id"]]),
            expected_revision=work["revision"]))

    def begin(self, goal, run_id="write-run"):
        self.plugin.activity_budget().start_run(SCOPE, run_id, 600, self.config)
        self.plugin.life_runs.add(run_id)
        self.plugin.writing_runs.add(run_id)
        self.plugin.run_videos[run_id] = set()
        self.plugin.store.life.claim_goal(SCOPE, goal["id"], run_id)
        self.plugin.run_goals[run_id] = goal["id"]
        return FakeEvent(run_id=run_id)

    async def test_writer_works_while_phone_is_busy_and_continues_after_restart(self):
        goal, source, work = await self.seed()
        work = await self.write(work, source)
        seen = []

        async def agent(event, prompt, tools, max_steps):
            seen.append(event.get_extra("df_run_id"))
            self.assertEqual(self.plugin.active_goal(event)["id"], goal["id"])
            self.assertEqual(tools, main.LIFE_TOOLS | main.WORKSHOP_TOOLS | {"df_share_thought"})
            current = json.loads(await self.plugin.workshop(event, "read", work_id=work["id"]))
            self.assertEqual(current["revision"], len(seen))
            await self.write(current, source, event, f"第{len(seen)}次整理，区分演示和推测")
            checked = json.loads(await self.plugin.workshop(event, "check", work_id=work["id"]))
            self.assertTrue(checked["passed"])
            if len(seen) == 2:
                await self.plugin.goal(event, "update", goal_id=goal["id"], status="completed")
            return "已保存研究笔记，联机人数仍待核实。"

        self.plugin.agent = agent
        # A foreground phone lease remains held through the complete writing run.
        async with self.plugin.gate.lease("foreground-chat"):
            await asyncio.wait_for(self.plugin.run_activity("once"), 2)
            self.assertEqual(self.plugin.gate.owner, "foreground-chat")
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["status"], "paused")
        self.plugin.store.close()
        self.plugin.store = core.Store(self.plugin.folder)
        self.plugin.budget = main.Budget(self.plugin.store)
        await asyncio.wait_for(self.plugin.run_activity("periodic"), 2)
        self.assertEqual(len(seen), 2)
        self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["revision"], 3)
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["status"], "completed")
        self.assertEqual([r[0] for r in self.plugin.store.db.execute("SELECT status FROM runs")], ["completed", "completed"])
        self.plugin.bili.assert_not_called()
        self.plugin.phone.assert_not_called()
        self.assertEqual(self.plugin.store.life.interests(SCOPE, "user"), [])
        memories = [r[0] for r in self.plugin.store.db.execute("SELECT body FROM memories WHERE scope=?", (SCOPE,))]
        self.assertTrue(any(work["id"] in body for body in memories))

    async def test_export_is_real_markdown_with_sources_and_share_has_receipt_once(self):
        goal, source, work = await self.seed()
        work = await self.write(work, source)
        exported = json.loads(await self.plugin.workshop(FakeEvent(), "export", work_id=work["id"]))
        path = Path(exported["path"])
        self.assertTrue(path.is_relative_to(self.plugin.folder / "works"))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), exported["sha256"])
        self.assertIn(source["id"], path.read_text())
        self.assertIn("合作建造研究笔记", path.read_text())
        await self.plugin.workshop(FakeEvent(), "share", work_id=work["id"], caption="把刚才的资料整理好啦～")
        await self.plugin.workshop(FakeEvent(event_id="duplicate"), "share", work_id=work["id"], caption="换一句配文也不重复投递")
        self.assertEqual(self.delivery.send.await_count, 1)
        args = self.delivery.send.await_args.args
        self.assertEqual(args[0], SCOPE)
        self.assertIn("合作建造研究笔记", args[1])
        self.assertIn("合作建造", args[1])
        self.assertNotIn(str(path), args[1])
        row = self.plugin.store.db.execute("SELECT status,receipt FROM deliveries").fetchone()
        self.assertEqual(row["status"], "sent")
        self.assertEqual(json.loads(row["receipt"])["message_id"], 101)
        self.plugin.bili.assert_not_called()

    async def test_unknown_delivery_is_recorded_and_never_retried(self):
        _, source, work = await self.seed()
        work = await self.write(work, source)
        self.delivery.send.side_effect = TimeoutError("missing response")
        with self.assertRaises(TimeoutError):
            await self.plugin.workshop(FakeEvent(), "share", work_id=work["id"])
        self.delivery.send.side_effect = None
        await self.plugin.workshop(FakeEvent(event_id="again"), "share", work_id=work["id"])
        self.assertEqual(self.delivery.send.await_count, 1)
        self.assertEqual(self.plugin.store.db.execute("SELECT status FROM deliveries").fetchone()[0], "uncertain")

    async def test_corrected_sources_block_share_export_and_completion_despite_old_read(self):
        goal, source, work = await self.seed()
        work = await self.write(work, source)
        self.assertTrue(json.loads(await self.plugin.workshop(FakeEvent(), "check", work_id=work["id"]))["passed"])
        self.plugin.store.life.record_episode(SCOPE, kind="read", source_id="corrected-read",
            supersedes_id=source["id"], goal_id=goal["id"],
            evidence={"operation": "info", "result_excerpt": '{"description":"仅单人演示"}'})
        for action in ("share", "export"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                await self.plugin.workshop(FakeEvent(), action, work_id=work["id"])
        with self.assertRaises(ValueError):
            await self.plugin.goal(FakeEvent(), "update", goal_id=goal["id"], status="completed")
        self.delivery.send.assert_not_called()
        self.assertNotEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["status"], "completed")

    async def test_latest_invalid_draft_cannot_complete_using_previous_valid_revision(self):
        goal, source, work = await self.seed()
        work = await self.write(work, source)
        await self.plugin.workshop(FakeEvent(event_id="draft"), "revise", work_id=work["id"],
            body=f"还有些想法待整理。[E:{source['id']}]", source_ids=json.dumps([source["id"]]), expected_revision=1)
        self.assertTrue(json.loads(await self.plugin.workshop(FakeEvent(), "check", work_id=work["id"], revision=1))["passed"])
        with self.assertRaises(ValueError):
            await self.plugin.goal(FakeEvent(), "update", goal_id=goal["id"], status="completed")

    async def test_revision_budget_and_identical_retry_do_not_create_extra_versions(self):
        self.config["workshop_revisions_per_run"] = 1
        self.save_config()
        goal, source, work = await self.seed()
        event = self.begin(goal)
        first = await self.write(work, source, event)
        repeated = await self.write(work, source, event)
        self.assertEqual(first["revision"], repeated["revision"])
        # Fixture imports the plugin in a temporary sys.modules sandbox; storage
        # can therefore hold a separately loaded BudgetExceeded class.
        with self.assertRaisesRegex(RuntimeError, "revision budget"):
            await self.write(first, source, event, "另一版观察")
        self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["revision"], 1)
        self.assertEqual(self.plugin.store.db.execute("SELECT count(*) FROM creative_revisions").fetchone()[0], 1)

    async def test_background_share_budget_blocks_delivery_and_keeps_work(self):
        self.config["daily_shares"] = 0
        self.save_config()
        goal, source, work = await self.seed()
        work = await self.write(work, source)
        event = self.begin(goal)
        with self.assertRaises(main.BudgetExceeded):
            await self.plugin.workshop(event, "share", work_id=work["id"])
        self.delivery.send.assert_not_called()
        self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["revision"], 1)
        # No send was attempted, so a later known allowance may send this version.
        self.config["daily_shares"] = 1
        self.save_config()
        await self.plugin.workshop(event, "share", work_id=work["id"])
        self.assertEqual(self.delivery.send.await_count, 1)

    async def test_scope_and_switches_gate_all_workshop_tools(self):
        _, source, work = await self.seed()
        work = await self.write(work, source)
        for event in (FakeEvent(scope=OTHER_SCOPE), FakeEvent(user="999")):
            with self.subTest(event=event), self.assertRaises(PermissionError):
                await self.plugin.workshop(event, "read", work_id=work["id"])
        for key in ("workshop_enabled", "life_enabled"):
            self.config[key] = False
            self.save_config()
            with self.subTest(key=key), self.assertRaises(PermissionError):
                await self.plugin.workshop(FakeEvent(), "list")
            self.config[key] = True
            self.save_config()

    async def test_disabling_workshop_mid_writer_blocks_further_model_or_mutation(self):
        goal, source, work = await self.seed()
        event = self.begin(goal)
        self.config["workshop_enabled"] = False
        self.save_config()
        with self.assertRaises(PermissionError):
            self.plugin.charge_model(event)
        with self.assertRaises(PermissionError):
            await self.write(work, source, event)
        self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["revision"], 0)

    async def test_foreground_rechecks_switch_after_waiting_for_background(self):
        _, source, work = await self.seed()

        async def preempt(reason):
            self.config["workshop_enabled"] = False
            self.save_config()

        self.plugin.pause_background = AsyncMock(side_effect=preempt)
        with self.assertRaises(PermissionError):
            await self.write(work, source)
        self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["revision"], 0)

    async def test_owner_pause_cancels_writer_and_keeps_committed_draft(self):
        goal, source, work = await self.seed()
        entered = asyncio.Event()

        async def agent(event, prompt, tools, max_steps):
            await self.write(work, source, event)
            entered.set()
            await asyncio.Event().wait()

        self.plugin.agent = agent
        self.plugin.live = asyncio.create_task(self.plugin.run_activity("once"))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await self.plugin.incoming(FakeEvent(text="暂停自主活动", event_id="pause-work"))
            self.assertTrue(self.plugin.live.cancelled())
            self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["revision"], 1)
            self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["status"], "paused")
            self.assertEqual(self.plugin.store.db.execute("SELECT status FROM runs").fetchone()[0], "cancelled")
            self.assertEqual(self.plugin.writing_runs, set())
            self.assertTrue(self.plugin.store.get_setting("life_paused:" + SCOPE))
        finally:
            self.plugin.live.cancel()
            await asyncio.gather(self.plugin.live, return_exceptions=True)

    async def test_need_sources_returns_goal_to_research_without_device_calls(self):
        goal, source, work = await self.seed()
        event = self.begin(goal)
        await self.plugin.workshop(event, "need_sources", work_id=work["id"], caption="查阅官方联机人数说明")
        self.assertEqual(self.plugin.workshop_store().get(SCOPE, work["id"])["phase"], "research")
        self.assertEqual(self.plugin.store.life.get_goal(SCOPE, goal["id"])["next_step"], "查阅官方联机人数说明")
        self.assertIsNone(self.plugin.writing_candidate(self.plugin.cfg()))
        self.plugin.bili.assert_not_called()
        self.plugin.phone.assert_not_called()

    async def test_disabled_tools_are_removed_from_foreground_toolset(self):
        self.config["workshop_enabled"] = False
        self.save_config()
        request = types.SimpleNamespace(system_prompt="", func_tool=fixtures.ToolSet([
            types.SimpleNamespace(name="df_workshop"), types.SimpleNamespace(name="df_goal")]))
        await self.plugin.guard_phone(FakeEvent(), request)
        self.assertNotIn("df_workshop", request.func_tool.names())
        self.assertIn("df_goal", request.func_tool.names())


if __name__ == "__main__":
    unittest.main()
