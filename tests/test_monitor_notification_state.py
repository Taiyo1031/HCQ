from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.cook_monitor import CookMonitor, MonitorRegistration


class FakeStorage:
    def __init__(self):
        self.registry = {}

    def load_monitor_registry(self):
        return self.registry

    def save_monitor_registry(self, value):
        self.registry = value


class FakeHip:
    def path(self):
        return "D:/Project/monitor.hip"

    def isNewFile(self):
        return False


class FakePlaybar:
    def __init__(self):
        self.playing = False

    def isPlaying(self):
        return self.playing


class FakeNode:
    def __init__(self):
        self.count = 1
        self.duration_ms = 1000.0
        self.cooking = False
        self.node_errors = ()
        self.node_warnings = ()

    def path(self):
        return "/obj/cache"

    def name(self):
        return "cache"

    def cookCount(self):
        return self.count

    def lastCookTime(self):
        return self.duration_ms

    def isCooking(self):
        return self.cooking

    def errors(self):
        return self.node_errors

    def warnings(self):
        return self.node_warnings


class FakeHou:
    def __init__(self, node):
        self.hipFile = FakeHip()
        self.playbar = FakePlaybar()
        self._node = node

    def node(self, path):
        return self._node if path == self._node.path() else None


class FakeNotifications:
    def __init__(self):
        self.calls = []
        self.merged = False

    def completed(self, **kwargs):
        self.calls.append(("completed", kwargs))
        return SimpleNamespace(merged=self.merged)

    def warning(self, **kwargs):
        self.calls.append(("warning", kwargs))
        return SimpleNamespace(merged=self.merged)

    def error(self, **kwargs):
        self.calls.append(("error", kwargs))
        return SimpleNamespace(merged=self.merged)


class MonitorNotificationStateTests(unittest.TestCase):
    def make_monitor(self, settings=None):
        node = FakeNode()
        hou = FakeHou(node)
        notifications = FakeNotifications()
        monitor = CookMonitor(
            FakeStorage(),
            settings or {},
            notifications,
            hou_module=hou,
        )
        registration = monitor.add_node(node)
        return monitor, registration, node, hou, notifications

    def test_short_cook_exposes_threshold_suppression_reason(self):
        monitor, registration, node, _hou, notifications = self.make_monitor(
            {"minimum_cook_duration_seconds": 5.0}
        )
        node.count = 2
        node.duration_ms = 2000.0

        monitor.poll_once()
        state = monitor.get_notification_state(registration.id)

        self.assertEqual(state["state"], "suppressed")
        self.assertEqual(state["suppression_reason"], "below_minimum_duration")
        self.assertEqual(state["last_duration_seconds"], 2.0)
        self.assertEqual(monitor.last_suppression_reason, "below_minimum_duration")
        self.assertEqual(notifications.calls, [])

    def test_disabled_result_notification_has_specific_reason(self):
        monitor, registration, node, _hou, notifications = self.make_monitor(
            {"minimum_cook_duration_seconds": 0.0}
        )
        registration.notify_on_complete = False
        node.count = 2

        monitor.poll_once()

        self.assertEqual(
            registration.suppression_reason,
            "completed_notifications_disabled",
        )
        self.assertEqual(notifications.calls, [])

    def test_notified_and_rapid_merge_states_are_public(self):
        monitor, registration, node, _hou, notifications = self.make_monitor(
            {"minimum_cook_duration_seconds": 0.0}
        )
        node.count = 2
        monitor.poll_once()
        self.assertEqual(registration.notification_state, "notified")
        self.assertTrue(registration.last_notification_at)

        notifications.merged = True
        node.count = 3
        node.duration_ms = 2000.0
        monitor.poll_once()
        self.assertEqual(registration.notification_state, "merged")
        self.assertEqual(
            registration.suppression_reason,
            "rapid_notification_merged",
        )

    def test_pause_playback_and_global_suppression_reasons_update_live(self):
        monitor, registration, _node, hou, _notifications = self.make_monitor()

        monitor.suspend()
        self.assertEqual(registration.suppression_reason, "queue_suspended")
        monitor.resume()
        self.assertEqual(registration.notification_state, "ready")

        hou.playbar.playing = True
        monitor.poll_once()
        self.assertEqual(registration.suppression_reason, "playback_active")
        hou.playbar.playing = False
        monitor.poll_once()
        self.assertEqual(registration.notification_state, "ready")

        monitor.update_settings({"monitor_enabled": False})
        self.assertEqual(registration.suppression_reason, "monitor_disabled")

    def test_notification_state_round_trips_in_registry_json(self):
        registration = MonitorRegistration(
            node_path="/obj/cache",
            notification_state="suppressed",
            suppression_reason="below_minimum_duration",
            last_notification_at="2026-07-26T12:00:00+09:00",
        )

        restored = MonitorRegistration.from_dict(registration.to_dict())

        self.assertEqual(restored.notification_state, "suppressed")
        self.assertEqual(restored.suppression_reason, "below_minimum_duration")
        self.assertEqual(
            restored.last_notification_at,
            "2026-07-26T12:00:00+09:00",
        )


if __name__ == "__main__":
    unittest.main()
