"""Runner-local Provider accounting; no real model or QQ calls."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


PLUGIN = Path(__file__).resolve().parents[1] / "plugin/astrbot_plugin_bili_activity"
spec = importlib.util.spec_from_file_location("bili_agent_budget_test", PLUGIN / "agent_budget.py")
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


class LimitReached(RuntimeError):
    pass


class Provider:
    def __init__(self, name="model", failure=None):
        self.provider_config = {"id": name, "modalities": ["image", "tool_use"]}
        self.failure, self.requests, self.streams_closed = failure, [], 0

    async def text_chat(self, **kwargs):
        self.requests.append(kwargs)
        if self.failure:
            raise self.failure
        return "response"

    async def text_chat_stream(self, **kwargs):
        self.requests.append(kwargs)
        try:
            yield "first"
            yield "second"
        finally:
            self.streams_closed += 1


def runner(primary=None, fallbacks=()):
    return types.SimpleNamespace(provider=primary or Provider(), fallback_providers=list(fallbacks),
                                 request_stop=Mock(), streaming=False,
                                 llm_compress_provider=None, custom_compressor=None,
                                 request_context_manager_config=types.SimpleNamespace(
                                     llm_compress_provider=None, custom_compressor=None))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_count_actual_calls_and_leave_shared_front_provider_unchanged(self):
        shared = Provider()
        active = runner(shared)
        charge = Mock()
        guard = adapter.instrument_runner(active, charge)
        charge.assert_not_called()
        self.assertIsNot(active.provider, shared)
        self.assertIs(active.provider.provider_config, shared.provider_config)
        self.assertEqual(active.request_max_retries, 1)
        await active.provider.text_chat(text="background")
        await shared.text_chat(text="foreground")
        self.assertEqual(charge.call_count, 1)
        self.assertEqual(shared.requests, [{"text": "background"}, {"text": "foreground"}])
        self.assertNotIn("text_chat", vars(shared))
        guard.raise_if_blocked()

    async def test_failed_request_and_fallback_each_use_one_reservation(self):
        primary, backup = Provider(failure=TimeoutError()), Provider("fallback")
        active = runner(primary, [backup])
        charge = Mock()
        guard = adapter.instrument_runner(active, charge)
        with self.assertRaises(TimeoutError):
            await active.provider.text_chat()
        self.assertEqual(await active.fallback_providers[0].text_chat(), "response")
        self.assertEqual(charge.call_count, 2)
        self.assertEqual((len(primary.requests), len(backup.requests)), (1, 1))
        active.request_stop.assert_not_called()
        guard.raise_if_blocked()

    async def test_budget_failure_stops_runner_and_blocks_fallback_even_if_caught(self):
        first, second = Provider(), Provider("fallback")
        active = runner(first, [second])
        charge = Mock(side_effect=[None, LimitReached("day budget")])
        guard = adapter.instrument_runner(active, charge)
        await active.provider.text_chat()
        with self.assertRaises(LimitReached):
            await active.provider.text_chat()
        # Native fallback catches ordinary exceptions. The guard still prevents
        # a second provider call and exposes the original stop to the caller.
        with self.assertRaisesRegex(LimitReached, "day budget"):
            await active.fallback_providers[0].text_chat()
        with self.assertRaises(LimitReached):
            guard.raise_if_blocked()
        active.request_stop.assert_called_once()
        self.assertEqual(charge.call_count, 2)
        self.assertEqual((len(first.requests), len(second.requests)), (1, 0))

    async def test_stream_is_charged_once_not_per_chunk_and_closed_on_early_exit(self):
        provider = Provider()
        active = runner(provider)
        active.streaming = True
        charge = Mock()
        adapter.instrument_runner(active, charge)
        stream = active.provider.text_chat_stream()
        charge.assert_not_called()
        self.assertEqual(await anext(stream), "first")
        await stream.aclose()
        self.assertEqual(charge.call_count, 1)
        self.assertEqual(provider.streams_closed, 1)
        self.assertEqual([part async for part in active.provider.text_chat_stream()], ["first", "second"])
        self.assertEqual(charge.call_count, 2)
        self.assertEqual(provider.streams_closed, 2)

    async def test_exhausted_stream_never_opens_network(self):
        provider = Provider()
        active = runner(provider)
        active.streaming = True
        guard = adapter.instrument_runner(active, Mock(side_effect=LimitReached()))
        with self.assertRaises(LimitReached):
            await anext(active.provider.text_chat_stream())
        self.assertEqual(provider.requests, [])
        active.request_stop.assert_called_once()
        with self.assertRaises(LimitReached):
            guard.raise_if_blocked()

    async def test_cancellation_propagates_without_retry_or_refund(self):
        provider = Provider(failure=asyncio.CancelledError())
        active = runner(provider)
        charge = Mock()
        guard = adapter.instrument_runner(active, charge)
        with self.assertRaises(asyncio.CancelledError):
            await active.provider.text_chat()
        charge.assert_called_once()
        self.assertEqual(len(provider.requests), 1)
        guard.raise_if_blocked()

    def test_incompatible_runner_fails_before_mutation(self):
        for mutation in (
            lambda r: setattr(r, "request_stop", None),
            lambda r: setattr(r, "llm_compress_provider", Provider()),
            lambda r: setattr(r, "custom_compressor", object()),
            lambda r: setattr(r.request_context_manager_config, "llm_compress_provider", Provider()),
            lambda r: setattr(r, "fallback_providers", [object()]),
            lambda r: setattr(r, "fallback_providers", "unsupported"),
        ):
            with self.subTest(mutation=mutation):
                active = runner()
                original = active.provider
                mutation(active)
                with self.assertRaises(RuntimeError):
                    adapter.instrument_runner(active, Mock())
                self.assertIs(active.provider, original)

    def test_instrumentation_cannot_be_stacked(self):
        active = runner()
        adapter.instrument_runner(active, Mock())
        original = active.provider
        with self.assertRaises(RuntimeError):
            adapter.instrument_runner(active, Mock())
        self.assertIs(active.provider, original)

    async def test_two_runners_sharing_provider_have_independent_guards(self):
        provider = Provider()
        one, two = runner(provider), runner(provider)
        adapter.instrument_runner(one, Mock(side_effect=LimitReached()))
        other_charge = Mock()
        adapter.instrument_runner(two, other_charge)
        with self.assertRaises(LimitReached):
            await one.provider.text_chat()
        self.assertEqual(await two.provider.text_chat(), "response")
        other_charge.assert_called_once()
        two.request_stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
