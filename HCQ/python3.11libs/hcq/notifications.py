"""Non-modal in-Houdini notifications with a headless-safe event API."""

from __future__ import annotations

import importlib
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable


ActionCallback = Callable[[], None]
NotificationCallback = Callable[["Notification"], None]


def _optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except (ImportError, RuntimeError):
        return None


def _qt_enum(qt_core: Any, group: str, name: str, fallback: Any) -> Any:
    qt = getattr(qt_core, "Qt", None)
    grouped = getattr(qt, group, None) if qt is not None else None
    return getattr(grouped, name, getattr(qt, name, fallback))


@dataclass
class NotificationAction:
    label: str
    callback: ActionCallback


@dataclass
class Notification:
    title: str
    message: str
    level: str = "info"
    node_path: str = ""
    duration_seconds: float | None = None
    actions: list[NotificationAction] = field(default_factory=list)
    timeout_ms: int = 6000
    repeat_count: int = 1
    merged: bool = False
    delivery: dict[str, bool] = field(default_factory=dict)


class ToastPresenter:
    """Creates lightweight Qt widgets only when a Houdini UI is available."""

    def __init__(
        self,
        hou_module: Any | None = None,
        qt_widgets: Any | None = None,
        qt_core: Any | None = None,
    ) -> None:
        self.hou = hou_module
        self.qt_widgets = qt_widgets
        self.qt_core = qt_core
        self._toasts: list[Any] = []
        self._toast_records: dict[int, tuple[Any, Any]] = {}

    def can_present(self) -> bool:
        self._ensure_modules()
        if self.qt_widgets is None or self.qt_core is None:
            return False
        application_type = getattr(self.qt_widgets, "QApplication", None)
        return bool(application_type is not None and application_type.instance() is not None)

    def application_active(self) -> bool:
        if not self.can_present():
            return False
        application = self.qt_widgets.QApplication.instance()
        try:
            active = application.activeWindow()
            if active is None:
                return False
            minimized = getattr(active, "isMinimized", None)
            return not (callable(minimized) and minimized())
        except Exception:
            return False

    def show(self, notification: Notification) -> Any | None:
        if not self.can_present():
            return None
        if id(notification) in self._toast_records:
            return self.update(notification)

        parent = self._main_window()
        frame = self.qt_widgets.QFrame(parent)
        frame.setObjectName("hcqNotificationToast")
        frame.setProperty("hcqLevel", notification.level)
        frame.setWindowTitle(notification.title)
        tooltip = _qt_enum(self.qt_core, "WindowType", "ToolTip", None)
        frameless = _qt_enum(self.qt_core, "WindowType", "FramelessWindowHint", None)
        if tooltip is not None:
            flags = tooltip | frameless if frameless is not None else tooltip
            frame.setWindowFlags(flags)
        frame.setAttribute(
            _qt_enum(self.qt_core, "WidgetAttribute", "WA_DeleteOnClose", 55),
            True,
        )

        layout = self.qt_widgets.QVBoxLayout(frame)
        header = self.qt_widgets.QHBoxLayout()
        level_icon = self.qt_widgets.QLabel(frame)
        pixmap = self._level_pixmap(notification.level)
        if pixmap is not None:
            level_icon.setPixmap(pixmap)
        level_icon.setAccessibleName(notification.level.title())
        level_icon.setToolTip(notification.level.title())
        header.addWidget(level_icon, 0)
        title = self.qt_widgets.QLabel(notification.title, frame)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        title.setAccessibleName(f"{notification.level.title()}: {notification.title}")
        header.addWidget(title, 1)
        layout.addLayout(header)

        message = self.qt_widgets.QLabel(self._message_text(notification), frame)
        message.setWordWrap(True)
        message.setTextInteractionFlags(
            _qt_enum(
                self.qt_core,
                "TextInteractionFlag",
                "TextSelectableByMouse",
                1,
            )
        )
        layout.addWidget(message)

        if notification.actions:
            buttons = self.qt_widgets.QHBoxLayout()
            buttons.addStretch(1)
            for action in notification.actions:
                button = self.qt_widgets.QPushButton(action.label, frame)
                button.clicked.connect(
                    lambda checked=False, callback=action.callback, widget=frame:
                    self._invoke_action(widget, callback)
                )
                buttons.addWidget(button)
            layout.addLayout(buttons)

        frame.setMinimumWidth(340)
        frame.setMaximumWidth(520)
        frame.adjustSize()
        self._position(frame, parent)
        key = id(notification)
        frame.destroyed.connect(lambda *_args, key=key: self._forget_key(key))
        self._toasts.append(frame)
        self._toast_records[key] = (frame, message)
        frame.show()
        frame.raise_()
        if notification.timeout_ms > 0:
            self.qt_core.QTimer.singleShot(notification.timeout_ms, frame.close)
        return frame

    def update(self, notification: Notification) -> Any | None:
        """Update a visible toast after rapid notifications are merged."""
        record = self._toast_records.get(id(notification))
        if record is None:
            return None
        frame, message = record
        try:
            message.setText(self._message_text(notification))
            frame.adjustSize()
            self._reposition_all()
            frame.raise_()
            return frame
        except RuntimeError:
            self._forget_key(id(notification))
            return None

    def close_all(self) -> None:
        for toast in tuple(self._toasts):
            try:
                toast.close()
            except Exception:
                pass
        self._toasts.clear()
        self._toast_records.clear()

    def _ensure_modules(self) -> None:
        if self.hou is None:
            self.hou = _optional_import("hou")
        if self.qt_widgets is None or self.qt_core is None:
            pyside = _optional_import("PySide6")
            if pyside is not None:
                self.qt_widgets = self.qt_widgets or getattr(pyside, "QtWidgets", None)
                self.qt_core = self.qt_core or getattr(pyside, "QtCore", None)

    def _main_window(self) -> Any | None:
        qt = getattr(self.hou, "qt", None) if self.hou is not None else None
        getter = getattr(qt, "mainWindow", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                pass
        application = self.qt_widgets.QApplication.instance()
        return application.activeWindow() if application is not None else None

    def _position(self, frame: Any, parent: Any | None) -> None:
        margin = 18
        vertical_offset = sum(
            toast.height() + 8 for toast in self._toasts if getattr(toast, "isVisible", lambda: False)()
        )
        try:
            if parent is not None:
                top_left = parent.mapToGlobal(parent.rect().topLeft())
                x = top_left.x() + parent.width() - frame.width() - margin
                y = top_left.y() + parent.height() - frame.height() - margin - vertical_offset
            else:
                screen = self.qt_widgets.QApplication.primaryScreen().availableGeometry()
                x = screen.right() - frame.width() - margin
                y = screen.bottom() - frame.height() - margin - vertical_offset
            geometry = self._screen_geometry(parent, x, y)
            if geometry is not None:
                x, y = self._clamped_position(
                    x,
                    y,
                    frame.width(),
                    frame.height(),
                    geometry.left(),
                    geometry.top(),
                    geometry.right(),
                    geometry.bottom(),
                    margin,
                )
            frame.move(x, y)
        except Exception:
            pass

    def _invoke_action(self, frame: Any, callback: ActionCallback) -> None:
        try:
            callback()
        finally:
            frame.close()

    def _forget(self, frame: Any) -> None:
        try:
            self._toasts.remove(frame)
        except ValueError:
            pass

    def _forget_key(self, key: int) -> None:
        record = self._toast_records.pop(key, None)
        if record is not None:
            self._forget(record[0])

    def _reposition_all(self) -> None:
        for frame in tuple(self._toasts):
            try:
                self._position(frame, frame.parentWidget())
            except RuntimeError:
                self._forget(frame)

    def _screen_geometry(self, parent: Any | None, x: int, y: int) -> Any | None:
        if parent is not None:
            try:
                screen = parent.screen()
                if screen is not None:
                    return screen.availableGeometry()
            except Exception:
                pass
        application = self.qt_widgets.QApplication.instance()
        try:
            point_type = getattr(self.qt_core, "QPoint", None)
            screen = application.screenAt(point_type(x, y)) if point_type else None
            if screen is None:
                screen = application.primaryScreen()
            return screen.availableGeometry() if screen is not None else None
        except Exception:
            return None

    def _level_pixmap(self, level: str) -> Any | None:
        application = self.qt_widgets.QApplication.instance()
        if application is None:
            return None
        names = {
            "success": "SP_DialogApplyButton",
            "warning": "SP_MessageBoxWarning",
            "error": "SP_MessageBoxCritical",
            "info": "SP_MessageBoxInformation",
        }
        standard = _qt_enum(
            self.qt_widgets,
            "QStyle.StandardPixmap",
            names.get(level, "SP_MessageBoxInformation"),
            None,
        )
        # _qt_enum targets QtCore.Qt groups. QStyle enums need direct lookup.
        style_type = getattr(self.qt_widgets, "QStyle", None)
        group = getattr(style_type, "StandardPixmap", None)
        standard = getattr(group, names.get(level, "SP_MessageBoxInformation"), standard)
        if standard is None:
            return None
        try:
            icon = application.style().standardIcon(standard)
            size = max(16, int(application.style().pixelMetric(
                getattr(
                    getattr(style_type, "PixelMetric", None),
                    "PM_SmallIconSize",
                    16,
                )
            )))
            return icon.pixmap(size, size)
        except Exception:
            return None

    @staticmethod
    def _message_text(notification: Notification) -> str:
        if notification.repeat_count > 1:
            return f"{notification.message} ({notification.repeat_count} events)"
        return notification.message

    @staticmethod
    def _clamped_position(
        x: int,
        y: int,
        width: int,
        height: int,
        left: int,
        top: int,
        right: int,
        bottom: int,
        margin: int = 18,
    ) -> tuple[int, int]:
        minimum_x = left + margin
        maximum_x = max(minimum_x, right - width - margin + 1)
        minimum_y = top + margin
        maximum_y = max(minimum_y, bottom - height - margin + 1)
        return (
            min(max(x, minimum_x), maximum_x),
            min(max(y, minimum_y), maximum_y),
        )


class WindowsNotificationPresenter:
    """Optional Windows shell notification channel backed by QSystemTrayIcon."""

    def __init__(
        self,
        hou_module: Any | None = None,
        qt_widgets: Any | None = None,
        qt_gui: Any | None = None,
        icon_path: str | None = None,
        click_callback: Callable[[Notification], None] | None = None,
        platform: str | None = None,
    ) -> None:
        self.hou = hou_module
        self.qt_widgets = qt_widgets
        self.qt_gui = qt_gui
        self.icon_path = icon_path or ""
        self.click_callback = click_callback
        self.platform = platform or sys.platform
        self._tray: Any | None = None
        self._last_notification: Notification | None = None

    def is_available(self) -> bool:
        if self.platform != "win32":
            return False
        self._ensure_modules()
        if self.qt_widgets is None:
            return False
        application = getattr(self.qt_widgets, "QApplication", None)
        tray_type = getattr(self.qt_widgets, "QSystemTrayIcon", None)
        if application is None or application.instance() is None or tray_type is None:
            return False
        try:
            return bool(
                tray_type.isSystemTrayAvailable()
                and tray_type.supportsMessages()
            )
        except Exception:
            return False

    can_present = is_available

    def show(self, notification: Notification) -> bool:
        if not self.is_available() or not self._ensure_tray():
            return False
        self._last_notification = notification
        try:
            self._tray.showMessage(
                notification.title,
                notification.message,
                self._message_icon(notification.level),
                notification.timeout_ms,
            )
            return True
        except Exception:
            return False

    def update(self, notification: Notification) -> bool:
        # Windows shell messages cannot be updated reliably in place. The
        # current message remains visible while its repeat count is reflected
        # by the in-Houdini presenter.
        if self._last_notification is not notification:
            return False
        return False

    def close(self) -> None:
        if self._tray is not None:
            try:
                self._tray.hide()
                self._tray.deleteLater()
            except Exception:
                pass
        self._tray = None
        self._last_notification = None

    close_all = close

    def set_click_callback(
        self,
        callback: Callable[[Notification], None] | None,
    ) -> None:
        self.click_callback = callback

    def _ensure_modules(self) -> None:
        if self.hou is None:
            self.hou = _optional_import("hou")
        if self.qt_widgets is None or self.qt_gui is None:
            pyside = _optional_import("PySide6")
            if pyside is not None:
                self.qt_widgets = self.qt_widgets or getattr(pyside, "QtWidgets", None)
                self.qt_gui = self.qt_gui or getattr(pyside, "QtGui", None)

    def _ensure_tray(self) -> bool:
        if self._tray is not None:
            return True
        tray_type = getattr(self.qt_widgets, "QSystemTrayIcon", None)
        if tray_type is None:
            return False
        try:
            application = self.qt_widgets.QApplication.instance()
            self._tray = tray_type(application)
            icon = self._notification_icon()
            if icon is not None:
                self._tray.setIcon(icon)
            self._tray.setToolTip("HCQ — Houdini Cook Queue")
            self._tray.messageClicked.connect(self._on_clicked)
            self._tray.show()
            return True
        except Exception:
            self._tray = None
            return False

    def _notification_icon(self) -> Any | None:
        icon_type = getattr(self.qt_gui, "QIcon", None) if self.qt_gui is not None else None
        if icon_type is not None and self.icon_path and os.path.isfile(self.icon_path):
            try:
                icon = icon_type(self.icon_path)
                if not icon.isNull():
                    return icon
            except Exception:
                pass
        try:
            style_type = getattr(self.qt_widgets, "QStyle", None)
            standard = getattr(
                getattr(style_type, "StandardPixmap", None),
                "SP_ComputerIcon",
            )
            return self.qt_widgets.QApplication.instance().style().standardIcon(standard)
        except Exception:
            return None

    def _message_icon(self, level: str) -> Any:
        tray_type = self.qt_widgets.QSystemTrayIcon
        group = getattr(tray_type, "MessageIcon", tray_type)
        name = {
            "warning": "Warning",
            "error": "Critical",
            "success": "Information",
            "info": "Information",
        }.get(level, "Information")
        return getattr(group, name)

    def _on_clicked(self) -> None:
        if self.click_callback is not None and self._last_notification is not None:
            try:
                self.click_callback(self._last_notification)
            except Exception:
                pass


class NotificationCenter:
    """Collect, deduplicate, and present HCQ notifications."""

    CHANNELS = frozenset({"in_app", "windows", "both", "auto"})

    def __init__(
        self,
        presenter: ToastPresenter | None = None,
        hou_module: Any | None = None,
        merge_rapid: bool = True,
        merge_window_seconds: float = 2.0,
        navigation: Any | None = None,
        view_history_callback: ActionCallback | None = None,
        windows_presenter: WindowsNotificationPresenter | None = None,
        notification_channel: str = "in_app",
    ) -> None:
        self.hou = hou_module
        self.presenter = presenter or ToastPresenter(hou_module=hou_module)
        self.windows_presenter = windows_presenter or WindowsNotificationPresenter(
            hou_module=hou_module,
            click_callback=self._windows_clicked,
        )
        set_click_callback = getattr(self.windows_presenter, "set_click_callback", None)
        if callable(set_click_callback):
            set_click_callback(self._windows_clicked)
        self.merge_rapid = merge_rapid
        self.merge_window_seconds = max(0.0, float(merge_window_seconds))
        self.navigation = navigation
        self.view_history_callback = view_history_callback
        self.notification_channel = "in_app"
        self.set_channel(notification_channel)
        self.history: list[Notification] = []
        self._listeners: list[NotificationCallback] = []
        self._last_signature: tuple[Any, ...] | None = None
        self._last_sent_at = 0.0

    def subscribe(self, callback: NotificationCallback) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def send(self, notification: Notification) -> Notification:
        now = time.monotonic()
        signature = (
            notification.level,
            notification.title,
            notification.message,
            notification.node_path,
        )
        if (
            self.merge_rapid
            and self.history
            and signature == self._last_signature
            and now - self._last_sent_at <= self.merge_window_seconds
        ):
            existing = self.history[-1]
            existing.repeat_count += 1
            existing.merged = True
            self._last_sent_at = now
            for callback in tuple(self._listeners):
                try:
                    callback(existing)
                except Exception:
                    pass
            self._post_ui(lambda: self._update_presented(existing))
            return existing

        notification.merged = False
        self._add_default_actions(notification)
        self.history.append(notification)
        self._last_signature = signature
        self._last_sent_at = now
        for callback in tuple(self._listeners):
            try:
                callback(notification)
            except Exception:
                pass
        self._post_ui(lambda: self._present(notification))
        return notification

    def set_channel(self, channel: str) -> str:
        """Select ``in_app``, ``windows``, ``both``, or context-aware ``auto``."""
        value = str(channel or "in_app").strip().lower()
        if value not in self.CHANNELS:
            raise ValueError(f"Unsupported notification channel: {channel}")
        self.notification_channel = value
        return value

    def update_settings(self, settings: dict[str, Any]) -> None:
        """Apply notification preferences without recreating the manager."""
        self.merge_rapid = bool(settings.get("merge_rapid_notifications", True))
        try:
            window = float(
                settings.get(
                    "notification_merge_window_seconds",
                    self.merge_window_seconds,
                )
            )
        except (TypeError, ValueError):
            window = self.merge_window_seconds
        self.merge_window_seconds = max(0.0, window)
        configured = settings.get("notification_channel")
        if configured is None:
            configured = (
                "both"
                if bool(settings.get("windows_notifications_enabled", False))
                else "in_app"
            )
        self.set_channel(str(configured))

    def windows_available(self) -> bool:
        checker = getattr(self.windows_presenter, "is_available", None)
        if not callable(checker):
            checker = getattr(self.windows_presenter, "can_present", None)
        try:
            return bool(checker()) if callable(checker) else False
        except Exception:
            return False

    def channel_availability(self) -> dict[str, bool]:
        can_present = getattr(self.presenter, "can_present", None)
        try:
            in_app = bool(can_present()) if callable(can_present) else True
        except Exception:
            in_app = False
        return {
            "in_app": in_app,
            "windows": self.windows_available(),
        }

    def test_notification(self, channel: str | None = None) -> Notification:
        """Send a harmless test through the requested or current channel."""
        notification = Notification(
            title="HCQ Notification Test",
            message="Notifications are configured correctly.",
            level="info",
        )
        if channel is None:
            return self.send(notification)
        requested = str(channel).strip().lower()
        if requested not in self.CHANNELS:
            raise ValueError(f"Unsupported notification channel: {channel}")
        self._add_default_actions(notification)
        self._post_ui(lambda: self._present(notification, requested))
        return notification

    send_test_notification = test_notification

    def completed(
        self,
        title: str,
        message: str,
        node_path: str = "",
        duration_seconds: float | None = None,
        actions: list[NotificationAction] | None = None,
    ) -> Notification:
        return self.send(
            Notification(
                title=title,
                message=message,
                level="success",
                node_path=node_path,
                duration_seconds=duration_seconds,
                actions=list(actions or []),
            )
        )

    def warning(
        self,
        title: str,
        message: str,
        node_path: str = "",
        duration_seconds: float | None = None,
        actions: list[NotificationAction] | None = None,
    ) -> Notification:
        return self.send(
            Notification(
                title=title,
                message=message,
                level="warning",
                node_path=node_path,
                duration_seconds=duration_seconds,
                actions=list(actions or []),
            )
        )

    def error(
        self,
        title: str,
        message: str,
        node_path: str = "",
        duration_seconds: float | None = None,
        actions: list[NotificationAction] | None = None,
    ) -> Notification:
        return self.send(
            Notification(
                title=title,
                message=message,
                level="error",
                node_path=node_path,
                duration_seconds=duration_seconds,
                actions=list(actions or []),
                timeout_ms=0,
            )
        )

    def info(
        self,
        title: str,
        message: str,
        node_path: str = "",
        actions: list[NotificationAction] | None = None,
    ) -> Notification:
        return self.send(
            Notification(
                title=title,
                message=message,
                level="info",
                node_path=node_path,
                actions=list(actions or []),
            )
        )

    def job_finished(self, job: Any, result: Any) -> Notification:
        """Present a Queue Runner job result with useful, non-modal actions."""
        state = str(getattr(result, "state", "unknown"))
        name = str(
            getattr(job, "display_name", "")
            or getattr(result, "display_name", "")
            or "Queue Job"
        )
        node_path = str(
            getattr(job, "node_path", "")
            or getattr(result, "node_path", "")
        )
        duration = getattr(result, "duration_seconds", None)
        actions: list[NotificationAction] = []
        outputs = list(getattr(result, "output_paths", ()) or ())
        if outputs and self.navigation is not None:
            opener = getattr(self.navigation, "open_output_folder", None)
            if callable(opener):
                actions.append(
                    NotificationAction(
                        "Open Output Folder",
                        lambda path=outputs[0]: opener(path),
                    )
                )
        if state == "completed":
            return self.completed(
                "Job Complete",
                f"{name} completed successfully.",
                node_path,
                duration,
                actions,
            )
        if state == "completed_with_warning":
            warnings = list(getattr(result, "warnings", ()) or ())
            message = f"{name} completed with warnings."
            if warnings:
                message = f"{message} {warnings[0]}"
            return self.warning(
                "Job Completed with Warnings",
                message,
                node_path,
                duration,
                actions,
            )
        if state in {"cancelled", "skipped"}:
            return self.warning(
                "Job Cancelled" if state == "cancelled" else "Job Skipped",
                f"{name} was {state}.",
                node_path,
                duration,
                actions,
            )
        errors = list(getattr(result, "errors", ()) or ())
        message = f"{name} failed."
        if errors:
            message = f"{message} {errors[0]}"
        return self.error(
            "Job Failed",
            message,
            node_path,
            duration,
            actions,
        )

    def queue_finished(self, session: Any) -> Notification:
        state = str(getattr(session, "state", "unknown"))
        actions: list[NotificationAction] = []
        if self.view_history_callback is not None:
            actions.append(NotificationAction("View History", self.view_history_callback))
        if state == "completed":
            return self.completed(
                "Queue Complete",
                "All enabled queue jobs completed.",
                actions=actions,
            )
        if state == "cancelled":
            return self.warning(
                "Queue Cancelled",
                "The queue was cancelled.",
                actions=actions,
            )
        return self.error(
            "Queue Failed",
            str(getattr(session, "message", "") or "The queue stopped after a failure."),
            actions=actions,
        )

    def clear(self) -> None:
        self.history.clear()
        self._last_signature = None
        self.presenter.close_all()
        close_windows = getattr(self.windows_presenter, "close_all", None)
        if not callable(close_windows):
            close_windows = getattr(self.windows_presenter, "close", None)
        if callable(close_windows):
            close_windows()

    def _present(
        self,
        notification: Notification,
        channel: str | None = None,
    ) -> dict[str, bool]:
        selected = channel or self.notification_channel
        delivery = {"in_app": False, "windows": False, "fallback": False}

        if selected == "auto":
            active = getattr(self.presenter, "application_active", None)
            try:
                selected = "in_app" if callable(active) and active() else "windows"
            except Exception:
                selected = "windows"

        if selected in {"in_app", "both"}:
            try:
                delivery["in_app"] = self.presenter.show(notification) is not None
            except Exception:
                delivery["in_app"] = False

        if selected in {"windows", "both"}:
            try:
                delivery["windows"] = bool(self.windows_presenter.show(notification))
            except Exception:
                delivery["windows"] = False
            if not delivery["windows"] and not delivery["in_app"]:
                delivery["fallback"] = True
                try:
                    delivery["in_app"] = self.presenter.show(notification) is not None
                except Exception:
                    delivery["in_app"] = False

        notification.delivery = delivery
        return delivery

    def _update_presented(self, notification: Notification) -> None:
        updated = False
        update_in_app = getattr(self.presenter, "update", None)
        if callable(update_in_app):
            try:
                updated = update_in_app(notification) is not None
            except Exception:
                updated = False
        notification.delivery["in_app"] = (
            notification.delivery.get("in_app", False) or updated
        )
        update_windows = getattr(self.windows_presenter, "update", None)
        if callable(update_windows):
            try:
                update_windows(notification)
            except Exception:
                pass

    def _windows_clicked(self, notification: Notification) -> None:
        if notification.node_path and self.navigation is not None:
            callback = getattr(self.navigation, "go_to_node", None)
            if callable(callback):
                callback(notification.node_path)
                return
        if self.view_history_callback is not None:
            self.view_history_callback()

    def _add_default_actions(self, notification: Notification) -> None:
        if not notification.node_path or self.navigation is None:
            return
        if any(action.label == "Go to Node" for action in notification.actions):
            return
        callback = getattr(self.navigation, "go_to_node", None)
        if callable(callback):
            notification.actions.append(
                NotificationAction(
                    "Go to Node",
                    lambda path=notification.node_path: self._navigate_to_node(
                        callback, path
                    ),
                )
            )

    def _navigate_to_node(
        self,
        callback: Callable[[str], Any],
        node_path: str,
    ) -> None:
        try:
            result = callback(node_path)
            if getattr(result, "success", True) is False:
                message = str(
                    getattr(
                        result,
                        "message",
                        f"Could not navigate to node: {node_path}",
                    )
                )
                self.warning("Navigation Failed", message)
        except Exception as error:
            self.warning(
                "Navigation Failed",
                f"Could not navigate to node: {node_path}. {error}",
            )

    def _post_ui(self, callback: Callable[[], None]) -> None:
        if self.hou is None:
            self.hou = _optional_import("hou")
        available = getattr(self.hou, "isUIAvailable", None) if self.hou is not None else None
        if not callable(available):
            callback()
            return
        try:
            if not available():
                callback()
                return
        except Exception:
            return
        ui = getattr(self.hou, "ui", None) if self.hou is not None else None
        post = getattr(ui, "postEventCallback", None)
        if callable(post):
            try:
                post(callback)
                return
            except Exception:
                return
