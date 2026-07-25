"""Non-modal in-Houdini notifications with a headless-safe event API."""

from __future__ import annotations

import importlib
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

    def show(self, notification: Notification) -> Any | None:
        self._ensure_modules()
        if self.qt_widgets is None or self.qt_core is None:
            return None
        application_type = getattr(self.qt_widgets, "QApplication", None)
        if application_type is None or application_type.instance() is None:
            return None

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
        title = self.qt_widgets.QLabel(notification.title, frame)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        text = notification.message
        if notification.repeat_count > 1:
            text = f"{text} ({notification.repeat_count} events)"
        message = self.qt_widgets.QLabel(text, frame)
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
        frame.destroyed.connect(lambda *_: self._forget(frame))
        self._toasts.append(frame)
        frame.show()
        frame.raise_()
        if notification.timeout_ms > 0:
            self.qt_core.QTimer.singleShot(notification.timeout_ms, frame.close)
        return frame

    def close_all(self) -> None:
        for toast in tuple(self._toasts):
            try:
                toast.close()
            except Exception:
                pass
        self._toasts.clear()

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
            frame.move(max(0, x), max(0, y))
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


class NotificationCenter:
    """Collect, deduplicate, and present HCQ notifications."""

    def __init__(
        self,
        presenter: ToastPresenter | None = None,
        hou_module: Any | None = None,
        merge_rapid: bool = True,
        merge_window_seconds: float = 2.0,
        navigation: Any | None = None,
        view_history_callback: ActionCallback | None = None,
    ) -> None:
        self.hou = hou_module
        self.presenter = presenter or ToastPresenter(hou_module=hou_module)
        self.merge_rapid = merge_rapid
        self.merge_window_seconds = max(0.0, float(merge_window_seconds))
        self.navigation = navigation
        self.view_history_callback = view_history_callback
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
            self.history[-1].repeat_count += 1
            self._last_sent_at = now
            return self.history[-1]

        self._add_default_actions(notification)
        self.history.append(notification)
        self._last_signature = signature
        self._last_sent_at = now
        for callback in tuple(self._listeners):
            try:
                callback(notification)
            except Exception:
                pass
        self._post_ui(lambda: self.presenter.show(notification))
        return notification

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
                    lambda path=notification.node_path: callback(path),
                )
            )

    def _post_ui(self, callback: Callable[[], None]) -> None:
        if self.hou is None:
            self.hou = _optional_import("hou")
        available = getattr(self.hou, "isUIAvailable", None) if self.hou is not None else None
        if callable(available):
            try:
                if not available():
                    callback()
                    return
            except Exception:
                pass
        ui = getattr(self.hou, "ui", None) if self.hou is not None else None
        post = getattr(ui, "postEventCallback", None)
        if callable(post):
            try:
                post(callback)
                return
            except Exception:
                pass
        callback()
