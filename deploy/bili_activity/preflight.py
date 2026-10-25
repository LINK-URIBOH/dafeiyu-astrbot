"""Preflight for the Windows Bilibili companion.

Fails before launch instead of discovering a missing timezone, ffmpeg, ADB
device or a port conflict halfway through an activity. Read-only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def check_python():
    if sys.version_info < (3, 12):
        return False, f"Python {sys.version.split()[0]} < 3.12"
    return True, sys.version.split()[0]


def check_timezone():
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo("Asia/Shanghai")
    except Exception as exc:  # ZoneInfoNotFoundError on Windows without tzdata
        return False, f"Asia/Shanghai unavailable ({type(exc).__name__}); install tzdata"
    return True, "Asia/Shanghai"


def check_ffmpeg(ffmpeg_dir=None):
    candidates = []
    if ffmpeg_dir:
        candidates.append(Path(ffmpeg_dir) / "ffmpeg.exe")
        candidates.append(Path(ffmpeg_dir) / "ffmpeg")
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(Path(found))
    for path in candidates:
        if path.is_file():
            try:
                result = subprocess.run([str(path), "-version"], capture_output=True,
                                        text=True, timeout=10)
            except (OSError, subprocess.SubprocessError) as exc:
                return False, f"{path} failed ({type(exc).__name__})"
            if result.returncode == 0:
                return True, str(path)
    return False, "ffmpeg not found; put it in D:\\AI\\BiliActivity\\bin or add to PATH"


def check_adb(adb, device="emulator-5554"):
    path = Path(adb)
    if not path.is_file():
        return False, f"adb not found: {adb}"
    try:
        result = subprocess.run([str(path), "-s", device, "get-state"],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"adb failed ({type(exc).__name__})"
    if result.returncode != 0 or result.stdout.strip() != "device":
        return False, f"{device} is not online"
    return True, f"{device} online"


def check_port(port, allow_in_use=False):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            if allow_in_use:
                return True, f"127.0.0.1:{port} already in use (assuming this service)"
            return False, (f"127.0.0.1:{port} is already in use by another process; "
                           "choose another port or stop it")
    return True, f"127.0.0.1:{port} free"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=r"D:\leidian\LDPlayer14\adb.exe")
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--ffmpeg-dir", default=r"D:\AI\BiliActivity\bin")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--allow-port-in-use", action="store_true",
                        help="the companion may already be running")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks = {
        "python": check_python(),
        "timezone": check_timezone(),
        "ffmpeg": check_ffmpeg(args.ffmpeg_dir),
        "adb": check_adb(args.adb, args.device),
        "port": check_port(args.port, args.allow_port_in_use),
    }
    ok = all(result[0] for result in checks.values())
    if args.json:
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        for name, (passed, detail) in checks.items():
            print(f"[{'OK' if passed else 'FAIL'}] {name}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
