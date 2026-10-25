"""Research-method CLI checks: scoped historical reads never mutate the ledger."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bili_method_ops_cli", ROOT / "deploy/bili_activity/ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
SCOPE, OTHER = "qq:FriendMessage:12345", "qq:FriendMessage:98765"
OWN_ID, OTHER_ID, RETIRED_ID = "a" * 32, "b" * 32, "c" * 32
GOAL, NEXT_GOAL, OTHER_GOAL = "d" * 32, "e" * 32, "f" * 32


class MethodOpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "state"

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(ops.main(["--data-dir", str(self.folder), *args]), 0)
        return output.getvalue()

    def config(self, **changes):
        self.folder.mkdir(exist_ok=True)
        value = ops.DEFAULTS | {"owner_scope": SCOPE, "owner_id": "12345", "dnd_ranges": []} | changes
        path = self.folder / "control.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def database(self, *, methods=True):
        self.config()
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.executescript("""
            CREATE TABLE runs(id TEXT,status TEXT,scope TEXT,started REAL,ended REAL);
            CREATE TABLE proposals(id TEXT,action TEXT,status TEXT,created REAL,expires REAL);
            CREATE TABLE deliveries(id TEXT,kind TEXT,status TEXT,created REAL,receipt TEXT);
            CREATE TABLE goals(id TEXT,scope TEXT,title TEXT,why TEXT,status TEXT,next_step TEXT,run_id TEXT,updated_at REAL);
            INSERT INTO goals VALUES('running-goal','qq:FriendMessage:12345','研究','继续','running','整理','live-run',20);
            """)
            if methods:
                db.executescript("""
                CREATE TABLE method_meta(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO method_meta VALUES('version','1');
                CREATE TABLE research_methods(
                    id TEXT PRIMARY KEY,scope TEXT,title TEXT,status TEXT,revision INTEGER,
                    create_key TEXT,created_at REAL,updated_at REAL);
                CREATE TABLE method_revisions(
                    method_id TEXT,scope TEXT,revision INTEGER,work_id TEXT,work_revision INTEGER,
                    work_hash TEXT,source_goal_id TEXT,title TEXT,applies_to TEXT,steps_json TEXT,
                    limitations TEXT,request_key TEXT,created_at REAL,PRIMARY KEY(method_id,revision));
                CREATE TABLE method_attempts(
                    id TEXT PRIMARY KEY,scope TEXT,method_id TEXT,revision INTEGER,goal_id TEXT,run_id TEXT,
                    started_at REAL,baseline_work_id TEXT,baseline_revision INTEGER,baseline_hash TEXT,
                    baseline_sources_json TEXT,status TEXT,result_work_id TEXT,result_revision INTEGER,
                    result_hash TEXT,summary TEXT,finished_at REAL,UNIQUE(scope,goal_id));
                """)
                db.executemany("INSERT INTO research_methods VALUES(?,?,?,?,?,?,?,?)", [
                    (OWN_ID, SCOPE, "比较游戏资料", "active", 2, "own", 10, 40),
                    (OTHER_ID, OTHER, "他人私聊的方法", "active", 1, "other", 10, 50),
                    (RETIRED_ID, SCOPE, "已停用方法", "retired", 1, "retired", 10, 20),
                ])
                db.executemany("INSERT INTO method_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                    (OWN_ID, SCOPE, 1, "work-one", 1, "hash-one", "source-goal", "初版方法", "游戏机制", '[{"kind":"gather","instruction":"找实机资料"}]', "不能推断未读内容", "v1", 11),
                    (OWN_ID, SCOPE, 2, "work-two", 2, "hash-two", "source-goal", "比较游戏资料", "两款游戏的同类机制", '[{"kind":"compare","instruction":"先核对相同指标"}]', "不能证明结论真实", "v2", 40),
                    (OTHER_ID, OTHER, 1, "private-work", 1, "private-hash", "other-source", "不能泄露的标题", "私人资料", '[]', "私人限制", "other-v1", 50),
                    (RETIRED_ID, SCOPE, 1, "retired-work", 1, "retired-hash", "retired-source", "已停用方法", "旧资料", '[]', "不再继续", "retired-v1", 20),
                ])
                db.executemany("INSERT INTO method_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
                    ("attempt-old", SCOPE, OWN_ID, 1, GOAL, "run-old", 12, None, 0, None, "[]", "success", "result-old", 1, "result-hash-old", "旧版记录", 13),
                    ("attempt-active", SCOPE, OWN_ID, 2, NEXT_GOAL, "live-run", 41, "baseline", 1, "baseline-hash", "[]", "active", None, None, None, "", None),
                    ("attempt-private", OTHER, OWN_ID, 2, OTHER_GOAL, "run-private", 51, None, 0, None, "[]", "success", "private-result", 1, "private-result-hash", "不能泄露的结果", 52),
                ])
            db.commit()

    def dump(self):
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            return list(db.iterdump())

    def test_missing_and_legacy_reads_do_not_initialize(self):
        self.assertEqual(json.loads(self.command("methods")), [])
        self.assertEqual(json.loads(self.command("method-attempts")), [])
        result = json.loads(self.command("status"))
        self.assertFalse(result["control"]["methods_enabled"])
        self.assertEqual(result["methods"], [])
        self.assertEqual(result["method_attempts"], [])
        self.assertFalse(self.folder.exists())
        self.database(methods=False)
        before = self.dump()
        self.assertEqual(json.loads(self.command("methods")), [])
        self.assertEqual(json.loads(self.command("method-attempts")), [])
        with self.assertRaises(ValueError):
            self.command("method", OWN_ID)
        self.assertEqual(self.dump(), before)
        self.assertFalse((self.folder / "schema_backups").exists())

    def test_opt_in_requires_life_workshop_acceptance_and_owner(self):
        base = {"life_enabled": True, "workshop_enabled": True, "one_shot_verified": True}
        failures = [{key: False} for key in base] + [{"owner_scope": ""}, {"dnd_ranges": None}]
        for changes in failures:
            with self.subTest(changes=changes):
                path = self.config(**(base | changes))
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    self.command("switch", "methods_enabled", "on")
                self.assertEqual(path.read_bytes(), before)
        self.config(**base)
        self.command("switch", "methods_enabled", "on")
        result = ops.load_control(self.folder)
        self.assertTrue(result["methods_enabled"])
        self.assertFalse(result["enabled"])
        self.assertFalse(result["periodic_enabled"])
        self.assertFalse(result["public_interactions"])
        self.assertFalse(result["collection_management"])
        self.assertIsNone(result["once_at"])

    def test_disable_requires_no_ready_config_and_preserves_all_other_values(self):
        path = self.config(methods_enabled=True, life_enabled=True, workshop_enabled=True,
                           enabled=True, periodic_enabled=True, public_interactions=True,
                           owner_scope="", owner_id="", dnd_ranges=None, custom={"retain": True}, once_at=12345)
        before = path.read_bytes()
        self.command("switch", "methods_enabled", "off")
        previous, current = json.loads(before), ops.load_control(self.folder)
        self.assertFalse(current.pop("methods_enabled"))
        previous.pop("methods_enabled")
        self.assertEqual(current, previous)
        backups = list((self.folder / "config_backups").glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_methods_scoped_historical_count_does_not_claim_current_validation(self):
        self.database()
        rows = json.loads(self.command("methods"))
        self.assertEqual([row["id"] for row in rows], [OWN_ID, RETIRED_ID])
        self.assertEqual(rows[0]["recorded_success_count"], 0)
        self.assertFalse(rows[0]["evidence_rechecked"])
        self.assertNotIn("success_count", rows[0])
        self.assertNotIn("label", rows[0])
        self.assertEqual(len(json.loads(self.command("methods", "--limit", "1"))), 1)

    def test_old_version_count_and_steps_are_read_without_revalidation(self):
        self.database()
        latest = json.loads(self.command("method", OWN_ID))
        self.assertEqual(latest["revision"], 2)
        self.assertEqual(latest["steps"], [{"kind": "compare", "instruction": "先核对相同指标"}])
        self.assertEqual(latest["recorded_success_count"], 0)
        self.assertFalse(latest["evidence_rechecked"])
        old = json.loads(self.command("method", OWN_ID, "--revision", "1"))
        self.assertEqual(old["head_revision"], 2)
        self.assertEqual(old["revision"], 1)
        self.assertEqual(old["title"], "初版方法")
        self.assertEqual(old["recorded_success_count"], 1)

    def test_attempt_scope_goal_filter_and_status_preserve_live_lease(self):
        self.database()
        before = self.dump()
        path = self.folder / "control.json"
        config_before = path.read_bytes()
        rows = json.loads(self.command("method-attempts"))
        self.assertEqual([row["id"] for row in rows], ["attempt-active", "attempt-old"])
        filtered = json.loads(self.command("method-attempts", "--goal-id", GOAL))
        self.assertEqual([row["id"] for row in filtered], ["attempt-old"])
        self.assertEqual(json.loads(self.command("method-attempts", "--goal-id", OTHER_GOAL)), [])
        current = json.loads(self.command("status"))
        self.assertEqual(current["method_attempts"][0]["status"], "active")
        self.assertEqual(current["method_attempts"][0]["run_id"], "live-run")
        self.assertEqual(current["methods"][0]["id"], OWN_ID)
        self.assertEqual(self.dump(), before)
        self.assertEqual(path.read_bytes(), config_before)
        self.assertFalse((self.folder / "config_backups").exists())
        self.assertFalse((self.folder / "schema_backups").exists())

    def test_missing_and_foreign_method_have_same_error(self):
        self.database()
        errors = []
        for method_id in (OTHER_ID, "9" * 32):
            with self.assertRaises(ValueError) as caught:
                self.command("method", method_id)
            errors.append(str(caught.exception))
        self.assertEqual(errors[0], errors[1])
        self.assertNotIn("不能泄露", " ".join(errors))
        with self.assertRaises(ValueError):
            self.command("method", OWN_ID, "--revision", "3")

    def test_invalid_selectors_do_not_touch_database(self):
        self.database()
        before = self.dump()
        for command in ("methods", "method-attempts"):
            for limit in ("0", "101"):
                with self.subTest(command=command, limit=limit), self.assertRaises(ValueError):
                    self.command(command, "--limit", limit)
        for value in ("../outside", "' OR 1=1 --", "z" * 32):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.command("method", value)
            with self.subTest(goal=value), self.assertRaises(ValueError):
                self.command("method-attempts", "--goal-id", value)
        for revision in ("0", "21"):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.command("method", OWN_ID, "--revision", revision)
        self.assertEqual(self.dump(), before)

    def test_partial_schema_errors_are_not_hidden_as_empty_lists(self):
        self.database()
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.execute("DROP TABLE method_revisions")
            db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            self.command("method", OWN_ID)
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.execute("ALTER TABLE method_attempts RENAME COLUMN status TO broken_status")
            db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            self.command("methods")
        with self.assertRaises(sqlite3.OperationalError):
            self.command("method-attempts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
