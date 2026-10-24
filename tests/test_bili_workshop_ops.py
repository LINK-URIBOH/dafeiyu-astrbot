"""Read-only creative-work CLI and opt-in configuration regressions."""
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
spec = importlib.util.spec_from_file_location("bili_workshop_ops_cli", ROOT / "deploy/bili_activity/ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
SCOPE, OTHER = "qq:FriendMessage:12345", "qq:FriendMessage:98765"
OWN_ID, OTHER_ID, EMPTY_ID = "a" * 32, "b" * 32, "c" * 32


class WorkshopOpsTests(unittest.TestCase):
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

    def database(self, *, creative=True):
        self.config()
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.executescript("""
            CREATE TABLE runs(id TEXT,status TEXT,scope TEXT,started REAL,ended REAL);
            CREATE TABLE proposals(id TEXT,action TEXT,status TEXT,created REAL,expires REAL);
            CREATE TABLE deliveries(id TEXT,kind TEXT,status TEXT,created REAL,receipt TEXT);
            CREATE TABLE goals(id TEXT,scope TEXT,title TEXT,why TEXT,status TEXT,next_step TEXT,run_id TEXT,updated_at REAL);
            INSERT INTO goals VALUES('goal-own','qq:FriendMessage:12345','写笔记','要继续','running','完成草稿','live-run',20);
            """)
            if creative:
                db.executescript("""
                CREATE TABLE creative_works(
                    id TEXT PRIMARY KEY, scope TEXT, goal_id TEXT, title TEXT, phase TEXT,
                    status TEXT, revision INTEGER, create_key TEXT, created_at REAL, updated_at REAL);
                CREATE TABLE creative_revisions(
                    work_id TEXT,scope TEXT,revision INTEGER,body TEXT,source_ids_json TEXT,
                    validation_json TEXT,body_hash TEXT,request_key TEXT,created_at REAL,
                    PRIMARY KEY(work_id,revision));
                CREATE TABLE creative_meta(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO creative_meta VALUES('version','1');
                """)
                db.executemany("INSERT INTO creative_works VALUES(?,?,?,?,?,?,?,?,?,?)", [
                    (OWN_ID, SCOPE, "goal-own", "合作建造笔记", "write", "ready", 2, "own", 10, 30),
                    (OTHER_ID, OTHER, "goal-other", "另一个私聊的作品", "write", "ready", 1, "other", 10, 31),
                    (EMPTY_ID, SCOPE, "goal-empty", "待写草稿", "research", "draft", 0, "empty", 10, 15),
                ])
                db.executemany("INSERT INTO creative_revisions VALUES(?,?,?,?,?,?,?,?,?)", [
                    (OWN_ID, SCOPE, 1, "第一版正文", '["source-one"]', '{"passed":false}', "hash-v1", "v1", 11),
                    (OWN_ID, SCOPE, 2, "第二版正文", '["source-two"]', '{"passed":true}', "hash-v2", "v2", 30),
                    (OTHER_ID, OTHER, 1, "不能泄露的正文", '[]', '{"passed":true}', "secret", "other-v1", 31),
                ])
            db.commit()

    def dump(self):
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            return list(db.iterdump())

    def test_missing_and_legacy_state_reads_do_not_initialize(self):
        self.assertEqual(json.loads(self.command("works")), [])
        result = json.loads(self.command("status"))
        self.assertFalse(result["control"]["workshop_enabled"])
        self.assertEqual(result["works"], [])
        self.assertFalse(self.folder.exists())
        self.database(creative=False)
        before = self.dump()
        config = (self.folder / "control.json").read_bytes()
        self.assertEqual(json.loads(self.command("works")), [])
        self.assertEqual(json.loads(self.command("status"))["works"], [])
        with self.assertRaises(ValueError):
            self.command("work", OWN_ID)
        self.assertEqual(self.dump(), before)
        self.assertEqual((self.folder / "control.json").read_bytes(), config)
        self.assertFalse((self.folder / "schema_backups").exists())

    def test_workshop_opt_in_requires_life_acceptance_and_actual_owner(self):
        for changes in ({"life_enabled": False, "one_shot_verified": True},
                        {"life_enabled": True, "one_shot_verified": False},
                        {"life_enabled": True, "one_shot_verified": True, "owner_scope": ""},
                        {"life_enabled": True, "one_shot_verified": True, "dnd_ranges": None}):
            with self.subTest(changes=changes):
                path = self.config(**changes)
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    self.command("switch", "workshop_enabled", "on")
                self.assertEqual(path.read_bytes(), before)
        self.config(life_enabled=True, one_shot_verified=True, enabled=False, periodic_enabled=False)
        self.command("switch", "workshop_enabled", "on")
        config = ops.load_control(self.folder)
        self.assertTrue(config["workshop_enabled"])
        self.assertFalse(config["enabled"])
        self.assertFalse(config["periodic_enabled"])
        self.assertIsNone(config["once_at"])

    def test_disable_works_without_ready_config_and_preserves_other_switches(self):
        self.config(workshop_enabled=True, life_enabled=True, enabled=True, periodic_enabled=True,
                    public_interactions=True, owner_scope="", owner_id="", dnd_ranges=None)
        self.command("switch", "workshop_enabled", "off")
        current = ops.load_control(self.folder)
        self.assertFalse(current["workshop_enabled"])
        for key in ("life_enabled", "enabled", "periodic_enabled", "public_interactions"):
            self.assertTrue(current[key])

    def test_new_limits_preserve_old_config_and_exact_backup(self):
        path = self.config(check_minutes=30, check_jitter_minutes=0, once_at=12345,
                           dnd_ranges=[["23:15", "07:45"]], custom={"retain": True})
        before = path.read_bytes()
        self.command("configure", "--workshop-revisions-per-run", "2", "--workshop-max-characters", "6000")
        after = ops.load_control(self.folder)
        for key in ("check_minutes", "check_jitter_minutes", "once_at", "enabled", "periodic_enabled", "dnd_ranges", "custom"):
            self.assertEqual(after[key], json.loads(before)[key])
        self.assertEqual(after["workshop_revisions_per_run"], 2)
        self.assertEqual(after["workshop_max_characters"], 6000)
        backup = list((self.folder / "config_backups").glob("*.json"))
        self.assertEqual(len(backup), 1)
        self.assertEqual(backup[0].read_bytes(), before)

    def test_invalid_workshop_limits_do_not_save(self):
        path = self.config()
        before = path.read_bytes()
        for name, values in (("--workshop-revisions-per-run", ("0", "11")),
                             ("--workshop-max-characters", ("499", "20001"))):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.command("configure", name, value)
                self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.folder / "config_backups").exists())

    def test_work_list_and_revision_reads_are_scoped_and_do_not_recover_running_goal(self):
        self.database()
        before = self.dump()
        result = json.loads(self.command("works"))
        self.assertEqual([row["id"] for row in result], [OWN_ID, EMPTY_ID])
        self.assertEqual([row["id"] for row in json.loads(self.command("status"))["works"]], [OWN_ID, EMPTY_ID])
        latest = json.loads(self.command("work", OWN_ID))
        self.assertEqual(latest["body"], "第二版正文")
        self.assertEqual(latest["source_ids"], ["source-two"])
        self.assertTrue(latest["validation"]["passed"])
        self.assertTrue(latest["validation_is_cached"])
        first = json.loads(self.command("work", OWN_ID, "--revision", "1"))
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["head_revision"], 2)
        self.assertEqual(first["body"], "第一版正文")
        self.assertFalse(first["validation"]["passed"])
        self.assertEqual(self.dump(), before)

    def test_missing_and_other_scope_return_same_detail_error_without_content(self):
        self.database()
        errors = []
        for work_id in (OTHER_ID, "d" * 32):
            with self.assertRaises(ValueError) as exc:
                self.command("work", work_id)
            errors.append(str(exc.exception))
        self.assertEqual(errors[0], errors[1])
        self.assertNotIn("不能泄露", " ".join(errors))
        with self.assertRaises(ValueError):
            self.command("work", OWN_ID, "--revision", "99")

    def test_undrafted_work_has_no_body_and_no_validation_claim(self):
        self.database()
        result = json.loads(self.command("work", EMPTY_ID))
        self.assertEqual(result["revision"], 0)
        self.assertEqual(result["body"], "")
        self.assertEqual(result["source_ids"], [])
        self.assertIsNone(result["validation"])

    def test_invalid_selectors_and_partial_schema_fail_explicitly(self):
        self.database()
        for limit in ("0", "101"):
            with self.assertRaises(ValueError):
                self.command("works", "--limit", limit)
        for work_id in ("../outside", "' OR 1=1 --", "x" * 32):
            with self.assertRaises(ValueError):
                self.command("work", work_id)
        with self.assertRaises(ValueError):
            self.command("work", OWN_ID, "--revision", "0")
        with contextlib.closing(sqlite3.connect(self.folder / "activity.sqlite3")) as db:
            db.execute("DROP TABLE creative_revisions")
            db.commit()
        with self.assertRaises(sqlite3.OperationalError):
            self.command("work", OWN_ID)


if __name__ == "__main__":
    unittest.main(verbosity=2)
