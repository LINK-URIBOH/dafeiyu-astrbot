"""Offline transport regression: real image bytes, MCP protocol, OneBot doubles.

This suite does not claim a live PhoneMCP or QQ delivery.
Run: .venv/bin/python tests/test_bili_transport.py
"""
import asyncio
import base64
import importlib.util
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bili_transport", ROOT / "plugin/astrbot_plugin_bili_activity/transport.py",
)
transport = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transport
SPEC.loader.exec_module(transport)


def png(color="blue", size=(720, 1280)):
    output = io.BytesIO()
    image = Image.new("RGB", size, color)
    image.save(output, format="PNG")
    return output.getvalue()


def image_result(raw):
    return CallToolResult(content=[
        ImageContent(type="image", data=base64.b64encode(raw).decode(), mimeType="image/png")
    ])


class FakeMCP:
    def __init__(self, result=None):
        self.result = result or image_result(png())
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, args))
        return self.result


class FakeBot:
    def __init__(self, readback=None, send_error=None, read_error=None):
        self.calls = []
        self.readback = readback
        self.send_error = send_error
        self.read_error = read_error

    async def call_action(self, action, **args):
        self.calls.append((action, args))
        if action == "send_private_msg":
            if self.send_error:
                raise self.send_error
            return {"status": "ok", "retcode": 0, "data": {"message_id": 42}}
        if action == "get_msg":
            if self.read_error:
                raise self.read_error
            if self.readback is not None:
                return self.readback
            return {
                "message_id": 42, "message_type": "private", "target_id": 123,
                "message": [{"type": "image", "data": {"file": "file-id.jpg"}}],
            }
        raise AssertionError(action)


def delivery(bot):
    context = SimpleNamespace(get_platform_inst=lambda _: SimpleNamespace(bot=bot))
    return transport.QQDelivery(context, "qq:FriendMessage:123", timeout=0.2)


