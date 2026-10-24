"""Evidence-backed work storage regressions; no model or production services."""
from __future__ import annotations

import hashlib
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
package = types.ModuleType("bili_workshop_state_test")
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package
for name in ("core", "workshop"):
    spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, PLUGIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    globals()[name] = module

SCOPE, OTHER = "qq:FriendMessage:12345", "qq:GroupMessage:12345"


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.store = core.Store(self.folder)
        self.workshop = workshop.Workshop(self.store)
        self.goal = self.store.life.create_goal(SCOPE, "游戏研究", "好奇合作模式", "整理真实观察", "first")
        self.source = self.episode("first")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def episode(self, key, scope=SCOPE, **kwargs):
        return self.store.life.record_episode(scope, kind="video", source_id=key,
            evidence={"bvid": "BVsample", "cid": "42", "analyzed_range": [0, 15],
                      "subtitles": [{"from": 2, "to": 5, "content": "可以一起搭建房子"}]}, **kwargs)

    def create(self, **kwargs):
        return self.workshop.create(SCOPE, self.goal["id"], "合作建造笔记", "first", **kwargs)

    def body(self, source=None):
        source = source or self.source["id"]
        return f"## 资料观察\n演示字幕提到合作搭建。[E:{source}]\n\n## 我的想法\n我想试试搭房子。\n\n## 待核实\n还不知道是否支持跨平台联机。"

    def revise(self, work, **kwargs):
        values = dict(body=self.body(), source_ids=[self.source["id"]], expected_revision=work["revision"], request_key="v1")
        values.update(kwargs)
        return self.workshop.revise(SCOPE, work["id"], **values)

    def reopen(self):
        self.store.close()
        self.store = core.Store(self.folder)
        self.workshop = workshop.Workshop(self.store)

    def test_additive_migration_snapshots_old_ledger_and_keeps_main_version(self):
        backup = self.workshop.schema_backup
        self.assertTrue(backup.exists())
        with closing(sqlite3.connect(backup)) as db:
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='goals'").fetchone())
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='creative_works'").fetchone())
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.reopen()
        self.assertIsNone(self.workshop.schema_backup)
        self.assertEqual(len(list((self.folder / "schema_backups").glob("creative-*.sqlite3"))), 1)

    def test_future_workshop_schema_rejected_without_mutation(self):
        self.store.db.execute("UPDATE creative_meta SET value='99' WHERE key='version'")
        before = list(self.store.db.iterdump())
        with self.assertRaisesRegex(RuntimeError, "unsupported"):
            workshop.Workshop(self.store)
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_creation_is_scoped_one_per_goal_and_idempotent(self):
        first = self.create()
        self.assertEqual(self.create()["id"], first["id"])
        self.assertEqual(self.workshop.create(SCOPE, self.goal["id"], "另一个标题", "second")["id"], first["id"])
        self.assertEqual(first["revision"], 0)
        self.assertEqual(first["phase"], "write")
        self.assertEqual(self.workshop.list(OTHER), [])
        self.assertIsNone(self.workshop.get(OTHER, first["id"]))
        self.assertIsNone(self.workshop.get(SCOPE, "../../file"))
        with self.assertRaises(ValueError):
            self.workshop.create(OTHER, self.goal["id"], "不能跨会话", "other")
        with self.assertRaisesRegex(ValueError, "reused"):
            self.workshop.create(SCOPE, self.goal["id"], "不同内容", "first")

    def test_revision_immutable_optimistic_and_retry_safe(self):
        work = self.create()
        first = self.revise(work)
        self.assertEqual(first["revision"], 1)
        self.assertTrue(first["created_revision"])
        repeated = self.revise(work)
        self.assertFalse(repeated["created_revision"])
        self.assertEqual(first["body_hash"], repeated["body_hash"])
        with self.assertRaisesRegex(ValueError, "reused"):
            self.revise(first, body=self.body() + "\n不一样")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.revise(work, body=self.body() + "\n更新", request_key="v2")
        second = self.revise(first, body=self.body() + "\n继续核实。", request_key="v2")
        self.assertEqual(second["revision"], 2)
        self.assertEqual(self.workshop.get(SCOPE, work["id"], 1)["body"], first["body"])
        self.assertEqual(self.workshop.get(SCOPE, work["id"], 1)["head_revision"], 2)
        duplicate_content = self.revise(second, body=second["body"], request_key="v2-content-retry")
        self.assertEqual(duplicate_content["revision"], 2)
        self.assertFalse(duplicate_content["created_revision"])

    def test_restart_preserves_draft_and_resumes_only_with_new_lease(self):
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run1")
        work = self.create(run_id="run1")
        written = self.revise(work, run_id="run1")
        self.reopen()
        self.assertEqual(self.workshop.get(SCOPE, work["id"])["body_hash"], written["body_hash"])
        self.assertEqual(self.workshop.pending(SCOPE)[0]["id"], work["id"])
        with self.assertRaisesRegex(ValueError, "lease"):
            self.revise(written, request_key="v2", run_id="run1")
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run2")
        updated = self.revise(written, body=self.body() + "\n补充疑问", request_key="v2", run_id="run2")
        self.assertEqual(updated["revision"], 2)

    def test_mutations_require_same_goal_run(self):
        work = self.create()
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run1")
        for action in (
            lambda: self.create(), lambda: self.create(run_id="other"),
            lambda: self.revise(work), lambda: self.revise(work, run_id="other"),
            lambda: self.workshop.set_phase(SCOPE, work["id"], "research"),
            lambda: self.workshop.set_phase(SCOPE, work["id"], "write", "other"),
        ):
            with self.assertRaises(ValueError):
                action()
        self.assertEqual(self.revise(work, run_id="run1")["revision"], 1)

    def test_waiting_approval_blocks_writing_and_pending(self):
        work = self.create()
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run1")
        self.store.life.update_goal(SCOPE, self.goal["id"], status="waiting_approval", run_id="run1")
        self.assertEqual(self.workshop.pending(SCOPE), [])
        with self.assertRaises(ValueError):
            self.revise(work)
        with self.assertRaises(ValueError):
            self.workshop.set_phase(SCOPE, work["id"], "write")

    def test_pending_filters_goals_before_limit_and_excludes_research(self):
        work = self.create()
        self.assertEqual(self.workshop.pending(SCOPE, 1)[0]["id"], work["id"])
        self.workshop.set_phase(SCOPE, work["id"], "research")
        self.assertEqual(self.workshop.pending(SCOPE), [])
        self.workshop.set_phase(SCOPE, work["id"], "write")
        self.store.life.update_goal(SCOPE, self.goal["id"], status="cancelled")
        goal = self.store.life.create_goal(SCOPE, "还没做完", "继续写", "写初稿", "another")
        next_work = self.workshop.create(SCOPE, goal["id"], "下一篇", "next")
        self.assertEqual(self.workshop.pending(SCOPE, 1)[0]["id"], next_work["id"])

    def test_valid_document_checks_sources_and_hash_not_semantic_truth(self):
        work = self.revise(self.create())
        checked = self.workshop.check(SCOPE, work["id"])
        self.assertTrue(checked["passed"])
        self.assertEqual(checked["body_hash"], hashlib.sha256(work["body"].encode()).hexdigest())
        self.assertIn("not proof", checked["meaning"])
        self.assertEqual(checked["sources"][0]["bvid"], "BVsample")
        self.assertEqual(checked["sources"][0]["analyzed_range"], [0, 15])
        self.assertEqual(self.workshop.get(SCOPE, work["id"])["status"], "ready")

    def test_bad_format_is_saved_but_cannot_export(self):
        work = self.revise(self.create(), body="我写了草稿，还没有来源标记和分节")
        self.assertEqual(work["status"], "draft")
        self.assertFalse(work["validation"]["passed"])
        self.assertIn("草稿", self.workshop.get(SCOPE, work["id"])["body"])
        with self.assertRaisesRegex(ValueError, "pass fresh"):
            self.workshop.export(SCOPE, work["id"])
        self.assertFalse((self.folder / "works").exists())

    def test_citations_must_match_declared_sources_and_observation_section(self):
        work = self.create()
        bodies = [self.body().replace("[E:", "[E:invalid"),
                  self.body().replace("资料观察", "我的想法"),
                  self.body().replace(f"[E:{self.source['id']}]", "") + f"\n[E:{self.source['id']}]",
                  self.body() + "\n[E:" + "a" * 32 + "]"]
        for index, body in enumerate(bodies):
            work = self.revise(work, body=body, request_key=f"bad{index}")
            self.assertFalse(work["validation"]["passed"])

    def test_sources_need_same_scope_observed_content_not_lifecycle_or_empty_video(self):
        work = self.create()
        foreign = self.episode("foreign", scope=OTHER)
        lifecycle = self.store.life.record_episode(SCOPE, kind="run_end", source_id="end", evidence={"status": "done"})
        empty = self.store.life.record_episode(SCOPE, kind="video", source_id="empty", evidence={"bvid": "BVempty", "range": [0, 5]})
        empty_read = self.store.life.record_episode(SCOPE, kind="read", source_id="empty-read", evidence={"operation": "comments", "result_excerpt": "[]"})
        for source in (foreign["id"], lifecycle["id"], empty["id"], empty_read["id"], "a" * 32):
            with self.assertRaises(ValueError):
                self.revise(work, source_ids=[source], body=self.body(source))
        self.assertEqual(self.workshop.get(SCOPE, work["id"])["revision"], 0)

    def test_real_comment_read_is_a_citable_source(self):
        source = self.store.life.record_episode(SCOPE, kind="read", source_id="comments", evidence={
            "operation": "comments", "result_excerpt": '{"rpid":42,"message":"可以联机吗"}'})
        work = self.revise(self.create(), source_ids=[source["id"]], body=self.body(source["id"]))
        self.assertTrue(work["validation"]["passed"])

    def test_source_correction_invalidates_cached_ready_work_and_export(self):
        work = self.revise(self.create())
        self.episode("correction", supersedes_id=self.source["id"])
        checked = self.workshop.check(SCOPE, work["id"])
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["sources"], [])
        self.assertEqual(self.workshop.get(SCOPE, work["id"])["status"], "draft")
        with self.assertRaises(ValueError):
            self.workshop.export(SCOPE, work["id"])
        with self.assertRaises(ValueError):
            self.revise(work)

    def test_check_old_version_does_not_overwrite_current_head_status(self):
        first = self.revise(self.create())
        second = self.revise(first, body="还没写完", request_key="v2")
        self.assertTrue(self.workshop.check(SCOPE, first["id"], 1)["passed"])
        self.assertEqual(self.workshop.get(SCOPE, second["id"])["status"], "draft")

    def test_checks_can_run_inside_goal_completion_transaction(self):
        work = self.revise(self.create())
        with self.store.transaction():
            existing = workshop.Workshop(self.store)
            self.assertTrue(existing.check(SCOPE, work["id"])["passed"])

    def test_export_is_actual_managed_file_with_stable_hash_and_sources(self):
        work = self.revise(self.create())
        exported = self.workshop.export(SCOPE, work["id"])
        expected = self.folder / "works" / work["id"] / "r1.md"
        self.assertEqual(Path(exported["path"]), expected)
        content = expected.read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), exported["sha256"])
        self.assertIn(self.source["id"], content.decode())
        self.assertIn("BVsample", content.decode())
        repeated = self.workshop.export(SCOPE, work["id"])
        self.assertEqual(repeated, exported)
        with self.assertRaises(ValueError):
            self.workshop.export(OTHER, work["id"])

    def test_export_rejects_directory_symlinks_and_never_writes_outside(self):
        work = self.revise(self.create())
        outside = self.folder / "outside"
        outside.mkdir()
        (self.folder / "works").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.workshop.export(SCOPE, work["id"])
        self.assertEqual(list(outside.iterdir()), [])
        (self.folder / "works").unlink()
        (self.folder / "works").mkdir()
        (self.folder / "works" / work["id"]).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.workshop.export(SCOPE, work["id"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_export_rejects_target_symlink(self):
        work = self.revise(self.create())
        directory = self.folder / "works" / work["id"]
        directory.mkdir(parents=True)
        target = self.folder / "untouched.md"
        target.write_text("keep")
        (directory / "r1.md").symlink_to(target)
        with self.assertRaises(ValueError):
            self.workshop.export(SCOPE, work["id"])
        self.assertEqual(target.read_text(), "keep")

    def test_payload_limits_and_argument_types(self):
        work = self.create()
        for kwargs in (dict(body="x" * 12001), dict(source_ids=[self.source["id"]] * 2),
                       dict(source_ids="not-list"), dict(expected_revision=True),
                       dict(max_chars=20001), dict(request_key="")):
            with self.assertRaises(ValueError):
                self.revise(work, **kwargs)
        self.assertEqual(self.workshop.get(SCOPE, work["id"])["revision"], 0)

    def test_empty_work_cannot_pass_check(self):
        work = self.create()
        result = self.workshop.check(SCOPE, work["id"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["revision"], 0)

    def test_background_revision_quota_is_durable_and_retries_are_free(self):
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run1")
        work = self.create(run_id="run1")
        first = self.revise(work, run_id="run1", max_revisions=1)
        self.assertFalse(self.revise(work, run_id="run1", max_revisions=1)["created_revision"])
        self.assertFalse(self.revise(first, run_id="run1", request_key="same", max_revisions=1)["created_revision"])
        with self.assertRaises(workshop.BudgetExceeded):
            self.revise(first, body=self.body() + "\n另一版", request_key="v2", run_id="run1", max_revisions=1)
        self.reopen()
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run1")
        with self.assertRaises(workshop.BudgetExceeded):
            self.revise(first, body=self.body() + "\n另一版", request_key="v2", run_id="run1", max_revisions=1)
        self.store.life.pause_run(SCOPE, "run1", "done")
        self.store.life.claim_goal(SCOPE, self.goal["id"], "run2")
        second = self.revise(first, body=self.body() + "\n另一版", request_key="v2", run_id="run2", max_revisions=1)
        self.assertEqual(second["revision"], 2)

    def test_foreground_revision_does_not_use_background_quota(self):
        work = self.revise(self.create(), max_revisions=1)
        second = self.revise(work, body=self.body() + "\n第二版", request_key="v2", max_revisions=1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM settings WHERE key LIKE 'workshop_revisions:%'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
