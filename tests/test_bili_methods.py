"""Research method storage checks using real scoped SQLite and work evidence."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "plugin/astrbot_plugin_bili_activity"
package = types.ModuleType("bili_method_state_test")
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package
for name in ("core", "workshop", "methods"):
    spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, PLUGIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    globals()[name] = module

SCOPE, OTHER = "qq:FriendMessage:12345", "qq:GroupMessage:12345"
STEPS = [{"kind": "gather", "instruction": "收集实际演示，记录时间范围"},
         {"kind": "review", "instruction": "把观察和推测分开，核对引用"}]


class MethodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.store = core.Store(self.folder)
        self.workshop = workshop.Workshop(self.store)
        self.library = methods.MethodLibrary(self.store)
        self.origin_goal, self.origin_source, self.origin = self.make_source("origin")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def goal(self, key, run=None):
        goal = self.store.life.create_goal(SCOPE, "研究" + key, "想理解实际机制", "核对资料", key)
        self.store.life.claim_goal(SCOPE, goal["id"], run or key)
        return goal

    def episode(self, key, goal=None, run=None, **kwargs):
        return self.store.life.record_episode(SCOPE, kind="video", source_id=key,
            evidence={"bvid": "BV" + key, "cid": "42", "analyzed_range": [0, 15],
                      "subtitles": [{"from": 1, "to": 5, "content": "合作机制" + key}]},
            goal_id=goal["id"] if goal else None, run_id=run, **kwargs)

    def body(self, source, extra=""):
        return f"## 资料观察\n已读取具体演示。[E:{source['id']}]\n## 我的想法\n值得继续研究{extra}。\n## 待核实\n还需要官方人数说明。"

    def write(self, key, goal, source, run, existing=None):
        work = existing or self.workshop.create(SCOPE, goal["id"], key + "笔记", key, run_id=run)
        return self.workshop.revise(SCOPE, work["id"], self.body(source, key), [source["id"]], work["revision"],
                                    key + str(work["revision"]), run_id=run)

    def make_source(self, key):
        goal = self.goal(key)
        source = self.episode(key, goal, key)
        work = self.write(key, goal, source, key)
        self.store.life.update_goal(SCOPE, goal["id"], status="completed", run_id=key)
        return goal, source, work

    def create(self, **kwargs):
        values = dict(work_id=self.origin["id"], title="证据分层研究法", applies_to="研究视频展示的游戏机制",
                      steps=STEPS, limitations="不能仅凭评论断言玩法真实", request_key="method")
        values.update(kwargs)
        return self.library.create(SCOPE, **values)

    def revise(self, method, **kwargs):
        values = dict(work_id=self.origin["id"], title=method["title"], applies_to=method["applies_to"],
                      steps=method["steps"], limitations=method["limitations"],
                      expected_revision=method["revision"], request_key="r" + str(method["revision"] + 1))
        values.update(kwargs)
        return self.library.revise(SCOPE, method["id"], **values)

    def attempt(self, method, key):
        goal = self.goal(key)
        return goal, self.library.select(SCOPE, method["id"], goal["id"], key)

    def success(self, method, key):
        goal, attempt = self.attempt(method, key)
        source = self.episode(key, goal, key)
        work = self.write(key, goal, source, key)
        self.store.life.update_goal(SCOPE, goal["id"], status="completed", run_id=key)
        result = self.library.result(SCOPE, attempt["id"], "success", "保存了新的有来源作品", run_id=key)
        return goal, source, work, result

    def test_migration_backup_is_additive_and_does_not_repeat(self):
        self.assertTrue(self.library.schema_backup.exists())
        with closing(sqlite3.connect(self.library.schema_backup)) as db:
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='creative_works'").fetchone())
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='research_methods'").fetchone())
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertIsNone(methods.MethodLibrary(self.store).schema_backup)
        self.assertEqual(len(list((self.folder / "schema_backups").glob("methods-*.sqlite3"))), 1)

    def test_future_schema_is_rejected_without_mutation(self):
        self.store.db.execute("UPDATE method_meta SET value='99' WHERE key='version'")
        before = list(self.store.db.iterdump())
        with self.assertRaisesRegex(RuntimeError, "unsupported"):
            methods.MethodLibrary(self.store)
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_method_starts_candidate_and_create_retry_is_idempotent(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["label"], "candidate")
        self.assertEqual(first["success_count"], 0)
        self.assertEqual(first["steps"], STEPS)
        self.assertTrue(first["source_valid"])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM method_revisions").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "reused"):
            self.create(title="different")

    def test_requires_completed_fresh_source_work(self):
        goal = self.goal("unfinished")
        source = self.episode("unfinished", goal, "unfinished")
        work = self.write("unfinished", goal, source, "unfinished")
        with self.assertRaisesRegex(ValueError, "completed"):
            self.create(work_id=work["id"])
        self.episode("corrected", supersedes_id=self.origin_source["id"])
        with self.assertRaisesRegex(ValueError, "fresh checks"):
            self.create()

    def test_steps_are_bounded_data_and_reject_executable_schema(self):
        for steps in ([], STEPS * 4, [{"kind": "shell", "instruction": "echo hi"}],
                      [{"kind": "write", "instruction": "hello", "tool": "run_command"}],
                      [{"kind": "write", "instruction": "x" * 601}]):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                self.create(steps=steps)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM research_methods").fetchone()[0], 0)

    def test_scope_is_enforced_for_methods_sources_and_attempts(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        self.assertEqual(self.library.list(OTHER), [])
        self.assertIsNone(self.library.get(OTHER, method["id"]))
        self.assertIsNone(self.library.get_attempt(OTHER, attempt["id"]))
        self.assertIsNone(self.library.get(SCOPE, "../../secret"))
        with self.assertRaises(ValueError):
            self.library.select(OTHER, method["id"], goal["id"], "target")
        with self.assertRaises(ValueError):
            self.library.result(OTHER, attempt["id"], "failed", "理由")
        with self.assertRaises(ValueError):
            self.library.create(OTHER, self.origin["id"], "方法", "适用范围", STEPS, "限制", "other")

    def test_selection_requires_real_run_lease_and_different_goal(self):
        method = self.create()
        goal = self.goal("target")
        with self.assertRaisesRegex(ValueError, "active goal"):
            self.library.select(SCOPE, method["id"], goal["id"], "wrong-run")
        with self.assertRaises(ValueError):
            self.library.select(SCOPE, method["id"], self.origin_goal["id"], "origin")
        attempt = self.library.select(SCOPE, method["id"], goal["id"], "target")
        self.assertEqual(self.library.select(SCOPE, method["id"], goal["id"], "target")["id"], attempt["id"])

    def test_success_only_counts_checked_distinct_goals_and_cannot_replay(self):
        method = self.create()
        _, _, _, first = self.success(method, "one")
        self.assertEqual(self.library.get(SCOPE, method["id"])["label"], "reused_once")
        repeated = self.library.result(SCOPE, first["id"], "success", "改文案也不新增结果", run_id="one")
        self.assertEqual(repeated["summary"], first["summary"])
        self.success(method, "two")
        updated = self.library.get(SCOPE, method["id"])
        self.assertEqual(updated["label"], "reused_multiple")
        self.assertEqual(updated["success_count"], 2)
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.library.result(SCOPE, first["id"], "failed", "改变结果", run_id="one")

    def test_success_self_report_without_new_work_is_rejected(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        self.episode("target", goal, "target")
        self.store.life.update_goal(SCOPE, goal["id"], status="completed", run_id="target")
        with self.assertRaisesRegex(ValueError, "new work revision"):
            self.library.result(SCOPE, attempt["id"], "success", "我觉得成功了", run_id="target")
        self.assertEqual(self.library.get(SCOPE, method["id"])["success_count"], 0)

    def test_baseline_work_before_selection_cannot_be_claimed_as_result(self):
        method = self.create()
        goal = self.goal("target")
        source = self.episode("target", goal, "target")
        self.write("target", goal, source, "target")
        attempt = self.library.select(SCOPE, method["id"], goal["id"], "target")
        self.assertEqual(attempt["baseline_revision"], 1)
        self.store.life.update_goal(SCOPE, goal["id"], status="completed", run_id="target")
        with self.assertRaisesRegex(ValueError, "after method selection"):
            self.library.result(SCOPE, attempt["id"], "success", "使用旧作品", run_id="target")

    def test_new_episode_id_with_identical_evidence_does_not_count(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        source = self.store.life.record_episode(SCOPE, kind="video", source_id="clone",
            evidence=self.origin_source["evidence"] | {"captured_at": 999}, goal_id=goal["id"], run_id="target")
        self.write("new wording", goal, source, "target")
        self.store.life.update_goal(SCOPE, goal["id"], status="completed", run_id="target")
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.library.result(SCOPE, attempt["id"], "success", "重新包装旧来源", run_id="target")

    def test_corrected_origin_invalidates_reuse_and_prior_valid_count(self):
        method = self.create()
        self.success(method, "first")
        self.episode("correction", supersedes_id=self.origin_source["id"])
        current = self.library.get(SCOPE, method["id"])
        self.assertFalse(current["source_valid"])
        self.assertEqual(current["recorded_success_count"], 1)
        self.assertEqual(current["success_count"], 0)
        goal = self.goal("new")
        with self.assertRaisesRegex(ValueError, "fresh checks"):
            self.library.select(SCOPE, method["id"], goal["id"], "new")

    def test_corrected_result_is_kept_as_history_but_not_valid_success(self):
        method = self.create()
        _, source, _, attempt = self.success(method, "first")
        self.episode("correction", supersedes_id=source["id"])
        current = self.library.get(SCOPE, method["id"])
        self.assertTrue(current["source_valid"])
        self.assertEqual(current["success_count"], 0)
        self.assertEqual(current["recorded_success_count"], 1)
        self.assertEqual(self.library.get_attempt(SCOPE, attempt["id"])["status"], "success")

    def test_revision_is_immutable_optimistic_and_resets_counts(self):
        method = self.create()
        self.success(method, "first")
        changed = self.revise(method, limitations="新增限制：需要官方说明")
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["success_count"], 0)
        self.assertEqual(self.library.get(SCOPE, method["id"], 1)["success_count"], 1)
        retry = self.revise(method, limitations="新增限制：需要官方说明")
        self.assertEqual(retry["revision"], 2)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.revise(method, limitations="another", request_key="new-conflict")

    def test_paused_attempt_resumes_pinned_version_preserving_baseline(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        self.library.pause_run(SCOPE, "target", "到达预算")
        self.store.life.pause_run(SCOPE, "target", "到达预算")
        changed = self.revise(method, limitations="新增限制")
        self.assertEqual(changed["revision"], 2)
        self.store.life.claim_goal(SCOPE, goal["id"], "resume")
        resumed = self.library.select(SCOPE, method["id"], goal["id"], "resume")
        self.assertEqual(resumed["id"], attempt["id"])
        self.assertEqual(resumed["revision"], 1)
        self.assertEqual(resumed["started_at"], attempt["started_at"])
        self.assertEqual(resumed["baseline_revision"], attempt["baseline_revision"])
        self.assertEqual(resumed["run_id"], "resume")

    def test_recovery_is_explicit_and_does_not_interrupt_a_live_lease(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        self.assertEqual(methods.MethodLibrary(self.store).active(SCOPE, goal["id"])["status"], "active")
        self.assertEqual(self.library.recover(), 0)
        self.store.close()
        self.store = core.Store(self.folder)
        self.workshop = workshop.Workshop(self.store)
        self.library = methods.MethodLibrary(self.store)
        self.assertEqual(self.library.active(SCOPE, goal["id"])["status"], "active")
        self.assertEqual(self.library.recover(), 1)
        self.assertEqual(self.library.active(SCOPE, goal["id"])["status"], "paused")
        self.store.life.claim_goal(SCOPE, goal["id"], "resume")
        self.assertEqual(self.library.select(SCOPE, method["id"], goal["id"], "resume")["id"], attempt["id"])

    def test_one_goal_cannot_switch_methods_to_create_more_attempts(self):
        method = self.create()
        other = self.create(title="另一个方法", request_key="second")
        goal, attempt = self.attempt(method, "target")
        with self.assertRaisesRegex(ValueError, "another method"):
            self.library.select(SCOPE, other["id"], goal["id"], "target")
        self.library.result(SCOPE, attempt["id"], "failed", "没有足够资料", run_id="target")
        with self.assertRaisesRegex(ValueError, "finished"):
            self.library.select(SCOPE, method["id"], goal["id"], "target")

    def test_retirement_prevents_resume_and_new_success(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        retired = self.library.retire(SCOPE, method["id"])
        self.assertEqual(retired["status"], "retired")
        self.assertFalse(retired["usable"])
        self.assertEqual(self.library.active(SCOPE, goal["id"])["status"], "paused")
        with self.assertRaisesRegex(ValueError, "retired"):
            self.library.select(SCOPE, method["id"], goal["id"], "target")
        with self.assertRaisesRegex(ValueError, "retired"):
            self.library.result(SCOPE, attempt["id"], "success", "不能再记成功", run_id="target")
        self.assertEqual(self.library.result(SCOPE, attempt["id"], "abandoned", "不再采用", run_id="target")["status"], "abandoned")

    def test_foreground_cannot_change_running_attempt_and_failure_is_not_success(self):
        method = self.create()
        goal, attempt = self.attempt(method, "target")
        with self.assertRaisesRegex(ValueError, "active run"):
            self.library.result(SCOPE, attempt["id"], "failed", "前台报告")
        with self.assertRaises(ValueError):
            self.library.result(SCOPE, attempt["id"], "failed", "", run_id="target")
        self.store.life.pause_run(SCOPE, "target", "前台打断")
        self.library.pause_run(SCOPE, "target", "前台打断")
        failed = self.library.result(SCOPE, attempt["id"], "failed", "只有看法，没有完成作品")
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["result_hash"])
        self.assertEqual(self.library.get(SCOPE, method["id"])["success_count"], 0)


if __name__ == "__main__":
    unittest.main()