class ImageTests(unittest.TestCase):
    def test_native_small_image_is_preserved(self):
        raw = png()
        prepared, mime, _, width, height = transport.prepare_image(raw)
        self.assertEqual(prepared, raw)
        self.assertEqual(mime, "image/png")
        self.assertEqual((width, height), (720, 1280))

    def test_compression_keeps_dimensions_and_readable_resolution(self):
        raw = png()
        prepared, mime, _, width, height = transport.prepare_image(raw, target_bytes=500)
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual((width, height), (720, 1280))
        self.assertEqual(Image.open(io.BytesIO(prepared)).size, (720, 1280))

    def test_status_bar_only_differences_dedupe_but_content_does_not(self):
        image = Image.new("RGB", (720, 1280), "white")

        def fingerprint():
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            return transport.prepare_image(stream.getvalue())[2]

        initial = fingerprint()
        image.paste("black", (0, 0, 100, 20))
        self.assertEqual(fingerprint(), initial)
        image.paste("red", (40, 180, 160, 240))
        self.assertNotEqual(fingerprint(), initial)

    def test_windows_path_and_success_message_are_not_images(self):
        result = CallToolResult(content=[TextContent(type="text", text=r"D:\temp\screenshot.png")])
        with self.assertRaises(transport.TransportError):
            transport.image_bytes(result)

    def test_multiple_images_are_ambiguous(self):
        result = image_result(png())
        result.content.append(result.content[0])
        with self.assertRaises(transport.TransportError):
            transport.image_bytes(result)

    def test_payload_and_decode_limits(self):
        with self.assertRaises(transport.TransportError):
            transport.image_bytes(image_result(png()), max_input_bytes=100)
        result = image_result(b"not an image")
        with self.assertRaises(transport.TransportError):
            transport.prepare_image(transport.image_bytes(result))
        with self.assertRaises(transport.TransportError):
            transport.prepare_image(png(size=(10, 10)))

    def test_old_phone_black_fallback_is_not_shared(self):
        with self.assertRaises(transport.TransportError):
            transport.prepare_image(png("black", (1080, 2400)))


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sse_and_streamable_http_mcp_lifecycle(self):
        # A protocol server on loopback exercises initialize/call/teardown,
        # including the supported MCP SDK's actual timeout parameter types.
        for mode in ("sse", "streamable-http"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
                script = Path(folder, "server.py")
                script.write_text(
                    'from mcp.server.fastmcp import FastMCP\n'
                    f'mcp = FastMCP("transport-test", host="127.0.0.1", port={port})\n'
                    '@mcp.tool()\n'
                    'def read_marker() -> dict:\n'
                    '    return {"transport_ok": True, "device_id": "emulator-5554"}\n'
                    f'mcp.run(transport={mode!r})\n', encoding="utf-8",
                )
                process = await asyncio.create_subprocess_exec(
                    sys.executable, str(script), stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    ready = False
                    for _ in range(80):
                        try:
                            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
                            writer.close()
                            await writer.wait_closed()
                            ready = True
                            break
                        except OSError:
                            await asyncio.sleep(0.05)
                    self.assertTrue(ready, "test MCP did not start")
                    path = "/sse" if mode == "sse" else "/mcp"
                    client = transport.MCPClient(f"http://127.0.0.1:{port}{path}", mode, timeout=5)
                    value = await client.json_call("read_marker")
                    self.assertEqual(value, {"transport_ok": True, "device_id": "emulator-5554"})
                finally:
                    if process.returncode is None:
                        process.terminate()
                    await asyncio.wait_for(process.wait(), 5)

    async def test_capture_calls_phone_each_time_and_writes_actual_bytes(self):
        client = FakeMCP()
        with tempfile.TemporaryDirectory() as folder:
            capture = transport.ScreenCapture(client, folder)
            first = await capture.capture(video={"bvid": "BV1234567890", "cid": 1})
            client.result = image_result(png("red"))
            second = await capture.capture()
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(client.calls[0], ("get_screenshot", {"device_id": "emulator-5554"}))
            self.assertNotEqual(first.fingerprint, second.fingerprint)
            self.assertFalse(first.video_verified)
            self.assertLessEqual(first.request_started_at, first.captured_at)
            self.assertTrue(Path(first.path).is_absolute())
            with Image.open(first.path) as loaded:
                self.assertEqual(loaded.size, (720, 1280))
            meta = json.loads(Path(first.path + ".json").read_text())
            self.assertEqual(meta["device_id"], "emulator-5554")

    async def test_gate_blocks_foreign_task_and_releases_after_cancel(self):
        gate = transport.PhoneGate()
        ready = asyncio.Event()

        async def browser():
            async with gate.lease("run"):
                ready.set()
                await asyncio.sleep(30)

        task = asyncio.create_task(browser())
        await ready.wait()
        with self.assertRaises(transport.PhoneBusy):
            await gate.call(FakeMCP(), "tap", {})
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await gate.call(FakeMCP(), "get_screenshot", {})
        with self.assertRaises(transport.PhoneBusy):
            await gate.call(FakeMCP(), "tap", {}, owner="run")

    async def test_concurrent_commands_under_same_lease_are_serial(self):
        gate = transport.PhoneGate()
        active = peak = 0

        class Client:
            async def call(self, name, args):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    await asyncio.sleep(0.01)
                    return {}
                finally:
                    active -= 1

        async with gate.lease() as owner:
            await asyncio.gather(*[
                gate.call(Client(), "tap", {}, owner=owner) for _ in range(4)
            ])
        self.assertEqual(peak, 1)

    async def test_receipt_includes_real_image_send_and_readback(self):
        bot = FakeBot()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "current.png")
            path.write_bytes(png())
            receipt = await delivery(bot).send("qq:FriendMessage:123", "看到这帧啦", path)
        self.assertTrue(receipt["acknowledged"])
        self.assertTrue(receipt["image_readback"])
        self.assertTrue(receipt["readback_verified"])
        self.assertFalse(receipt["recipient_confirmed"])
        self.assertEqual([x[0] for x in bot.calls], ["send_private_msg", "get_msg"])
        sent_image = bot.calls[0][1]["message"][1]["data"]["file"]
        self.assertTrue(sent_image.startswith("base64://"))
        encoded = base64.b64decode(sent_image.removeprefix("base64://"))
        self.assertEqual(Image.open(io.BytesIO(encoded)).size, (720, 1280))

    async def test_send_timeout_never_retries(self):
        bot = FakeBot(send_error=TimeoutError())
        with self.assertRaises(transport.DeliveryUnknown):
            await delivery(bot).send("qq:FriendMessage:123", "hello")
        self.assertEqual(len(bot.calls), 1)

    async def test_readback_failure_retains_ack_and_only_retries_get(self):
        bot = FakeBot(read_error=TimeoutError())
        receipt = await delivery(bot).send("qq:FriendMessage:123", "hello")
        self.assertTrue(receipt["acknowledged"])
        self.assertFalse(receipt["verified"])
        self.assertEqual([x[0] for x in bot.calls], ["send_private_msg", "get_msg", "get_msg"])

    async def test_wrong_recipient_and_missing_image_fail_readback(self):
        for readback in (
            {"message_id": 42, "target_id": 999, "message": []},
            {"message_id": 43, "target_id": 123, "message": []},
            {"message_id": 42, "target_id": 123, "message": [{"type": "text", "data": {"text": "ok"}}]},
        ):
            with self.subTest(readback=readback), tempfile.TemporaryDirectory() as folder:
                path = Path(folder, "current.png")
                path.write_bytes(png())
                receipt = await delivery(FakeBot(readback=readback)).send(
                    "qq:FriendMessage:123", "hi", path,
                )
                self.assertFalse(receipt["verified"])

    async def test_owner_scope_required_before_any_send(self):
        bot = FakeBot()
        for scope in ("qq:GroupMessage:123", "qq:FriendMessage:456"):
            with self.assertRaises(PermissionError):
                await delivery(bot).send(scope, "hello")
        self.assertEqual(bot.calls, [])

    async def test_text_disguised_as_image_rejected_before_network(self):
        bot = FakeBot()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "current.png")
            path.write_text("screenshot success")
            with self.assertRaises(transport.TransportError):
                await delivery(bot).send("qq:FriendMessage:123", "hello", path)
        self.assertEqual(bot.calls, [])

    async def test_json_call_accepts_structured_and_text_json(self):
        client = transport.MCPClient("http://unused")
        async def structured(*_):
            return CallToolResult(content=[], structuredContent={"result": [1, 2]})
        client.call = structured
        self.assertEqual(await client.json_call("example"), [1, 2])
        async def text(*_):
            return CallToolResult(content=[TextContent(type="text", text='{"ok":true}')])
        client.call = text
        self.assertEqual(await client.json_call("example"), {"ok": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
