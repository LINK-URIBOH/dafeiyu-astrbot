"""Method reuse through the real controller and SQLite, with model/QQ substitutes.

These tests establish local behavior, not real autonomous decisions or QQ receipt.
"""
import asyncio
import json
import types
import unittest
from unittest.mock import AsyncMock, Mock

import test_bili_activity as fixtures


main, core = fixtures.main, fixtures.core
SCOPE, OTHER_SCOPE, FakeEvent = fixtures.SCOPE, fixtures.OTHER_SCOPE, fixtures.FakeEvent
STEPS = [
    {"kind": "gather", "instruction": "搜集与当前研究问题有关的实际资料"},
    {"kind": "verify", "instruction": "核对来源，区分演示、评论和自己的推测"},
    {"kind": "write", "instruction": "写下观察、想法和未解决的问题"},
]


class MethodIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.PluginTests.asyncSetUp(self)
        self.config.update(life_enabled=True, workshop_enabled=True, methods_enabled=True,
                           one_shot_verified=True, chat_cooldown_seconds=0)
        self.save_config()
        self.plugin.gate = main.PhoneGate()
        self.plugin.life_runs, self.plugin.run_goals = set(), {}
        self.plugin.writing_runs, self.plugin.method_runs = set(), set()
        self.plugin.flush_memory = AsyncMock()
        self.plugin.make_event = AsyncMock(side_effect=lambda rid: FakeEvent(run_id=rid))
        self.plugin.bili = Mock(side_effect=AssertionError("method writing must not call Bili"))
        self.plugin.phone = Mock(side_effect=AssertionError("method writing must not call PhoneMCP"))

    async def asyncTearDown(self):
        await fixtures.PluginTests.asyncTearDown(self)

    def save_config(self):
        self.plugin.control.write_text(json.dumps(self.config))

    def new_goal(self, key):
        return self.plugin.store.life.create_goal(SCOPE, f"整理{key}研究笔记", "保存实际研究结果",
                                                  "查资料、核对来源并写出待核实问题", key)

    def source(self, goal, key, run_id=None, supersedes_id=None):
        return self.plugin.store.life.record_episode(SCOPE, kind="read", source_id="read-" + key,
            goal_id=goal["id"], run_id=run_id, supersedes_id=supersedes_id,
            evidence={"operation": "info", "result_excerpt": json.dumps({
                "bvid": "BV" + key, "cid": len(key) + 1, "description": key + "的实际演示资料"})})

    @staticmethod
    def body(source, thought="先把观察与推测分开"):
        return (f"## 资料观察\n已读到研究资料。[E:{source['id']}]\n"
                f"## 我的想法\n{thought}。\n## 待核实\n资料中的结论仍需要独立核实。")

    async def origin(self):
        goal = self.new_goal("origin")
        source = self.source(goal, "origin")
        workshop = self.plugin.workshop_store()
        work = workshop.create(SCOPE, goal["id"], "初次研究笔记", "origin")
        work = workshop.revise(SCOPE, work["id"], self.body(source), [source["id"]], 0, "origin-v1")
        self.plugin.store.life.claim_goal(SCOPE, goal["id"], "seed-run")
        self.plugin.store.life.update_goal(SCOPE, goal["id"], status="completed", run_id="seed-run")
        method = json.loads(await self.plugin.method(FakeEvent(), "create", work_id=work["id"],
            title="有来源的研究笔记", applies_to="整理已读取的游戏或视频资料", steps=json.dumps(STEPS),
            limitations="只核对来源和结构，不证明推测正确"))
        return goal, source, work, method

    def begin(self, goal, run_id="method-run"):
        self.plugin.activity_budget().start_run(SCOPE, run_id, 600, self.config)
        self.plugin.life_runs.add(run_id)
        self.plugin.writing_runs.add(run_id)
        self.plugin.run_videos[run_id] = set()
        self.plugin.store.life.claim_goal(SCOPE, goal["id"], run_id)
        self.plugin.run_goals[run_id] = goal["id"]
        return FakeEvent(run_id=run_id)

    async def target_work(self, event, goal, key="target", work=None):
        source = self.source(goal, key, event.get_extra("df_run_id"))
        if work is None:
            work = json.loads(await self.plugin.workshop(event, "create", title=f"{key}研究结果"))
        work = json.loads(await self.plugin.workshop(event, "revise", work_id=work["id"],
            body=self.body(source, key + "需要与首次研究分开判断"),
            source_ids=json.dumps([source["id"]]), expected_revision=work["revision"]))
        return source, work

    def attempts(self):
        return [dict(row) for row in self.plugin.store.db.execute("SELECT * FROM method_attempts ORDER BY started_at")]

    async def test_method_create_and_revise_accept_decoded_steps(self):
        _, _, work, method = await self.origin()
        # The tool layer may decode the array; equivalent inputs stay idempotent.
        created = json.loads(await self.plugin.method(FakeEvent(), "create", work_id=work["id"],
            title=method["title"], applies_to=method["applies_to"], steps=STEPS,
            limitations=method["limitations"]))
        self.assertEqual(created["id"], method["id"])
        self.assertEqual(created["steps"], STEPS)
        revised_steps = STEPS + [{"kind": "review", "instruction": "复查待核实问题"}]
        revised = json.loads(await self.plugin.method(FakeEvent(event_id="decoded-revise"), "revise",
            method_id=method["id"], work_id=work["id"], title=method["title"],
            applies_to=method["applies_to"], steps=revised_steps, limitations=method["limitations"],
            expected_revision=1))
        saved = json.loads(await self.plugin.method(FakeEvent(), "read", method_id=method["id"]))
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(saved["steps"], revised_steps)

    async def test_method_rejects_non_array_steps_without_saving(self):
        _, _, work, method = await self.origin()
        for action in ("create", "revise"):
            for steps in (STEPS[0], json.dumps(STEPS[0]), "invalid JSON"):
                with self.subTest(action=action, steps=steps):
                    with self.assertRaisesRegex(ValueError, "steps must be a JSON array"):
                        await self.plugin.method(FakeEvent(), action, method_id=method["id"],
                            work_id=work["id"], title=method["title"], applies_to=method["applies_to"],
                            steps=steps, limitations=method["limitations"], expected_revision=1)
        self.assertEqual(self.plugin.store.db.execute("SELECT count(*) FROM research_methods").fetchone()[0], 1)
        self.assertEqual(self.plugin.store.db.execute("SELECT count(*) FROM method_revisions").fetchone()[0], 1)

    async def test_method_reuse_produces_checked_new_work_and_one_result_memory(self):
        _, _, _, method = await self.origin()
        self.assertEqual(method["success_count"], 0)
        self.assertEqual(method["label"], "candidate")
        goal = self.new_goal("target")
        event = self.begin(goal)
        attempt = json.loads(await self.plugin.method(event, "select", method_id=method["id"]))
        self.assertIn(event.get_extra("df_run_id"), self.plugin.method_runs)
        _, work = await self.target_work(event, goal)
        await self.plugin.goal(event, "update", goal_id=goal["id"], status="completed")
        self.assertEqual(self.attempts()[0]["status"], "success")
        self.assertEqual(self.attempts()[0]["result_work_id"], work["id"])
        await self.plugin.method(event, "result", attempt_id=attempt["id"], outcome="success", summary="已核对结果")
        await self.plugin.method(event, "result", attempt_id=attempt["id"], outcome="success", summary="重复唤醒")
        current = json.loads(await self.plugin.method(FakeEvent(), "read", method_id=method["id"]))
        self.assertEqual(current["success_count"], 1)
        self.assertEqual(current["label"], "reused_once")
        episodes = [json.loads(r[0]) for r in self.plugin.store.db.execute(
            "SELECT evidence_json FROM episodes WHERE scope=? AND kind='method_result'", (SCOPE,))]
        self.assertEqual(len(episodes), 1)
        self.assertIn(attempt["id"], json.dumps(episodes))
        memories = [r[0] for r in self.plugin.store.db.execute("SELECT body FROM memories WHERE scope=?", (SCOPE,))]
        self.assertEqual(sum(attempt["id"] in body for body in memories), 1)
        self.assertEqual(self.plugin.store.life.interests(SCOPE, "user"), [])
        self.plugin.phone.assert_not_called()
        self.plugin.bili.assert_not_called()
        self.delivery.send.assert_not_called()

    async def test_model_claim_without_completed_new_work_does_not_count(self):
        _, _, _, method = await self.origin()
        goal = self.new_goal("unsupported-claim")
        event = self.begin(goal)
        attempt = json.loads(await self.plugin.method(event, "select", method_id=method["id"]))
        with self.assertRaises(ValueError):
            await self.plugin.method(event, "result", attempt_id=attempt["id"], outcome="success", summary="我认为成功了")
        self.assertEqual(self.plugin.methods_store().get(SCOPE, method["id"])["success_count"], 0)
        self.assertNotEqual(self.attempts()[0]["status"], "success")

    async def test_select_requires_actual_background_goal_lease(self):
        _, _, _, method = await self.origin()
        for event in (FakeEvent(), FakeEvent(run_id="invented-run")):
            with self.subTest(run=event.get_extra("df_run_id")), self.assertRaises((ValueError, PermissionError)):
                await self.plugin.method(event, "select", method_id=method["id"])
        self.assertEqual(self.attempts(), [])

    async def test_unfinished_work_cannot_become_a_reusable_method(self):
        goal = self.new_goal("unfinished")
        source = self.source(goal, "unfinished")
        work = self.plugin.workshop_store().create(SCOPE, goal["id"], "还没有完成", "unfinished")
        self.plugin.workshop_store().revise(SCOPE, work["id"], self.body(source), [source["id"]], 0, "unfinished-v1")
        with self.assertRaises(ValueError):
            await self.plugin.method(FakeEvent(), "create", work_id=work["id"], title="不能凭草稿宣称成功",
                applies_to="类似资料", steps=json.dumps(STEPS), limitations="需要实际完成")

    async def test_scope_and_feature_switches_block_method_access(self):
        _, _, _, method = await self.origin()
        for event in (FakeEvent(scope=OTHER_SCOPE), FakeEvent(user="different-owner")):
            with self.subTest(scope=event.unified_msg_origin), self.assertRaises(PermissionError):
                await self.plugin.method(event, "read", method_id=method["id"])
        for key in ("methods_enabled", "life_enabled", "workshop_enabled"):
            self.config[key] = False
            self.save_config()
            with self.subTest(key=key), self.assertRaises(PermissionError):
                await self.plugin.method(FakeEvent(), "list")
            self.config[key] = True
            self.save_config()

    async def test_disabling_selected_method_blocks_model_and_workshop(self):
        _, _, _, method = await self.origin()
        goal = self.new_goal("disable")
        event = self.begin(goal)
        await self.plugin.method(event, "select", method_id=method["id"])
        self.config["methods_enabled"] = False
        self.save_config()
        with self.assertRaises(PermissionError):
            self.plugin.charge_model(event)
        with self.assertRaises(PermissionError):
            await self.plugin.workshop(event, "create", title="关闭后不能继续")
        self.assertIsNone(self.plugin.store.db.execute(
            "SELECT 1 FROM creative_works WHERE scope=? AND goal_id=?", (SCOPE, goal["id"])).fetchone())

    async def test_origin_source_correction_stops_selected_method_before_model(self):
        origin, source, _, method = await self.origin()
        goal = self.new_goal("correction")
        event = self.begin(goal)
        await self.plugin.method(event, "select", method_id=method["id"])
        self.source(origin, "origin-corrected", supersedes_id=source["id"])
        with self.assertRaises((PermissionError, ValueError)):
            self.plugin.charge_model(event)
        self.assertEqual(self.plugin.methods_store().get(SCOPE, method["id"])["success_count"], 0)

    async def test_retirement_stops_selected_method_without_changing_account_switches(self):
        _, _, _, method = await self.origin()
        goal = self.new_goal("retire")
        event = self.begin(goal)
        await self.plugin.method(event, "select", method_id=method["id"])
        self.plugin.methods_store().retire(SCOPE, method["id"])
        with self.assertRaises((PermissionError, ValueError)):
            self.plugin.charge_model(event)
        self.assertFalse(self.plugin.cfg()["public_interactions"])
        self.assertFalse(self.plugin.cfg()["collection_management"])
        self.plugin.bili.assert_not_called()

    async def test_foreground_mutation_rechecks_switch_after_preemption(self):
        _, _, work, _ = await self.origin()

        async def disable(reason):
            self.config["methods_enabled"] = False
            self.save_config()

        self.plugin.pause_background = AsyncMock(side_effect=disable)
        with self.assertRaises(PermissionError):
            await self.plugin.method(FakeEvent(event_id="after-preempt"), "create", work_id=work["id"],
                title="另一个提炼", applies_to="研究", steps=json.dumps(STEPS), limitations="待复用")

    async def test_writer_resumes_same_attempt_after_restart_without_extra_tools(self):
        _, _, _, method = await self.origin()
        goal = self.new_goal("continuation")
        draft = self.plugin.workshop_store().create(SCOPE, goal["id"], "续写的方法应用", "continuation")
        seen = []
        attempt_id = None

        async def agent(event, prompt, tools, max_steps):
            nonlocal attempt_id
            self.assertEqual(tools, main.LIFE_TOOLS | main.WORKSHOP_TOOLS | main.METHOD_TOOLS | {"df_share_thought"})
            self.assertIn(method["title"], prompt)
            seen.append(event.get_extra("df_run_id"))
            if len(seen) == 1:
                attempt = json.loads(await self.plugin.method(event, "select", method_id=method["id"]))
                attempt_id = attempt["id"]
            else:
                attempt = self.plugin.methods_store().active(SCOPE, goal["id"])
                self.assertEqual(attempt["id"], attempt_id)
                self.assertEqual(attempt["run_id"], event.get_extra("df_run_id"))
                self.assertIn(event.get_extra("df_run_id"), self.plugin.method_runs)
            current = self.plugin.workshop_store().get(SCOPE, draft["id"])
            await self.target_work(event, goal, "continuation-" + str(len(seen)), current)
            if len(seen) == 2:
                await self.plugin.goal(event, "update", goal_id=goal["id"], status="completed")
            return "已保存有来源的新资料笔记。"

        self.plugin.agent = agent
        async with self.plugin.gate.lease("foreground-phone"):
            await asyncio.wait_for(self.plugin.run_activity("once"), 2)
            self.assertEqual(self.plugin.gate.owner, "foreground-phone")
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.attempts()[0]["status"], "paused")
        self.plugin.store.close()
        self.plugin.store = core.Store(self.plugin.folder)
        self.plugin.budget = main.Budget(self.plugin.store)
        await asyncio.wait_for(self.plugin.run_activity("periodic"), 2)
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(self.attempts()), 1)
        self.assertEqual(self.attempts()[0]["status"], "success")
        self.assertEqual(self.plugin.methods_store().get(SCOPE, method["id"])["success_count"], 1)
        self.assertEqual(self.plugin.method_runs, set())
        self.plugin.phone.assert_not_called()
        self.plugin.bili.assert_not_called()

    async def test_method_tool_is_hidden_from_disabled_or_group_requests(self):
        for enabled, event in ((False, FakeEvent()), (True, FakeEvent(scope=OTHER_SCOPE))):
            self.config["methods_enabled"] = enabled
            self.save_config()
            request = types.SimpleNamespace(system_prompt="", func_tool=fixtures.ToolSet([
                types.SimpleNamespace(name="df_method"), types.SimpleNamespace(name="df_workshop")]))
            await self.plugin.guard_phone(event, request)
            self.assertNotIn("df_method", request.func_tool.names())

    async def test_selected_method_keeps_existing_model_budget(self):
        _, _, _, method = await self.origin()
        self.config["max_model_calls_per_run"] = 1
        self.save_config()
        goal = self.new_goal("budget")
        event = self.begin(goal)
        await self.plugin.method(event, "select", method_id=method["id"])
        self.plugin.charge_model(event)
        with self.assertRaises(main.BudgetExceeded):
            self.plugin.charge_model(event)
        self.assertNotEqual(self.attempts()[0]["status"], "success")
        self.plugin.bili.assert_not_called()

    async def test_reported_failure_is_retained_without_success_evidence(self):
        _, _, _, method = await self.origin()
        goal = self.new_goal("failed-application")
        event = self.begin(goal)
        attempt = json.loads(await self.plugin.method(event, "select", method_id=method["id"]))
        result = json.loads(await self.plugin.method(event, "result", attempt_id=attempt["id"],
            outcome="failed", summary="这次资料不足，未能产生符合要求的新作品"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.plugin.methods_store().get(SCOPE, method["id"])["success_count"], 0)
        self.assertIsNone(self.attempts()[0]["result_work_id"])
        self.assertEqual(self.plugin.store.db.execute(
            "SELECT count(*) FROM episodes WHERE kind='method_result'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
