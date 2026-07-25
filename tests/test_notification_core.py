from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.notifications import (
    Notification,
    NotificationCenter,
    ToastPresenter,
    WindowsNotificationPresenter,
)


class FakeToastPresenter:
    def __init__(self, active: bool = True):
        self.active = active
        self.shown = []
        self.updated = []
        self.closed = False

    def can_present(self):
        return True

    def application_active(self):
        return self.active

    def show(self, notification):
        self.shown.append(notification)
        return object()

    def update(self, notification):
        self.updated.append(notification)
        return object()

    def close_all(self):
        self.closed = True


class FakeWindowsPresenter:
    def __init__(self, available: bool = True):
        self.available = available
        self.shown = []
        self.updated = []
        self.closed = False
        self.click_callback = None

    def set_click_callback(self, callback):
        self.click_callback = callback

    def is_available(self):
        return self.available

    def show(self, notification):
        if not self.available:
            return False
        self.shown.append(notification)
        return True

    def update(self, notification):
        self.updated.append(notification)
        return False

    def close_all(self):
        self.closed = True


class NotificationCoreTests(unittest.TestCase):
    def test_rapid_merge_updates_visible_toast(self):
        toast = FakeToastPresenter()
        windows = FakeWindowsPresenter()
        center = NotificationCenter(
            presenter=toast,
            windows_presenter=windows,
            notification_channel="in_app",
        )

        first = center.completed("Cook Complete", "Cache finished.")
        merged = center.completed("Cook Complete", "Cache finished.")

        self.assertIs(first, merged)
        self.assertEqual(merged.repeat_count, 2)
        self.assertTrue(merged.merged)
        self.assertEqual(len(center.history), 1)
        self.assertEqual(len(toast.shown), 1)
        self.assertEqual(toast.updated, [merged])

    def test_settings_apply_live_and_windows_channel_can_be_tested(self):
        toast = FakeToastPresenter()
        windows = FakeWindowsPresenter()
        center = NotificationCenter(
            presenter=toast,
            windows_presenter=windows,
        )

        center.update_settings(
            {
                "merge_rapid_notifications": False,
                "notification_merge_window_seconds": 7.5,
                "windows_notifications_enabled": True,
            }
        )
        test = center.test_notification("windows")
        center.info("One", "Message")
        center.info("One", "Message")

        self.assertFalse(center.merge_rapid)
        self.assertEqual(center.merge_window_seconds, 7.5)
        self.assertEqual(center.notification_channel, "both")
        self.assertTrue(center.windows_available())
        self.assertTrue(test.delivery["windows"])
        self.assertEqual(len(center.history), 2)

    def test_unavailable_windows_channel_falls_back_to_in_app(self):
        toast = FakeToastPresenter()
        windows = FakeWindowsPresenter(available=False)
        center = NotificationCenter(
            presenter=toast,
            windows_presenter=windows,
            notification_channel="windows",
        )

        notification = center.info("Fallback", "Use the Houdini toast.")

        self.assertFalse(notification.delivery["windows"])
        self.assertTrue(notification.delivery["in_app"])
        self.assertTrue(notification.delivery["fallback"])
        self.assertEqual(center.channel_availability(), {
            "in_app": True,
            "windows": False,
        })

    def test_auto_channel_uses_windows_while_houdini_is_inactive(self):
        toast = FakeToastPresenter(active=False)
        windows = FakeWindowsPresenter()
        center = NotificationCenter(
            presenter=toast,
            windows_presenter=windows,
            notification_channel="auto",
        )

        notification = center.info("Background Cook", "The cook is complete.")

        self.assertTrue(notification.delivery["windows"])
        self.assertFalse(notification.delivery["in_app"])

    def test_negative_monitor_position_is_not_clamped_to_zero(self):
        x, y = ToastPresenter._clamped_position(
            x=-500,
            y=900,
            width=340,
            height=120,
            left=-1920,
            top=0,
            right=-1,
            bottom=1079,
        )

        self.assertLess(x, 0)
        self.assertGreaterEqual(x, -1902)
        self.assertLessEqual(x + 340, -18)
        self.assertGreaterEqual(y, 18)
        self.assertLessEqual(y + 120, 1062)

    def test_windows_presenter_is_headless_safe_off_windows(self):
        presenter = WindowsNotificationPresenter(platform="linux")
        self.assertFalse(presenter.is_available())
        self.assertFalse(presenter.show(Notification("Test", "Message")))

    def test_go_to_node_action_reports_navigation_failure(self):
        navigation = SimpleNamespace(
            go_to_node=lambda _path: SimpleNamespace(
                success=False,
                message="No Network Editor is available.",
            )
        )
        center = NotificationCenter(
            presenter=FakeToastPresenter(),
            windows_presenter=FakeWindowsPresenter(),
            navigation=navigation,
        )
        notification = center.info(
            "Cook Complete",
            "The cook is complete.",
            node_path="/obj/missing",
        )

        notification.actions[0].callback()

        self.assertEqual(center.history[-1].title, "Navigation Failed")
        self.assertEqual(
            center.history[-1].message,
            "No Network Editor is available.",
        )


if __name__ == "__main__":
    unittest.main()
