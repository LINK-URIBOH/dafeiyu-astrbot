"""Conservative local Bilibili navigation and current-video evidence.

This module runs next to PhoneMCP on Windows. It never infers the current video
from a title, an earlier launch request, or an activity backstack. Android
Intent data is only a diagnostic candidate: an app can change video without
changing its Activity Intent. A current identity requires a visible, explicitly
labelled video-id or share-link UI field. If the app does not expose one, callers
must report unknown instead of attaching unrelated metadata to a screenshot.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse


PACKAGE = "tv.danmaku.bili"
DEFAULT_ADB = r"D:\leidian\LDPlayer14\adb.exe"
BV_RE = re.compile(r"BV[0-9A-Za-z]{10}\Z")
VIDEO_FIELD = re.compile(r"(?:^|[/_.:])(?:bvid|bv_id|video_id|share_link|share_url|video_url)(?:$|[/_.:])", re.I)
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\Z")


def video_reference(value: str) -> dict | None:
    """Parse only an exact Bilibili ID/URL; page is unknown unless explicit."""
    value = value.strip()
    if BV_RE.fullmatch(value):
        return {"bvid": value, "page": None, "reference": value}
    if re.fullmatch(r"av[1-9]\d*", value, re.I):
        return {"aid": value[2:], "page": None, "reference": value}
    try:
        url = urlparse(value)
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            return None
        host = (url.hostname or "").lower()
        if host == "b23.tv" and re.fullmatch(r"/[A-Za-z0-9]+/?", url.path):
            return {"short_url": value, "page": None, "reference": value}
        if host not in {"www.bilibili.com", "m.bilibili.com", "bilibili.com"}:
            return None
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10}|av[1-9]\d*)/?", url.path)
        if not match:
            return None
        query = parse_qs(url.query)
        page = query.get("p", [None])
        if len(page) != 1 or (page[0] is not None and not re.fullmatch(r"[1-9]\d{0,3}", page[0])):
            return None
        result = {"reference": value, "page": int(page[0]) if page[0] else None}
        result["bvid" if match[1].startswith("BV") else "aid"] = match[1] if match[1].startswith("BV") else match[1][2:]
        return result
    except ValueError:
        return None


def focused_component(window_dump: str) -> str | None:
    """Only mCurrentFocus is current; mFocusedApp can point behind a dialog."""
    current = [line for line in window_dump.splitlines() if "mCurrentFocus=" in line]
    if len(current) != 1:
        return None
    match = re.search(r"\b(tv\.danmaku\.bili/[\w.$]+)\b", current[0])
    return match[1] if match else None


def visible_reference(xml: str) -> dict | None:
    """Ignore comments/titles containing a BV number; require a labelled field."""
    start, end = xml.find("<hierarchy"), xml.rfind("</hierarchy>")
    if start < 0 or end < start:
        return None
    try:
        root = ET.fromstring(xml[start:end + len("</hierarchy>")])
    except ET.ParseError:
        return None
    references = {}
    for node in root.iter("node"):
        if node.get("package") != PACKAGE or node.get("visible-to-user", "true") == "false":
            continue
        resource_id = node.get("resource-id", "")
        if not VIDEO_FIELD.search(resource_id):
            continue
        for field in ("text", "content-desc"):
            value = video_reference(node.get(field, ""))
            if value:
                key = (value.get("bvid"), value.get("aid"), value.get("short_url"), value.get("page"))
                references[key] = {**value, "resource_id": resource_id, "source": "visible_video_field"}
    # Multiple different references on a page do not identify which is playing.
    return next(iter(references.values())) if len(references) == 1 else None


def intent_candidate(top_dump: str) -> dict | None:
    """Diagnostic only. Never call this verified identity."""
    # `activity top` can contain more than one task: require one Bili activity.
    activities = re.split(r"(?m)^\s*ACTIVITY\s+", top_dump)
    matching = [part for part in activities[1:] if part.startswith(PACKAGE + "/")]
    if len(matching) != 1:
        return None
    refs = {}
    for line in matching[0].splitlines():
        if not re.search(r"\b(?:mIntent|Intent|intent)\s*[:=]", line):
            continue
        for value in re.findall(r"\bdat=(https://[^\s}]+)", line):
            ref = video_reference(value)
            if ref:
                refs[ref["reference"]] = ref
    return next(iter(refs.values())) if len(refs) == 1 else None


async def _run(command: list[str], timeout: float = 15) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.communicate()
        raise
    if len(stdout) + len(stderr) > 2_000_000:
        raise RuntimeError("ADB output exceeds bound")
    return proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


class PhoneVideo:
    def __init__(self, adb_path=None, device_id="emulator-5554", runner=None):
        if not re.fullmatch(r"emulator-\d+", device_id):
            raise ValueError("an emulator serial is required")
        self.adb = str(adb_path or os.environ.get("DAFEIYU_ADB") or DEFAULT_ADB)
        self.device_id = device_id
        self.runner = runner or _run
        self.lock = asyncio.Lock()

    async def _adb(self, *args, timeout=15):
        rc, out, _err = await self.runner([self.adb, "-s", self.device_id, *args], timeout)
        if rc != 0:
            # Do not include arbitrary device output in error messages/logs.
            raise RuntimeError(f"ADB operation failed (exit {rc})")
        return out

    async def device_online(self):
        try:
            out = await self._adb("get-state", timeout=5)
            online = out.strip() == "device"
        except (OSError, RuntimeError, TimeoutError):
            online = False
        return {"device_id": self.device_id, "online": online, "checked_at": time.time()}

    async def _current_video(self):
        started = time.time()
        if not (await self.device_online())["online"]:
            return {"device_id": self.device_id, "online": False, "identity_verified": False,
                    "reason": "device_offline", "observed_at": time.time()}
        before = focused_component(await self._adb("shell", "dumpsys", "window"))
        if not before:
            return {"device_id": self.device_id, "online": True, "identity_verified": False,
                    "reason": "bilibili_not_focused", "observed_at": time.time()}
        ui_reason = None
        try:
            xml = await self._adb("shell", "uiautomator", "dump", "/dev/tty", timeout=12)
            reference = visible_reference(xml)
        except (RuntimeError, TimeoutError):
            reference = None
            ui_reason = "ui_dump_unavailable"
        after = focused_component(await self._adb("shell", "dumpsys", "window"))
        if after != before:
            return {"device_id": self.device_id, "online": True, "identity_verified": False,
                    "reason": "foreground_changed_during_read", "observed_at": time.time()}
        result = {"device_id": self.device_id, "online": True, "foreground": after,
                  "request_started_at": started, "observed_at": time.time()}
        if reference:
            # BV/AV is verified from a UI field; part/cid may still need resolution.
            result.update(reference)
            result.update(reference_verified=True,
                          identity_verified=bool(reference.get("bvid") or reference.get("aid")),
                          part_verified=reference.get("page") is not None)
        else:
            result.update(identity_verified=False, reference_verified=False,
                          reason=ui_reason or "no_unambiguous_visible_video_id_or_share_url")
            try:
                candidate = intent_candidate(await self._adb("shell", "dumpsys", "activity", "top", timeout=8))
                if candidate:
                    result["intent_candidate"] = candidate
                    result["intent_warning"] = "Intent may be stale after in-app navigation or autoplay"
            except (RuntimeError, TimeoutError):
                pass
        return result

    async def current_video(self):
        async with self.lock:
            return await self._current_video()

    async def _launch(self, uri):
        if not (await self.device_online())["online"]:
            raise RuntimeError("device_offline")
        output = await self._adb(
            "shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
            "-d", uri, "-p", PACKAGE, timeout=20,
        )
        if re.search(r"(?im)^\s*(?:Error|Exception):", output):
            raise RuntimeError("Bilibili could not open the requested page")
        return focused_component(await self._adb("shell", "dumpsys", "window"))

    async def open_video(self, bvid, page=1):
        if not isinstance(bvid, str) or not BV_RE.fullmatch(bvid):
            raise ValueError("invalid bvid")
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 9999:
            raise ValueError("invalid video page")
        async with self.lock:
            foreground = await self._launch(f"https://www.bilibili.com/video/{bvid}?p={page}")
            observed = await self._current_video()
            observed["requested"] = {"bvid": bvid, "page": page}
            observed["navigation_confirmed"] = bool(foreground)
            observed["requested_video_matches"] = bool(
                observed.get("identity_verified") and observed.get("bvid") == bvid
                and observed.get("page") == page
            )
            return observed

    async def home(self):
        async with self.lock:
            # Current Bilibili builds no longer resolve bilibili://main/home/.
            # Use the supported home scheme, then fall back to the resolved
            # launcher activity instead of guessing a component name.
            try:
                component = await self._launch("bilibili://home")
            except RuntimeError:
                resolved = await self._adb(
                    "shell", "cmd", "package", "resolve-activity", "--brief", PACKAGE)
                component_name = resolved.strip().splitlines()[-1].strip()
                if not component_name.startswith(PACKAGE + "/"):
                    raise RuntimeError("Bilibili launcher activity unavailable")
                output = await self._adb("shell", "am", "start", "-W", "-n",
                                         component_name, timeout=20)
                if re.search(r"(?im)^\s*(?:Error|Exception):", output):
                    raise RuntimeError("Bilibili could not be launched")
                component = focused_component(await self._adb("shell", "dumpsys", "window"))
            return {"device_id": self.device_id, "requested_page": "home",
                    "bilibili_focused": bool(component), "page_verified": False,
                    "reason": "verify the visible page with PhoneMCP screenshot", "observed_at": time.time()}

    async def following(self):
        """Tap only an exact clickable navigation label; never a follow button."""
        async with self.lock:
            if not focused_component(await self._adb("shell", "dumpsys", "window")):
                raise RuntimeError("Bilibili is not focused")
            xml = await self._adb("shell", "uiautomator", "dump", "/dev/tty", timeout=12)
            start, end = xml.find("<hierarchy"), xml.rfind("</hierarchy>")
            if start < 0 or end < start:
                raise RuntimeError("UI hierarchy unavailable")
            root = ET.fromstring(xml[start:end + len("</hierarchy>")])
            targets = []
            for node in root.iter("node"):
                label = node.get("text", "") or node.get("content-desc", "")
                rid = node.get("resource-id", "").lower()
                # A bare "关注" can be an account mutation. Only a tab id qualifies.
                if (node.get("package") == PACKAGE and label in {"关注", "动态"}
                        and node.get("clickable") == "true" and ("tab" in rid or "navigation" in rid)):
                    match = BOUNDS.fullmatch(node.get("bounds", ""))
                    if match:
                        x1, y1, x2, y2 = map(int, match.groups())
                        if x1 < x2 and y1 < y2:
                            targets.append(((x1 + x2) // 2, (y1 + y2) // 2, label))
            if len(targets) != 1:
                raise RuntimeError("unambiguous following navigation tab unavailable")
            x, y, label = targets[0]
            await self._adb("shell", "input", "tap", str(x), str(y))
            return {"device_id": self.device_id, "requested_page": "following", "tapped_label": label,
                    "page_verified": False, "reason": "verify destination using PhoneMCP screenshot",
                    "observed_at": time.time()}

    async def run(self, operation, args=None):
        args = args or {}
        if operation == "status":
            return await self.device_online()
        if operation == "current":
            return await self.current_video()
        if operation == "open_video":
            return await self.open_video(args["bvid"], args.get("page", 1))
        if operation == "home":
            return await self.home()
        if operation == "following":
            return await self.following()
        raise ValueError("unsupported phone navigation operation")
