"""Local ops/deployment regressions; these do not establish production deployment."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bili_ops", ROOT / "deploy/bili_activity/ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"

    def tearDown(self):
        self.temporary.cleanup()

    def run_ops(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return ops.main(["--data-dir", str(self.data), *args])

    def ready(self):
        self.run_ops("init")
        self.run_ops("configure", "--owner-scope", "qq:FriendMessage:12345", "--owner-id", "12345",
                     "--dnd-ranges", '[["23:00","08:00"]]')

    def evidence(self, *, status="completed", mode="autonomous", run_id="run-1", receipt=True):
        self.ready()
        with contextlib.closing(sqlite3.connect(self.data / "activity.sqlite3")) as con:
            con.executescript("""
            CREATE TABLE runs(id TEXT,status TEXT,scope TEXT,started REAL,ended REAL);
            CREATE TABLE deliveries(scope TEXT,kind TEXT,status TEXT,created REAL,receipt TEXT,meta TEXT);
            """)
            con.execute("INSERT INTO runs VALUES(?,?,?,?,?)", ("run-1", status, "qq:FriendMessage:12345", 100.0, 200.0))
            con.execute("INSERT INTO deliveries VALUES(?,?,?,?,?,?)", (
                "qq:FriendMessage:12345", "screenshot", "sent", 150.0,
                json.dumps({"message_id": "42", "verified": receipt, "image_readback": receipt}),
                json.dumps({"run_id": run_id, "share_mode": mode})))
            con.commit()
        path = self.root / "evidence.json"
        path.write_text(json.dumps({"run_id": "run-1", "read_content_verified": True,
                                   "screenshot_opened": True, "qq_screenshot_message_id": "42"}))
        return path

    def test_init_preserves_existing_user_config(self):
        self.data.mkdir()
        path = self.data / "control.json"
        original = '{"owner_scope":"custom", "custom_flag":true}\n'
        path.write_text(original)
        self.run_ops("init")
        self.assertEqual(path.read_text(), original)

    def test_once_requires_actual_owner_and_known_dnd(self):
        self.run_ops("init")
        with self.assertRaises(ValueError):
            self.run_ops("once")
        self.run_ops("configure", "--owner-scope", "qq:FriendMessage:12345", "--owner-id", "12345")
        with self.assertRaises(ValueError):
            self.run_ops("once")
        self.run_ops("configure", "--dnd-ranges", "[]")
        self.run_ops("once", "--delay-seconds", "180")
        config = ops.load_control(self.data)
        self.assertTrue(config["enabled"])
        self.assertFalse(config["periodic_enabled"])
        self.assertIsInstance(config["once_at"], float)

    def test_periodic_cannot_enable_before_evidence(self):
        self.ready()
        with self.assertRaises(ValueError):
            self.run_ops("enable-periodic")
        self.assertFalse(ops.load_control(self.data)["periodic_enabled"])

    def test_passive_screenshot_does_not_accept_autonomous_run(self):
        path = self.evidence(mode="passive")
        with self.assertRaises(ValueError):
            self.run_ops("accept-one-shot", "--evidence", str(path))

    def test_different_run_receipt_does_not_accept_run(self):
        path = self.evidence(run_id="run-2")
        with self.assertRaises(ValueError):
            self.run_ops("accept-one-shot", "--evidence", str(path))

    def test_missing_qq_readback_does_not_accept_run(self):
        path = self.evidence(receipt=False)
        with self.assertRaises(ValueError):
            self.run_ops("accept-one-shot", "--evidence", str(path))

    def test_completed_run_and_verified_receipt_allow_periodic(self):
        path = self.evidence()
        self.run_ops("accept-one-shot", "--evidence", str(path))
        self.run_ops("enable-periodic")
        self.assertTrue(ops.load_control(self.data)["periodic_enabled"])

    def test_mutation_backups_and_stop_do_not_change_cron_database(self):
        self.ready()
        untouched = self.root / "data_v4.db"
        untouched.write_bytes(b"existing paused cron state")
        self.run_ops("switch", "public_interactions", "on")
        self.run_ops("stop")
        self.assertGreaterEqual(len(list((self.data / "config_backups").glob("*.json"))), 3)
        self.assertEqual(untouched.read_bytes(), b"existing paused cron state")
        self.assertFalse(ops.load_control(self.data)["enabled"])

    def test_config_rejects_credentials_bad_dnd_or_wrong_device(self):
        for args in (("--phone-url", "http://user:password@host/Phone"),
                     ("--dnd-ranges", '[["25:00","08:00"]]'),
                     ("--device-id", "another-device")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.run_ops("configure", *args)


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "deploy"
        self.data = self.root / "astrbot/data"
        self.data.mkdir(parents=True)
        self.script = ROOT / "deploy/bili_activity/deploy.sh"

    def tearDown(self):
        self.temporary.cleanup()

    def deploy(self):
        return subprocess.run(["bash", str(self.script), str(self.root)], text=True,
                              capture_output=True, timeout=20,
                              env={**os.environ, "PYTHON": sys.executable})

    def test_deploy_preserves_config_and_archives_live_database(self):
        plugin = self.data / "plugins/astrbot_plugin_bili_activity"
        plugin.mkdir(parents=True)
        (plugin / "main.py").write_text("existing user edit")
        (plugin / "user-note.txt").write_text("keep this file")
        state = self.data / "plugin_data/astrbot_plugin_bili_activity"
        state.mkdir(parents=True)
        config = '{"enabled": false, "user_custom": true}\n'
        (state / "control.json").write_text(config)
        db = sqlite3.connect(state / "activity.sqlite3")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE evidence(note TEXT)")
        db.execute("INSERT INTO evidence VALUES('existing activity state')")
        db.commit()
        db.close()  # Windows keeps the file locked until the handle is closed.
        (self.data / "data_v4.db").write_bytes(b"paused unrelated cron jobs")
        try:
            result = self.deploy()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((state / "control.json").read_text(), config)
            self.assertEqual((plugin / "user-note.txt").read_text(), "keep this file")
            self.assertEqual((self.data / "data_v4.db").read_bytes(), b"paused unrelated cron jobs")
            archives = list((self.root / "backups").glob("*.tar.gz"))
            self.assertEqual(len(archives), 1)
            with tarfile.open(archives[0]) as archive:
                old = archive.extractfile("astrbot/data/plugins/astrbot_plugin_bili_activity/main.py").read()
                self.assertEqual(old, b"existing user edit")
                copied_db = Path(self.temporary.name) / "db-copy.sqlite3"
                copied_db.write_bytes(archive.extractfile("astrbot/data/plugin_data/astrbot_plugin_bili_activity/activity.sqlite3").read())
            with contextlib.closing(sqlite3.connect(copied_db)) as backup:
                self.assertEqual(backup.execute("SELECT note FROM evidence").fetchone()[0], "existing activity state")
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            db.close()

    def test_nested_destination_symlink_stops_before_overwrite(self):
        if os.name == "nt":
            self.skipTest("creating symlinks on Windows requires elevated privileges")
        plugin = self.data / "plugins/astrbot_plugin_bili_activity"
        plugin.mkdir(parents=True)
        victim = Path(self.temporary.name) / "outside.py"
        victim.write_text("must remain")
        (plugin / "main.py").symlink_to(victim)
        result = self.deploy()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(victim.read_text(), "must remain")
        self.assertFalse((self.root / "backups").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
