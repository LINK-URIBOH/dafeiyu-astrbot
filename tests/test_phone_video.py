"""Conservative current-video navigation tests; no real emulator is contacted."""
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("phone_video_test_module", ROOT / "deploy/bili_activity/phone_video.py")
phone = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = phone
SPEC.loader.exec_module(phone)

BV = "BV1234567890"
FOCUS = "mCurrentFocus=Window{abc u0 tv.danmaku.bili/.VideoDetailsActivity}"
OTHER = "mCurrentFocus=Window{abc u0 com.android.settings/.Settings}"


def xml(value, resource="video_id", *, second="", clickable="false", label=None):
    content = label if label is not None else value
    return ('<hierarchy><node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/'
            + resource + '" text="' + content + '" clickable="' + clickable
            + '" bounds="[0,0][100,100]"/>' + second + '</hierarchy>')


class FakeADB:
    def __init__(self, screen=None, focus=None, top=None, online=True):
        self.screen = screen or xml(BV)
        self.focus = list(focus or [FOCUS])
        self.top = top or ("ACTIVITY tv.danmaku.bili/.VideoDetailsActivity\n"
                           f"  mIntent=Intent {{ dat=https://www.bilibili.com/video/{BV}?p=1 }}")
        self.online = online
        self.calls = []

    async def __call__(self, command, timeout):
        args = command[3:]
        self.calls.append(args)
        if args == ["get-state"]:
            return (0, "device\n", "") if self.online else (1, "", "device unavailable")
        if args == ["shell", "dumpsys", "window"]:
            value = self.focus[0] if len(self.focus) == 1 else self.focus.pop(0)
            return 0, value, ""
        if args[:3] == ["shell", "uiautomator", "dump"]:
            return 0, self.screen, ""
        if args == ["shell", "dumpsys", "activity", "top"]:
            return 0, self.top, ""
        if args[:3] == ["shell", "am", "start"]:
            return 0, "Status: ok", ""
        if args[:3] == ["shell", "input", "tap"]:
            return 0, "", ""
        raise AssertionError(args)


class ParsingTests(unittest.TestCase):
    def test_exact_reference_and_part(self):
        self.assertEqual(phone.video_reference(BV)["bvid"], BV)
        value = phone.video_reference(f"https://www.bilibili.com/video/{BV}?p=2")
        self.assertEqual(value["page"], 2)
        self.assertIsNone(phone.video_reference(BV)["page"])

    def test_reject_untrusted_urls_and_ambiguous_page(self):
        for value in (f"https://evil.example/video/{BV}", f"http://www.bilibili.com/video/{BV}",
                      f"https://www.bilibili.com@evil.example/video/{BV}",
                      f"https://www.bilibili.com/video/{BV}?p=1&p=2", "abc" + BV):
            with self.subTest(value=value):
                self.assertIsNone(phone.video_reference(value))

    def test_comments_and_titles_are_not_video_identity(self):
        for resource in ("comment", "title", "video_title"):
            self.assertIsNone(phone.visible_reference(xml(BV, resource)))
        self.assertEqual(phone.visible_reference(xml(BV))["bvid"], BV)

    def test_multiple_references_are_unknown(self):
        second = '<node package="tv.danmaku.bili" resource-id="tv.danmaku.bili:id/video_id" text="BV0987654321"/>'
        self.assertIsNone(phone.visible_reference(xml(BV, second=second)))

    def test_background_activity_intent_not_authoritative(self):
        dump = f"ACTIVITY tv.danmaku.bili/.Video\n mIntent=Intent {{ dat=https://www.bilibili.com/video/{BV} }}"
        self.assertEqual(phone.intent_candidate(dump)["bvid"], BV)
        self.assertIsNone(phone.intent_candidate(dump + "\nACTIVITY tv.danmaku.bili/.Home\n"))
        self.assertIsNone(phone.focused_component("mFocusedApp=tv.danmaku.bili/.Video"))


class NavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_requires_visible_field_not_launch_echo(self):
        runner = FakeADB(screen=xml("example title", "title"))
        value = await phone.PhoneVideo(runner=runner).open_video(BV, 1)
        self.assertTrue(value["navigation_confirmed"])
        self.assertFalse(value["identity_verified"])
        self.assertFalse(value["requested_video_matches"])
        self.assertEqual(value["intent_candidate"]["bvid"], BV)

    async def test_visible_page_verifies_requested_match(self):
        runner = FakeADB(screen=xml(f"https://www.bilibili.com/video/{BV}?p=2", "share_url"))
        value = await phone.PhoneVideo(runner=runner).open_video(BV, 2)
        self.assertTrue(value["requested_video_matches"])
        self.assertTrue(value["part_verified"])

    async def test_wrong_part_does_not_match(self):
        runner = FakeADB(screen=xml(f"https://www.bilibili.com/video/{BV}?p=1", "share_url"))
        value = await phone.PhoneVideo(runner=runner).open_video(BV, 2)
        self.assertFalse(value["requested_video_matches"])

    async def test_foreground_change_invalidates_read(self):
        value = await phone.PhoneVideo(runner=FakeADB(focus=[FOCUS, OTHER])).current_video()
        self.assertFalse(value["identity_verified"])
        self.assertEqual(value["reason"], "foreground_changed_during_read")

    async def test_offline_exits_before_navigation(self):
        runner = FakeADB(online=False)
        local = phone.PhoneVideo(runner=runner)
        self.assertFalse((await local.device_online())["online"])
        with self.assertRaises(RuntimeError):
            await local.open_video(BV, 1)
        self.assertFalse(any(args[:3] == ["shell", "am", "start"] for args in runner.calls))

    async def test_follow_button_never_used_as_following_tab(self):
        runner = FakeADB(screen=xml("", "follow_button", clickable="true", label="关注"))
        with self.assertRaises(RuntimeError):
            await phone.PhoneVideo(runner=runner).following()
        self.assertFalse(any(args[:3] == ["shell", "input", "tap"] for args in runner.calls))

    async def test_exact_navigation_tab_is_permitted(self):
        runner = FakeADB(screen=xml("", "navigation_tab", clickable="true", label="动态"))
        value = await phone.PhoneVideo(runner=runner).following()
        self.assertEqual(value["tapped_label"], "动态")
        self.assertFalse(value["page_verified"])
        self.assertIn(["shell", "input", "tap", "50", "50"], runner.calls)

    async def test_invalid_id_and_unsupported_action_never_reach_adb(self):
        runner = FakeADB()
        local = phone.PhoneVideo(runner=runner)
        for operation, args in (("open_video", {"bvid": BV + ";whoami"}), ("follow", {"uid": 1})):
            with self.assertRaises(ValueError):
                await local.run(operation, args)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
