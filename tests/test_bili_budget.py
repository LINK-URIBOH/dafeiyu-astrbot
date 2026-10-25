"""Daily activity limits survive restarts and use Shanghai day boundaries."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PLUGIN = Path(__file__).resolve().parents[1] / "plugin/astrbot_plugin_bili_activity"
package = types.ModuleType("bili_budget_test")
package.__path__ = [str(PLUGIN)]
sys.modules[package.__name__] = package


def load(name):
    spec = importlib.util.spec_from_file_location(package.__name__ + "." + name, PLUGIN / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core, budget = load("core"), load("budget")
SCOPE = "qq:FriendMessage:12345"
OTHER = "qq:GroupMessage:12345"
TZ = ZoneInfo("Asia/Shanghai")


def at(day=23, hour=10, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=TZ).timestamp()


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = core.Store(self.temp.name)
        self.budget = budget.Budget(self.store)
        self.cfg = {**budget.DEFAULT_LIMITS, "daily_minutes": 10,
                    "max_model_calls_per_run": 3, "daily_model_calls": 4,
                    "daily_shares": 3, "screenshots_per_run": 1}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def start(self, run="r1", duration=300, now=None, scope=SCOPE):
        return self.budget.start_run(scope, run, duration, self.cfg, at() if now is None else now)

    def test_reserve_before_work_and_release_only_known_unused_time(self):
        self.assertEqual(self.start(duration=900), 600)
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, at()), 0)
        with self.assertRaises(budget.BudgetExceeded):
            self.start("r2", 30)
        self.budget.finish_run(SCOPE, "r1", at() + 120)
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, at()), 480)
        self.assertEqual(self.start("r2", 900, at() + 120), 480)

    def test_run_id_single_use_and_finish_is_idempotent(self):
        self.start()
        self.budget.finish_run(SCOPE, "r1", at() + 100)
        self.budget.finish_run(SCOPE, "r1", at() + 1)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at())["reserved_or_used_seconds"], 100)
        with self.assertRaises(budget.BudgetExceeded):
            self.start()
        self.budget.finish_run(SCOPE, "not-started", at())

    def test_crash_keeps_reservation_and_counters_across_restart(self):
        self.start()
        self.budget.model_call(SCOPE, "r1", self.cfg, at())
        self.budget.share(SCOPE, "r1", "screenshot", self.cfg, at())
        self.store.close()
        self.store = core.Store(self.temp.name)
        self.budget = budget.Budget(self.store)
        snapshot = self.budget.snapshot(SCOPE, self.cfg, at())
        self.assertEqual((snapshot["remaining_seconds"], snapshot["model_calls"], snapshot["shares"]), (300, 1, 1))
        with self.assertRaises(budget.BudgetExceeded):
            self.start()

    def test_midnight_reserves_both_days_and_finish_splits_actual_time(self):
        start = at(hour=23, minute=59, second=30)
        self.assertEqual(self.start(duration=120, now=start), 120)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, start)["reserved_or_used_seconds"], 30)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at(day=24, hour=0))["reserved_or_used_seconds"], 90)
        self.budget.finish_run(SCOPE, "r1", start + 45)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, start)["reserved_or_used_seconds"], 30)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at(day=24, hour=0))["reserved_or_used_seconds"], 15)

    def test_finish_before_midnight_releases_next_day_reservation(self):
        start = at(hour=23, minute=59, second=30)
        self.start(duration=120, now=start)
        self.budget.finish_run(SCOPE, "r1", start + 10)
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, start), 590)
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, start + 40), 600)

    def test_long_run_stops_at_first_exhausted_day_and_cannot_skip_time(self):
        tomorrow = at(day=24, hour=0)
        self.start("tomorrow-reserved", 590, tomorrow)
        start = at(hour=23, minute=59, second=30)
        self.assertEqual(self.start("late", 7200, start), 40)
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, tomorrow), 0)
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, at(day=25)), 600)

    def test_exact_midnight_charges_new_shanghai_day(self):
        self.start("old", 600, at(hour=12))
        midnight = at(day=24, hour=0)
        self.assertEqual(self.start("new", 60, midnight), 60)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, midnight)["day"], "2026-10-24")

    def test_model_limits_per_run_and_per_day(self):
        self.start()
        for _ in range(3):
            self.budget.model_call(SCOPE, "r1", self.cfg, at())
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r1", self.cfg, at())
        self.start("r2")
        self.budget.model_call(SCOPE, "r2", self.cfg, at())
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r2", self.cfg, at())
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at())["model_calls"], 4)

    def test_midnight_resets_daily_calls_but_not_per_run_calls(self):
        self.cfg.update(max_model_calls_per_run=3, daily_model_calls=2)
        start = at(hour=23, minute=59, second=30)
        self.start(duration=120, now=start)
        for _ in range(2):
            self.budget.model_call(SCOPE, "r1", self.cfg, start)
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r1", self.cfg, start)
        self.budget.model_call(SCOPE, "r1", self.cfg, start + 40)
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r1", self.cfg, start + 50)

    def test_shares_count_failed_attempts_and_screenshots_have_per_run_cap(self):
        self.start()
        self.budget.share(SCOPE, "r1", "screenshot", self.cfg, at())
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.share(SCOPE, "r1", "screenshot", self.cfg, at())
        self.budget.share(SCOPE, "r1", "thought", self.cfg, at())
        self.budget.share(SCOPE, "r1", "proposal", self.cfg, at())
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.share(SCOPE, "r1", "thought", self.cfg, at())
        self.budget.finish_run(SCOPE, "r1", at())
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at())["shares"], 3)

    def test_scope_isolation_including_same_run_id(self):
        self.start(duration=600)
        self.assertEqual(self.start(duration=600, scope=OTHER), 600)
        self.budget.model_call(SCOPE, "r1", self.cfg, at())
        self.assertEqual(self.budget.snapshot(OTHER, self.cfg, at())["model_calls"], 0)
        self.budget.finish_run(OTHER, "r1", at())
        self.assertEqual(self.budget.remaining_seconds(SCOPE, self.cfg, at()), 0)

    def test_no_calls_without_live_run_or_after_deadline_finish(self):
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r1", self.cfg, at())
        self.start(duration=20)
        for moment in (at() - 1, at() + 20):
            with self.assertRaises(budget.BudgetExceeded):
                self.budget.share(SCOPE, "r1", "thought", self.cfg, moment)
        self.budget.finish_run(SCOPE, "r1", at() + 1)
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r1", self.cfg, at() + 2)

    def test_duplicate_reservation_key_is_rejected_before_external_action(self):
        self.start()
        self.budget.model_call(SCOPE, "r1", self.cfg, at(), reservation_key="call-1")
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.model_call(SCOPE, "r1", self.cfg, at(), reservation_key="call-1")
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at())["model_calls"], 1)

    def test_invalid_values_do_not_create_budget_rows(self):
        for duration in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.start(duration=duration)
        with self.assertRaises(ValueError):
            self.budget.start_run(SCOPE, "r1", 10, {**self.cfg, "daily_minutes": False}, at())
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM activity_budget_runs").fetchone()[0], 0)

    def test_zero_sharing_limits_disable_shares_without_disabling_reading(self):
        self.cfg["daily_shares"] = 0
        self.start()
        self.budget.model_call(SCOPE, "r1", self.cfg, at())
        for kind in ("thought", "proposal", "screenshot"):
            with self.subTest(kind=kind), self.assertRaises(budget.BudgetExceeded):
                self.budget.share(SCOPE, "r1", kind, self.cfg, at())
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at())["shares"], 0)
        self.cfg.update(daily_shares=3, screenshots_per_run=0)
        self.budget.share(SCOPE, "r1", "thought", self.cfg, at())
        with self.assertRaises(budget.BudgetExceeded):
            self.budget.share(SCOPE, "r1", "screenshot", self.cfg, at())

    def test_nonpositive_required_limits_and_negative_share_limits_rejected(self):
        for key in budget.DEFAULT_LIMITS:
            minimum = 0 if key in {"daily_shares", "screenshots_per_run"} else 1
            for value in (minimum - 1, True, 1.5):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.budget.snapshot(SCOPE, {**self.cfg, key: value}, at())

    def test_clock_rollback_cannot_refund_whole_activity(self):
        self.start()
        self.budget.finish_run(SCOPE, "r1", at() - 1)
        self.assertEqual(self.budget.snapshot(SCOPE, self.cfg, at())["reserved_or_used_seconds"], 300)

    def test_second_connection_observes_reserved_capacity(self):
        self.start(duration=550)
        second_store = core.Store(self.temp.name)
        try:
            second = budget.Budget(second_store)
            self.assertEqual(second.start_run(SCOPE, "second", 100, self.cfg, at()), 50)
            with self.assertRaises(budget.BudgetExceeded):
                self.start("third", 10)
        finally:
            second_store.close()


if __name__ == "__main__":
    unittest.main()
