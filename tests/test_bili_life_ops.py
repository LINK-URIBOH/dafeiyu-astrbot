"""v0.2 CLI regressions against real SQLite state; no production services used."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin/astrbot_plugin_bili_activity"
PACKAGE = "bili_life_ops_test"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(PLUGIN)]
sys.modules[PACKAGE] = package


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ops = load("bili_life_ops_cli", ROOT / "deploy/bili_activity/ops.py")
core = load(PACKAGE + ".core", PLUGIN / "core.py")
budget = load(PACKAGE + ".budget", PLUGIN / "budget.py")
SCOPE = "qq:FriendMessage:12345"
OTHER = "qq:FriendMessage:98765"


class LifeOpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "state"

    def tearDown(self):
        self.temp.cleanup()

    def run_ops(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = ops.main(["--data-dir", str(self.folder), *args])
        self.assertEqual(code, 0)
        return output.getvalue()

    def config(self, **changes):
        self.folder.mkdir(exist_ok=True)
        value = ops.DEFAULTS | {"owner_scope": SCOPE, "owner_id": "12345", "dnd_ranges": []} | changes
        path = self.folder / "control.json"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def legacy(self):
        self.config()
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.executescript("""
            CREATE TABLE runs(id TEXT,status TEXT,scope TEXT,started REAL,ended REAL);
            CREATE TABLE proposals(id TEXT,action TEXT,status TEXT,created REAL,expires REAL);
            CREATE TABLE deliveries(id TEXT,kind TEXT,status TEXT,created REAL,receipt TEXT);
            INSERT INTO runs VALUES('old','completed','qq:FriendMessage:12345',1,2);
            """)

    def test_missing_state_is_read_only_and_defaults_stay_disabled(self):
        result = json.loads(self.run_ops("status"))
        self.assertFalse(result["control"]["life_enabled"])
        self.assertFalse(result["control"]["enabled"])
        self.assertFalse(result["control"]["periodic_enabled"])
        self.assertEqual(result["goals"], [])
        self.assertEqual(json.loads(self.run_ops("episodes")), [])
        self.assertEqual(json.loads(self.run_ops("goals")), [])
        self.assertFalse(self.folder.exists())

    def test_legacy_status_does_not_migrate_or_rewrite_config(self):
        self.legacy()
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        result = json.loads(self.run_ops("status"))
        self.assertEqual(result["runs"][0]["id"], "old")
        self.assertEqual(result["goals"], [])
        self.assertEqual(result["episodes"], [])
        self.assertEqual(result["budget"], {"runs": [], "time_days": [], "call_days": []})
        self.run_ops("goals", "--all")
        self.run_ops("episodes", "--goal-id", "missing")
        self.assertEqual({p.name: p.read_bytes() for p in self.folder.iterdir()}, before)

    def test_new_fields_preserve_existing_schedule_pause_state_and_exact_backup(self):
        path = self.config(enabled=False, periodic_enabled=False, once_at=1234567,
                           check_minutes=30, check_jitter_minutes=0,
                           dnd_ranges=[["22:15", "07:45"]], custom={"preserve": True})
        before = path.read_bytes()
        outside = self.folder.parent / "data_v4.db"
        outside.write_bytes(b"unrelated paused cron jobs")
        self.run_ops("configure", "--daily-minutes", "12", "--max-model-calls-per-run", "8",
                     "--daily-model-calls", "24", "--daily-shares", "0",
                     "--screenshots-per-run", "0", "--chat-cooldown-seconds", "0")
        current = ops.load_control(self.folder)
        for key in ("enabled", "periodic_enabled", "once_at", "check_minutes", "check_jitter_minutes", "dnd_ranges", "custom"):
            self.assertEqual(current[key], json.loads(before)[key])
        self.assertEqual(current["daily_minutes"], 12)
        self.assertEqual(current["daily_shares"], 0)
        self.assertEqual(current["screenshots_per_run"], 0)
        self.assertEqual(current["chat_cooldown_seconds"], 0)
        backups = list((self.folder / "config_backups").glob("*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(outside.read_bytes(), b"unrelated paused cron jobs")

    def test_invalid_limits_do_not_save_or_backup(self):
        path = self.config()
        before = path.read_bytes()
        for key, (minimum, maximum) in ops.NUMERIC_LIMITS.items():
            for value in (minimum - 1, maximum + 1):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.run_ops("configure", "--" + key.replace("_", "-"), str(value))
                self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.folder / "config_backups").exists())
        self.assertFalse((self.folder / ".ops.lock").exists())

    def test_life_enable_needs_existing_acceptance_and_does_not_start_activity(self):
        path = self.config(one_shot_verified=False)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.run_ops("switch", "life_enabled", "on")
        self.assertEqual(path.read_bytes(), before)
        self.config(one_shot_verified=True)
        self.run_ops("switch", "life_enabled", "on")
        value = ops.load_control(self.folder)
        self.assertTrue(value["life_enabled"])
        self.assertFalse(value["enabled"])
        self.assertFalse(value["periodic_enabled"])
        self.assertIsNone(value["once_at"])

    def test_life_disable_is_possible_without_ready_config_and_preserves_other_switches(self):
        self.config(owner_scope="", owner_id="", dnd_ranges=None, life_enabled=True,
                    enabled=True, periodic_enabled=True, public_interactions=True)
        self.run_ops("switch", "life_enabled", "off")
        value = ops.load_control(self.folder)
        self.assertFalse(value["life_enabled"])
        self.assertTrue(value["enabled"])
        self.assertTrue(value["periodic_enabled"])
        self.assertTrue(value["public_interactions"])

    def test_invalid_optional_schema_is_not_mistaken_for_legacy_database(self):
        self.legacy()
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.execute("CREATE TABLE goals(id TEXT)")
            db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            self.run_ops("status")

    def test_corrupt_database_is_reported_instead_of_empty_status(self):
        self.config()
        (self.folder / "activity.sqlite3").write_bytes(b"not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.run_ops("status")

    def test_real_v02_state_queries_preserve_running_lease_and_isolate_scope(self):
        path = self.config(one_shot_verified=True)
        config_before = path.read_bytes()
        store = core.Store(self.folder)
        try:
            life = store.life
            own = life.create_goal(SCOPE, "研究建造机制", "昨天没看完", "继续读演示", "first")
            other = life.create_goal(OTHER, "其他人的目标", "私有", "继续", "other")
            life.claim_goal(SCOPE, own["id"], "run-1")
            episode = life.record_episode(SCOPE, kind="video", source_id="clip1", evidence={"bvid": "BV1", "cid": 1, "range": [0, 8]},
                                          interpretation={"thought": "需要看下一段"}, run_id="run-1", goal_id=own["id"])
            life.record_episode(OTHER, kind="video", source_id="clip2", evidence={"bvid": "BV2", "cid": 2}, goal_id=other["id"])
            limits = ops.load_control(self.folder)
            ledger = budget.Budget(store)
            ledger.start_run(SCOPE, "run-1", 120, limits, now=1000)
            ledger.model_call(SCOPE, "run-1", limits, now=1001)
            ledger.share(SCOPE, "run-1", "screenshot", limits, now=1002)
            before = list(store.db.iterdump())
            result = json.loads(self.run_ops("status"))
            self.assertEqual([g["id"] for g in result["goals"]], [own["id"]])
            self.assertEqual(result["goals"][0]["status"], "running")
            self.assertEqual([e["id"] for e in result["episodes"]], [episode["id"]])
            self.assertEqual(result["budget"]["time_days"][0]["reserved_or_used_seconds"], 120)
            self.assertEqual(result["budget"]["call_days"][0]["model_calls"], 1)
            self.assertEqual(result["budget"]["call_days"][0]["screenshots"], 1)
            self.assertEqual(json.loads(self.run_ops("episodes", "--goal-id", other["id"])), [])
            self.assertEqual(json.loads(self.run_ops("goals", "--limit", "1"))[0]["id"], own["id"])
            self.assertEqual(list(store.db.iterdump()), before)
            self.assertEqual(path.read_bytes(), config_before)
            self.assertFalse((self.folder / "config_backups").exists())
        finally:
            store.close()

    def test_read_commands_reject_unbounded_limits(self):
        self.config()
        for command in ("goals", "episodes"):
            for value in ("0", "101"):
                with self.subTest(command=command, value=value), self.assertRaises(ValueError):
                    self.run_ops(command, "--limit", value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
