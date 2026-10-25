"""Preflight checks must fail closed before a companion launch."""
from __future__ import annotations

import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/bili_activity"))
import preflight


class PreflightTests(unittest.TestCase):
    def test_port_reports_listener_and_honours_allow(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            self.assertFalse(preflight.check_port(port)[0])
            self.assertTrue(preflight.check_port(port, allow_in_use=True)[0])

    def test_missing_adb_fails(self):
        passed, detail = preflight.check_adb("/definitely/missing/adb")
        self.assertFalse(passed)
        self.assertIn("not found", detail)

    def test_explicit_ffmpeg_dir_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "ffmpeg.exe"
            binary.write_bytes(b"stub")
            completed = subprocess.CompletedProcess([str(binary), "-version"], 0, "ffmpeg", "")
            with patch.object(preflight.subprocess, "run", return_value=completed):
                passed, detail = preflight.check_ffmpeg(folder)
        self.assertTrue(passed)
        self.assertEqual(detail, str(binary))
