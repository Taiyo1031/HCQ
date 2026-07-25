from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.cook_monitor import CookMonitor


class FakeStorage:
    def __init__(self):
        self.registry = {}

    def load_monitor_registry(self):
        return self.registry

    def save_monitor_registry(self, value):
        self.registry = value


class FakeHip:
    def path(self):
        return "D:/Project/test.hip"

    def isNewFile(self):
        return False


class FakeHou:
    def __init__(self):
        self.hipFile = FakeHip()

    def node(self, _path):
        return None


class FakeNode:
    def cookCount(self):
        return 1

    def lastCookTime(self):
        return 1500.0

    def errors(self):
        return ()

    def warnings(self):
        return ()


class MonitorTests(unittest.TestCase):
    def test_houdini_cook_milliseconds_are_converted_to_seconds(self):
        monitor = CookMonitor(FakeStorage(), {}, hou_module=FakeHou())
        snapshot = monitor._snapshot(FakeNode())
        self.assertEqual(snapshot.last_cook_time, 1.5)

    def test_save_as_carries_registrations_and_keeps_source_registry(self):
        storage = FakeStorage()
        monitor = CookMonitor(storage, {}, hou_module=FakeHou())
        monitor.add_node("/obj/cache")
        monitor.handle_hip_saved("D:/Project/copy.hip")
        self.assertEqual(
            [item.node_path for item in monitor.registrations], ["/obj/cache"]
        )
        registry_paths = [
            item["node_path"]
            for registrations in storage.registry.values()
            for item in registrations
        ]
        self.assertEqual(registry_paths.count("/obj/cache"), 2)


if __name__ == "__main__":
    unittest.main()
