#!/usr/bin/env python3
"""Operate only the Bilibili activity plugin; never change AstrBot cron jobs."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


DEFAULTS = {
    "enabled": False,
    "periodic_enabled": False,
    "public_interactions": False,
    "collection_management": False,
    "screenshot_enabled": True,
    "owner_scope": "",
    "owner_id": "",
    "dnd_ranges": None,
    "phone_url": "http://172.18.0.1:8009/Phone",
    "bili_url": "http://172.18.0.1:8010/mcp",
    "check_minutes": 30,
    "max_videos": 3,
    "max_minutes": 10,
    "once_at": None,
    "one_shot_verified": False,
    "device_id": "emulator-5554",
}
DEFAULT_DATA_DIR = "/opt/dafeiyu/astrbot/data/plugin_data/astrbot_plugin_bili_activity"


def load_control(folder: Path):
    path = folder / "control.json"
    if not path.exists():
        return dict(DEFAULTS)
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("control.json must contain an object")
    return {**DEFAULTS, **result}


def ready(config):
    scope = config["owner_scope"]
    if not isinstance(scope, str) or not re.fullmatch(r"[^:]+:FriendMessage:\d+", scope):
        raise ValueError("先设置实际主人的私聊 owner_scope；不能从模板推测接收人")
    if not config["owner_id"] or scope.rsplit(":", 1)[-1] != str(config["owner_id"]):
        raise ValueError("owner_id 必须和 owner_scope 的私聊用户一致")
    ranges = config.get("dnd_ranges")
    if ranges is None:
        raise ValueError("先核对现有免打扰配置并设置 dnd_ranges；确认无免打扰时才填 []")
    validate_dnd(ranges)
    for key in ("phone_url", "bili_url"):
        validate_url(config[key])


def validate_url(value):
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("MCP 地址必须是无凭证的 HTTP/HTTPS URL；不要把凭证放入配置或日志")


def validate_dnd(ranges):
    if not isinstance(ranges, list):
        raise ValueError("dnd_ranges 必须为 [[\"23:00\",\"08:00\"]] 形式的数组")
    for pair in ranges:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("每个免打扰时段必须包含开始和结束时间")
        for item in pair:
            if not isinstance(item, str) or len(item) != 5 or item[2] != ":":
                raise ValueError("免打扰时间必须为 HH:MM")
            hour, minute = map(int, item.split(":"))
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("免打扰时间超出范围")


@contextmanager
def exclusive(folder):
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / ".ops.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("另一个 ops 命令正在修改配置；请稍后重试") from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def save_control(folder, control):
    path = folder / "control.json"
    if path.exists():
        backup = folder / "config_backups"
        backup.mkdir(exist_ok=True)
        # Keep every user config before a modification; never print it in logs.
        (backup / f"control-{time.time_ns()}.json").write_bytes(path.read_bytes())
    temp = folder / f".control-{os.getpid()}.tmp"
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(control, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_rows(folder, query, params=()):
    path = folder / "activity.sqlite3"
    if not path.exists():
        return []
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in con.execute(query, params)]
    finally:
        con.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(DEFAULT_DATA_DIR))
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "start", "stop", "status", "enable-periodic", "disable-periodic"):
        sub.add_parser(name)
    cfg = sub.add_parser("configure")
    cfg.add_argument("--owner-scope")
    cfg.add_argument("--owner-id")
    cfg.add_argument("--dnd-ranges", help='JSON, e.g. [["23:00","08:00"]]; copy the actual current settings')
    cfg.add_argument("--phone-url")
    cfg.add_argument("--bili-url")
    cfg.add_argument("--device-id")
    cfg.add_argument("--check-minutes", type=int)
    cfg.add_argument("--max-videos", type=int)
    cfg.add_argument("--max-minutes", type=int)
    once = sub.add_parser("once")
    once.add_argument("--delay-seconds", type=int, default=180)
    switches = sub.add_parser("switch")
    switches.add_argument("name", choices=["public_interactions", "collection_management", "screenshot_enabled"])
    switches.add_argument("value", choices=["on", "off"])
    accepted = sub.add_parser("accept-one-shot")
    accepted.add_argument("--evidence", type=Path, required=True,
                          help="JSON with run_id, read_content_verified=true, screenshot_opened=true, qq_screenshot_message_id")
    logs = sub.add_parser("logs")
    logs.add_argument("--lines", type=int, default=50)
    args = parser.parse_args(argv)
    folder = args.data_dir.resolve()
    if args.command == "logs":
        for row in reversed(read_rows(folder, "SELECT * FROM events ORDER BY seq DESC LIMIT ?", (max(1, min(args.lines, 500)),))):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.command == "status":
        print(json.dumps({"control": load_control(folder),
                          "runs": read_rows(folder, "SELECT * FROM runs ORDER BY started DESC LIMIT 5"),
                          "proposals": read_rows(folder, "SELECT id,action,status,created,expires FROM proposals ORDER BY created DESC LIMIT 10"),
                          "deliveries": read_rows(folder, "SELECT id,kind,status,created,receipt FROM deliveries ORDER BY created DESC LIMIT 10")},
                         ensure_ascii=False, indent=2))
        return 0
    with exclusive(folder):
        control = load_control(folder)
        if args.command == "init" and (folder / "control.json").exists():
            print("配置已存在，保持原样。")
            return 0
        if args.command == "configure":
            for field in ("owner_scope", "owner_id", "phone_url", "bili_url", "device_id", "check_minutes", "max_videos", "max_minutes"):
                value = getattr(args, field)
                if value is not None:
                    limits = {"check_minutes": 1440, "max_videos": 10, "max_minutes": 30}
                    if field in limits and not 1 <= value <= limits[field]:
                        raise ValueError(f"{field} must be between 1 and {limits[field]}")
                    if field in {"phone_url", "bili_url"}:
                        validate_url(value)
                    if field == "device_id" and value != "emulator-5554":
                        raise ValueError("本次验收设备固定为 emulator-5554")
                    control[field] = value
            if args.dnd_ranges is not None:
                ranges = json.loads(args.dnd_ranges)
                validate_dnd(ranges)
                control["dnd_ranges"] = ranges
        elif args.command in {"start", "once", "enable-periodic"}:
            ready(control)
            control["enabled"] = True
            if args.command == "once":
                if args.delay_seconds < 60:
                    raise ValueError("首次联调至少留出 60 秒；默认 180 秒")
                control["once_at"] = time.time() + args.delay_seconds
            elif args.command == "enable-periodic":
                if control["one_shot_verified"] is not True:
                    raise ValueError("一次性活动尚未验收；先实际验收并保存 accept-one-shot 证据")
                control["periodic_enabled"] = True
        elif args.command == "stop":
            control.update(enabled=False, periodic_enabled=False, once_at=None)
        elif args.command == "disable-periodic":
            control["periodic_enabled"] = False
        elif args.command == "switch":
            control[args.name] = args.value == "on"
        elif args.command == "accept-one-shot":
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            if not (evidence.get("run_id") and evidence.get("read_content_verified") is True
                    and evidence.get("screenshot_opened") is True and evidence.get("qq_screenshot_message_id")):
                raise ValueError("验收证据缺少实际运行 ID、内容核对或 QQ 图片打开确认/回执")
            rows = read_rows(folder, "SELECT id,status,scope,started,ended FROM runs WHERE id=?", (evidence["run_id"],))
            if not rows or rows[0]["status"] != "completed":
                raise ValueError("运行记录不存在或未完成，不能标记验收通过")
            run = rows[0]
            receipts = read_rows(folder, "SELECT receipt,meta FROM deliveries WHERE scope=? AND kind='screenshot' AND status='sent' AND created>=? AND created<=?",
                                 (run["scope"], run["started"], run["ended"]))
            receipt_ok = False
            for row in receipts:
                receipt = json.loads(row["receipt"] or "null") or {}
                meta = json.loads(row["meta"] or "null") or {}
                if (str(receipt.get("message_id")) == str(evidence["qq_screenshot_message_id"])
                        and receipt.get("verified") is True
                        and receipt.get("image_readback") is True
                        and meta.get("run_id") == run["id"]
                        and meta.get("share_mode") == "autonomous"):
                    receipt_ok = True
            if not receipt_ok:
                raise ValueError("该运行期间没有匹配的 QQ 图片回执和图片读回记录，不能标记验收通过")
            control["one_shot_verified"] = True
            control["one_shot_evidence"] = evidence
        save_control(folder, control)
    print(f"已更新 {folder / 'control.json'}；插件会读取最新设置。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
