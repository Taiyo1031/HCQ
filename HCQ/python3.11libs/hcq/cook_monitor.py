"""Passive monitoring for registered Houdini nodes.

The module deliberately does not import :mod:`hou` or PySide6 at import time.
This keeps the data model and polling logic usable in unit tests and in
``hython``.  A UI session may pass the real modules explicitly, or allow the
monitor to discover them when it starts.
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .utils import new_id, normalized_hip_key, now_iso


ChangeCallback = Callable[["MonitorRegistration", str], None]


def _optional_import(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except (ImportError, RuntimeError):
        return None


def _call(value: Any, name: str, default: Any = None) -> Any:
    try:
        attribute = getattr(value, name)
        return attribute() if callable(attribute) else attribute
    except Exception:
        return default


def _event_name(event: Any) -> str:
    event_type = _call(event, "type")
    if event_type is not None:
        event = event_type
    name = _call(event, "name")
    return str(name if name is not None else event).replace("_", "").lower()


@dataclass
class NodeSnapshot:
    """A small, inexpensive subset of a node's cook state."""

    cook_count: int | None = None
    last_cook_time: float | None = None
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    is_cooking: bool = False
    sampled_at: float = field(default_factory=time.monotonic)


@dataclass
class MonitorRegistration:
    """Serializable monitor registration and its latest public state."""

    id: str = field(default_factory=lambda: new_id("monitor"))
    display_name: str = ""
    node_path: str = ""
    enabled: bool = True
    node_type: str = ""
    monitor_method: str = "generic"
    status: str = "Watching"
    last_cook_count: int | None = None
    last_cook_time: float | None = None
    last_duration_seconds: float | None = None
    last_completed_at: str | None = None
    last_result: str = "unknown"
    notify_on_complete: bool = True
    notify_on_warning: bool = True
    notify_on_failure: bool = True
    notification_state: str = "ready"
    suppression_reason: str = ""
    last_notification_at: str | None = None

    @property
    def method(self) -> str:
        return self.monitor_method

    @property
    def last_duration(self) -> float | None:
        return self.last_duration_seconds

    @property
    def last_cook(self) -> str | None:
        return self.last_completed_at

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MonitorRegistration":
        return cls(
            id=str(value.get("id") or new_id("monitor")),
            display_name=str(value.get("display_name", "")),
            node_path=str(value.get("node_path", "")),
            enabled=bool(value.get("enabled", True)),
            node_type=str(value.get("node_type", "")),
            monitor_method=str(value.get("monitor_method", "generic")),
            status=str(value.get("status", "Watching")),
            last_cook_count=value.get("last_cook_count"),
            last_cook_time=value.get("last_cook_time"),
            last_duration_seconds=value.get("last_duration_seconds"),
            last_completed_at=value.get("last_completed_at"),
            last_result=str(value.get("last_result", "unknown")),
            notify_on_complete=bool(value.get("notify_on_complete", True)),
            notify_on_warning=bool(value.get("notify_on_warning", True)),
            notify_on_failure=bool(value.get("notify_on_failure", True)),
            notification_state=str(value.get("notification_state", "ready")),
            suppression_reason=str(value.get("suppression_reason", "")),
            last_notification_at=value.get("last_notification_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "node_path": self.node_path,
            "enabled": self.enabled,
            "node_type": self.node_type,
            "monitor_method": self.monitor_method,
            "status": self.status,
            "last_cook_count": self.last_cook_count,
            "last_cook_time": self.last_cook_time,
            "last_duration_seconds": self.last_duration_seconds,
            "last_completed_at": self.last_completed_at,
            "last_result": self.last_result,
            "notify_on_complete": self.notify_on_complete,
            "notify_on_warning": self.notify_on_warning,
            "notify_on_failure": self.notify_on_failure,
            "notification_state": self.notification_state,
            "suppression_reason": self.suppression_reason,
            "last_notification_at": self.last_notification_at,
        }


class CookMonitor:
    """Observe registered nodes without initiating any Houdini cook."""

    def __init__(
        self,
        storage: Any,
        settings: dict[str, Any] | None = None,
        notifications: Any | None = None,
        hou_module: Any | None = None,
        qt_core: Any | None = None,
        timer_parent: Any | None = None,
    ) -> None:
        self.storage = storage
        self.settings = settings if settings is not None else {}
        self._enabled = bool(self.settings.get("monitor_enabled", True))
        self.notifications = notifications
        self.hou = hou_module
        self.qt_core = qt_core
        self.timer_parent = timer_parent

        self._registry: dict[str, list[dict[str, Any]]] = storage.load_monitor_registry()
        # Untitled registrations belong to the current process only.
        self._registry.pop("__untitled__", None)
        self._hip_key = "__untitled__"
        self._entries: list[MonitorRegistration] = []
        self._snapshots: dict[str, NodeSnapshot] = {}
        self._cook_started_at: dict[str, float] = {}
        self._last_notified: dict[str, tuple[Any, ...]] = {}
        self._callbacks: dict[str, list[tuple[str, Any, Any, Any]]] = {}
        self._listeners: list[ChangeCallback] = []
        self._timer: Any | None = None
        self._started = False
        self._suspend_depth = 0
        self._playback_suppressed = False
        self.last_suppression_reason = ""

        self.set_current_hip(self._current_hip_path(), persist=False)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def suspended(self) -> bool:
        return self._suspend_depth > 0

    @property
    def registrations(self) -> tuple[MonitorRegistration, ...]:
        return tuple(self._entries)

    def get_notification_state(
        self,
        registration_or_id: MonitorRegistration | str | None = None,
    ) -> dict[str, Any]:
        """Return live delivery/suppression state for diagnostics and UI."""
        if registration_or_id is None:
            return {
                "monitor_enabled": self.enabled,
                "suspended": self.suspended,
                "last_suppression_reason": self.last_suppression_reason,
                "registrations": [
                    self._registration_notification_state(item)
                    for item in self._entries
                ],
            }
        registration = self._resolve(registration_or_id)
        return (
            self._registration_notification_state(registration)
            if registration is not None
            else {}
        )

    notification_status = get_notification_state

    def subscribe(self, callback: ChangeCallback) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def start(self) -> None:
        """Start UI polling and attach event callbacks when available."""
        if self._started:
            return
        self._started = True
        self._ensure_modules()
        current_path = self._current_hip_path()
        current_key = normalized_hip_key(current_path, self._is_new_file())
        if current_key != self._hip_key:
            self.set_current_hip(current_path, persist=False)
        self._reattach_all()
        self.refresh_baselines()
        self._ensure_timer()
        self._update_timer_state()

    def stop(self) -> None:
        """Stop polling and detach callbacks without changing registrations."""
        self._started = False
        if self._timer is not None:
            self._timer.stop()
        self._detach_all()

    def close(self) -> None:
        self.stop()
        self._persist()

    def set_global_enabled(self, enabled: bool) -> None:
        was_enabled = self.enabled
        self._enabled = bool(enabled)
        self.settings["monitor_enabled"] = self._enabled
        if enabled and not was_enabled:
            self.refresh_baselines()
        self._update_timer_state()
        for registration in self._entries:
            if not registration.enabled:
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "registration_disabled",
                )
            elif registration.status != "Missing":
                registration.status = "Watching" if enabled else "Disabled"
                self._set_notification_state(
                    registration,
                    "ready" if enabled else "suppressed",
                    "" if enabled else "monitor_disabled",
                )
                self._emit(registration, "state")

    def update_settings(self, settings: dict[str, Any]) -> None:
        was_enabled = self.enabled
        self.settings = settings
        self._enabled = bool(settings.get("monitor_enabled", True))
        if self._enabled and not was_enabled:
            self.refresh_baselines()
        if self._timer is not None:
            self._timer.setInterval(self._poll_interval_ms())
        self._update_timer_state()
        if self._enabled != was_enabled:
            for registration in self._entries:
                if not self._enabled:
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "monitor_disabled",
                    )
                elif not registration.enabled:
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "registration_disabled",
                    )
                elif not self.suspended and registration.status != "Missing":
                    self._set_notification_state(registration, "ready", "")

    def add_node(
        self,
        node_or_path: Any,
        display_name: str | None = None,
        enabled: bool = True,
    ) -> MonitorRegistration:
        node = node_or_path if not isinstance(node_or_path, str) else self._node(node_or_path)
        path = str(node_or_path) if isinstance(node_or_path, str) else str(_call(node, "path", ""))
        if not path:
            raise ValueError("A valid Houdini node path is required.")
        existing = self.find(path)
        if existing is not None:
            return existing

        name = display_name or (_call(node, "name", None) if node is not None else None)
        node_type = self._node_type_name(node)
        notification_state = "ready"
        suppression_reason = ""
        if not enabled:
            notification_state = "suppressed"
            suppression_reason = "registration_disabled"
        elif node is None:
            notification_state = "suppressed"
            suppression_reason = "node_missing"
        elif not self.enabled:
            notification_state = "suppressed"
            suppression_reason = "monitor_disabled"
        elif self.suspended:
            notification_state = "suppressed"
            suppression_reason = "queue_suspended"
        registration = MonitorRegistration(
            display_name=str(name or path.rsplit("/", 1)[-1] or path),
            node_path=path,
            enabled=bool(enabled),
            node_type=node_type,
            monitor_method=self._detect_method(node),
            status="Watching" if node is not None and enabled else ("Disabled" if not enabled else "Missing"),
            notification_state=notification_state,
            suppression_reason=suppression_reason,
        )
        self._entries.append(registration)
        if node is not None:
            self._snapshots[registration.id] = self._snapshot(node)
            self._sync_snapshot_fields(registration, self._snapshots[registration.id])
            self._attach_callbacks(registration, node)
        self._persist()
        self._emit(registration, "added")
        return registration

    def add_selected_nodes(self) -> list[MonitorRegistration]:
        if self.hou is None:
            return []
        try:
            selected = tuple(self.hou.selectedNodes())
        except Exception:
            return []
        return [self.add_node(node) for node in selected]

    def remove(self, registration_or_id: MonitorRegistration | str) -> bool:
        registration = self._resolve(registration_or_id)
        if registration is None:
            return False
        self._detach_callbacks(registration.id)
        self._entries.remove(registration)
        self._snapshots.pop(registration.id, None)
        self._cook_started_at.pop(registration.id, None)
        self._last_notified.pop(registration.id, None)
        self._persist()
        self._emit(registration, "removed")
        return True

    def set_enabled(self, registration_or_id: MonitorRegistration | str, enabled: bool) -> bool:
        registration = self._resolve(registration_or_id)
        if registration is None:
            return False
        registration.enabled = bool(enabled)
        registration.status = "Watching" if enabled and self._node(registration.node_path) else (
            "Disabled" if not enabled else "Missing"
        )
        if enabled:
            node = self._node(registration.node_path)
            if node is not None:
                self._snapshots[registration.id] = self._snapshot(node)
                self._attach_callbacks(registration, node)
                self._set_notification_state(
                    registration,
                    "ready" if self.enabled and not self.suspended else "suppressed",
                    (
                        ""
                        if self.enabled and not self.suspended
                        else ("monitor_disabled" if not self.enabled else "queue_suspended")
                    ),
                )
            else:
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "node_missing",
                )
        else:
            self._detach_callbacks(registration.id)
            self._set_notification_state(
                registration,
                "suppressed",
                "registration_disabled",
            )
        self._persist()
        self._emit(registration, "state")
        return True

    def update_path(
        self,
        registration_or_id: MonitorRegistration | str,
        node_path: str,
    ) -> bool:
        """Resolve a missing registration to a replacement node path."""
        registration = self._resolve(registration_or_id)
        if registration is None:
            return False
        node = self._node(node_path)
        if node is None:
            raise ValueError(f"Node not found: {node_path}")
        duplicate = self.find(node_path)
        if duplicate is not None and duplicate is not registration:
            raise ValueError(f"Node is already registered: {node_path}")
        self._detach_callbacks(registration.id)
        registration.node_path = str(_call(node, "path", node_path))
        registration.display_name = str(_call(node, "name", registration.display_name))
        registration.node_type = self._node_type_name(node)
        registration.monitor_method = self._detect_method(node)
        registration.status = "Watching" if registration.enabled else "Disabled"
        snapshot = self._snapshot(node)
        self._snapshots[registration.id] = snapshot
        self._sync_snapshot_fields(registration, snapshot)
        if registration.enabled:
            self._attach_callbacks(registration, node)
            self._set_notification_state(
                registration,
                "ready" if self.enabled and not self.suspended else "suppressed",
                (
                    ""
                    if self.enabled and not self.suspended
                    else ("monitor_disabled" if not self.enabled else "queue_suspended")
                ),
            )
        else:
            self._set_notification_state(
                registration,
                "suppressed",
                "registration_disabled",
            )
        self._persist()
        self._emit(registration, "path_changed")
        return True

    # Explicit aliases keep the service convenient for panel/controller
    # facades without duplicating monitor behavior.
    set_registration_enabled = set_enabled
    replace_node = update_path
    locate_replacement = update_path
    edit_path = update_path

    def go_to_node(self, node_path: str) -> Any:
        from .navigation import go_to_node

        return go_to_node(node_path, self.hou)

    def find(self, node_path: str) -> MonitorRegistration | None:
        return next((item for item in self._entries if item.node_path == node_path), None)

    def suspend(self) -> None:
        """Suspend all observation while Queue Runner owns notifications."""
        self._suspend_depth += 1
        self._update_timer_state()
        if self._suspend_depth == 1:
            for registration in self._entries:
                if registration.enabled:
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "queue_suspended",
                    )

    def resume(self, refresh_baselines: bool = True) -> None:
        """Resume monitoring, refreshing baselines before the timer can fire."""
        if self._suspend_depth:
            self._suspend_depth -= 1
        if self._suspend_depth:
            return
        if refresh_baselines:
            self.refresh_baselines()
        self._update_timer_state()
        for registration in self._entries:
            if not registration.enabled:
                continue
            if not self.enabled:
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "monitor_disabled",
                )
            elif registration.status == "Missing":
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "node_missing",
                )
            else:
                self._set_notification_state(registration, "ready", "")

    def refresh_baselines(self) -> None:
        """Forget cook deltas caused while monitoring was suspended."""
        self._cook_started_at.clear()
        for registration in self._entries:
            if not registration.enabled:
                continue
            node = self._node(registration.node_path)
            if node is None:
                registration.status = "Missing"
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "node_missing",
                )
                continue
            snapshot = self._snapshot(node)
            self._snapshots[registration.id] = snapshot
            self._sync_snapshot_fields(registration, snapshot)
            registration.status = "Cooking" if snapshot.is_cooking else "Watching"

    def poll_once(self) -> list[MonitorRegistration]:
        """Poll only registered nodes and return registrations that changed."""
        if not self.enabled:
            for registration in self._entries:
                if registration.enabled:
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "monitor_disabled",
                    )
            return []
        if self.suspended:
            for registration in self._entries:
                if registration.enabled:
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "queue_suspended",
                    )
            return []
        if self._playback_is_active() and bool(
            self.settings.get("suppress_monitor_during_playback", True)
        ):
            # Advance baselines while playback is active so its cooks do not
            # become a delayed notification as soon as playback stops.
            self._playback_suppressed = True
            for registration in self._entries:
                if registration.enabled:
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "playback_active",
                    )
            self.refresh_baselines()
            return []
        if self._playback_suppressed:
            self._playback_suppressed = False
            for registration in self._entries:
                if registration.enabled and registration.status != "Missing":
                    self._set_notification_state(registration, "ready", "")

        changed: list[MonitorRegistration] = []
        persist = False
        for registration in tuple(self._entries):
            if not registration.enabled:
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "registration_disabled",
                )
                continue
            node = self._node(registration.node_path)
            if node is None:
                if registration.status != "Missing":
                    registration.status = "Missing"
                    self._set_notification_state(
                        registration,
                        "suppressed",
                        "node_missing",
                    )
                    changed.append(registration)
                    persist = True
                    self._emit(registration, "missing")
                continue

            if registration.status == "Missing":
                registration.status = "Watching"
                self._set_notification_state(registration, "ready", "")
                self._attach_callbacks(registration, node)
                self._emit(registration, "found")
                persist = True

            current = self._snapshot(node)
            previous = self._snapshots.get(registration.id)
            self._snapshots[registration.id] = current
            if previous is None:
                self._sync_snapshot_fields(registration, current)
                continue

            if current.is_cooking:
                if not previous.is_cooking:
                    self._cook_started_at[registration.id] = current.sampled_at
                if registration.status != "Cooking":
                    registration.status = "Cooking"
                    changed.append(registration)
                    self._emit(registration, "cooking")
                continue

            completed = previous.is_cooking or self._cook_delta(previous, current)
            if completed:
                duration = self._completion_duration(registration.id, current)
                self._record_completion(registration, current, duration, source="poll")
                changed.append(registration)
                persist = True
            elif registration.status == "Cooking":
                registration.status = "Watching"
                changed.append(registration)
                self._emit(registration, "state")

            self._sync_snapshot_fields(registration, current)

        if persist:
            self._persist()
        return changed

    def set_current_hip(
        self,
        hip_path: str,
        is_new_file: bool | None = None,
        persist: bool = True,
    ) -> None:
        """Switch the live registration set after a HIP load or clear event."""
        new_key = normalized_hip_key(
            hip_path,
            self._is_new_file() if is_new_file is None else bool(is_new_file),
        )
        if new_key == self._hip_key and self._entries:
            return
        if persist:
            self._persist()
        self._detach_all()
        old_key = self._hip_key
        self._hip_key = new_key
        if old_key == "__untitled__" and new_key != "__untitled__":
            # Opening another HIP discards temporary untitled registrations.
            # A first Save As must call ``handle_hip_saved`` instead.
            self._registry.pop("__untitled__", None)
        raw_entries = self._registry.get(new_key, [])
        self._entries = [
            MonitorRegistration.from_dict(value)
            for value in raw_entries
            if isinstance(value, dict)
        ]
        for registration in self._entries:
            if not registration.enabled:
                registration.notification_state = "suppressed"
                registration.suppression_reason = "registration_disabled"
            elif not self.enabled:
                registration.notification_state = "suppressed"
                registration.suppression_reason = "monitor_disabled"
        self.last_suppression_reason = next(
            (
                item.suppression_reason
                for item in reversed(self._entries)
                if item.suppression_reason
            ),
            "",
        )
        self._snapshots.clear()
        self._cook_started_at.clear()
        self._last_notified.clear()
        if self._started:
            self._reattach_all()
            self.refresh_baselines()
        for registration in self._entries:
            self._emit(registration, "loaded")

    def handle_hip_saved(self, hip_path: str) -> None:
        """Carry live registrations into a first save or Save As destination."""
        new_key = normalized_hip_key(hip_path, False)
        if new_key == self._hip_key:
            self._persist()
            return
        old_key = self._hip_key
        self._persist()
        existing = [
            MonitorRegistration.from_dict(value)
            for value in self._registry.get(new_key, [])
            if isinstance(value, dict)
        ]
        known_paths = {item.node_path for item in self._entries}
        self._entries.extend(
            item for item in existing if item.node_path not in known_paths
        )
        if old_key == "__untitled__":
            self._registry.pop("__untitled__", None)
        self._hip_key = new_key
        self._persist()
        for registration in self._entries:
            self._emit(registration, "hip_saved")

    def _ensure_modules(self) -> None:
        if self.hou is None:
            self.hou = _optional_import("hou")
        if self.qt_core is None:
            pyside = _optional_import("PySide6")
            self.qt_core = getattr(pyside, "QtCore", None) if pyside else None

    def _ensure_timer(self) -> None:
        if self._timer is not None or self.qt_core is None:
            return
        timer_type = getattr(self.qt_core, "QTimer", None)
        if timer_type is None:
            return
        self._timer = timer_type(self.timer_parent)
        self._timer.setInterval(self._poll_interval_ms())
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self.poll_once)

    def _update_timer_state(self) -> None:
        if self._timer is None:
            return
        should_run = self._started and self.enabled and not self.suspended
        if should_run and not self._timer.isActive():
            self._timer.start()
        elif not should_run and self._timer.isActive():
            self._timer.stop()

    def _poll_interval_ms(self) -> int:
        try:
            return max(250, int(self.settings.get("monitor_poll_interval_ms", 750)))
        except (TypeError, ValueError):
            return 750

    def _node(self, path: str) -> Any | None:
        if self.hou is None:
            return None
        try:
            return self.hou.node(path)
        except Exception:
            return None

    def _snapshot(self, node: Any) -> NodeSnapshot:
        count = _call(node, "cookCount")
        duration = _call(node, "lastCookTime")
        errors = _call(node, "errors", ()) or ()
        warnings = _call(node, "warnings", ()) or ()
        cooking = _call(node, "isCooking", False)
        try:
            count = int(count) if count is not None else None
        except (TypeError, ValueError):
            count = None
        try:
            # HOM reports hou.OpNode.lastCookTime() in milliseconds.
            duration = float(duration) / 1000.0 if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        return NodeSnapshot(
            cook_count=count,
            last_cook_time=duration,
            errors=tuple(str(item) for item in errors),
            warnings=tuple(str(item) for item in warnings),
            is_cooking=bool(cooking),
        )

    @staticmethod
    def _cook_delta(previous: NodeSnapshot, current: NodeSnapshot) -> bool:
        if (
            previous.cook_count is not None
            and current.cook_count is not None
            and previous.cook_count != current.cook_count
        ):
            return True
        return (
            previous.last_cook_time is not None
            and current.last_cook_time is not None
            and previous.last_cook_time != current.last_cook_time
        )

    def _completion_duration(self, registration_id: str, snapshot: NodeSnapshot) -> float:
        started = self._cook_started_at.pop(registration_id, None)
        if started is not None:
            return max(0.0, snapshot.sampled_at - started)
        return max(0.0, float(snapshot.last_cook_time or 0.0))

    def _record_completion(
        self,
        registration: MonitorRegistration,
        snapshot: NodeSnapshot,
        duration: float,
        source: str,
        forced_result: str | None = None,
    ) -> None:
        result = forced_result or (
            "failed" if snapshot.errors else ("warning" if snapshot.warnings else "completed")
        )
        registration.status = "Watching"
        registration.last_duration_seconds = duration
        registration.last_completed_at = now_iso()
        registration.last_result = result
        self._sync_snapshot_fields(registration, snapshot)

        signature = (
            snapshot.cook_count,
            round(float(snapshot.last_cook_time or 0.0), 6),
            result,
        )
        should_notify = self._last_notified.get(registration.id) != signature
        self._last_notified[registration.id] = signature
        if not should_notify:
            self._set_notification_state(
                registration,
                "suppressed",
                "duplicate_cook",
            )
        elif not self._passes_threshold(duration):
            self._set_notification_state(
                registration,
                "suppressed",
                "below_minimum_duration",
            )
        elif not self._notification_enabled(registration, result):
            self._set_notification_state(
                registration,
                "suppressed",
                f"{result}_notifications_disabled",
            )
        else:
            delivered = self._notify(
                registration,
                result,
                duration,
                snapshot.errors,
                snapshot.warnings,
            )
            if delivered is None:
                self._set_notification_state(
                    registration,
                    "suppressed",
                    "notification_service_unavailable",
                )
            else:
                merged = bool(getattr(delivered, "merged", False))
                registration.last_notification_at = now_iso()
                self._set_notification_state(
                    registration,
                    "merged" if merged else "notified",
                    "rapid_notification_merged" if merged else "",
                )
        self._emit(registration, "completed")

    def _passes_threshold(self, duration: float) -> bool:
        try:
            threshold = float(self.settings.get("minimum_cook_duration_seconds", 5.0))
        except (TypeError, ValueError):
            threshold = 5.0
        return duration >= max(0.0, threshold)

    @staticmethod
    def _notification_enabled(registration: MonitorRegistration, result: str) -> bool:
        if result == "failed":
            return registration.notify_on_failure
        if result == "warning":
            return registration.notify_on_warning
        return registration.notify_on_complete

    def _notify(
        self,
        registration: MonitorRegistration,
        result: str,
        duration: float,
        errors: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> Any | None:
        if self.notifications is None:
            return None
        name = registration.display_name or registration.node_path
        details = errors if result == "failed" else warnings
        message = f"{name} finished in {duration:.1f} seconds."
        if details:
            message = f"{message} {details[0]}"
        method = {
            "failed": "error",
            "warning": "warning",
            "completed": "completed",
        }[result]
        callback = getattr(self.notifications, method, None)
        if callable(callback):
            return callback(
                title="Cook Failed" if result == "failed" else "Cook Completed",
                message=message,
                node_path=registration.node_path,
                duration_seconds=duration,
            )
        return None

    def _attach_callbacks(self, registration: MonitorRegistration, node: Any) -> None:
        self._detach_callbacks(registration.id)
        attached: list[tuple[str, Any, Any, Any]] = []

        event_type = getattr(self.hou, "nodeEventType", None) if self.hou is not None else None
        lifecycle_events = tuple(
            event
            for event in (
                getattr(event_type, "NameChanged", None),
                getattr(event_type, "BeingDeleted", None),
            )
            if event is not None
        )
        if lifecycle_events and hasattr(node, "addEventCallback"):
            callback = (
                lambda *args, _id=registration.id, **kwargs:
                self._on_node_event(_id, *args, **kwargs)
            )
            try:
                node.addEventCallback(lifecycle_events, callback)
                attached.append(("node", node, callback, lifecycle_events))
            except Exception:
                pass

        if registration.monitor_method == "rop" and hasattr(node, "addRenderEventCallback"):
            callback = (
                lambda *args, _id=registration.id, **kwargs:
                self._on_rop_event(_id, *args, **kwargs)
            )
            try:
                node.addRenderEventCallback(callback)
                attached.append(("rop", node, callback, None))
            except Exception:
                pass

        if registration.monitor_method == "top":
            target = _call(node, "getPDGNode")
            target = target or node
            callback = (
                lambda *args, _id=registration.id, **kwargs:
                self._defer_pdg_event(_id, *args, **kwargs)
            )
            add_handler = getattr(target, "addEventHandler", None)
            if callable(add_handler):
                token = None
                event_types = self._pdg_event_types()
                try:
                    token = (
                        add_handler(callback, event_types)
                        if event_types
                        else add_handler(callback)
                    )
                except Exception:
                    try:
                        token = add_handler(callback)
                    except Exception:
                        token = None
                if token is not None:
                    attached.append(("pdg", target, callback, token))

        if attached:
            self._callbacks[registration.id] = attached

    def _detach_callbacks(self, registration_id: str) -> None:
        for kind, target, callback, extra in self._callbacks.pop(registration_id, []):
            try:
                if kind == "node":
                    target.removeEventCallback(extra, callback)
                elif kind == "rop":
                    target.removeRenderEventCallback(callback)
                elif kind == "pdg":
                    target.removeEventHandler(extra)
            except Exception:
                pass

    def _detach_all(self) -> None:
        for registration_id in tuple(self._callbacks):
            self._detach_callbacks(registration_id)

    def _reattach_all(self) -> None:
        for registration in self._entries:
            if registration.enabled:
                node = self._node(registration.node_path)
                if node is not None:
                    self._attach_callbacks(registration, node)

    def _on_node_event(self, registration_id: str, *args: Any, **kwargs: Any) -> None:
        registration = self._resolve(registration_id)
        if registration is None:
            return
        event = kwargs.get("event_type")
        if event is None:
            event = next(
                (item for item in args if "changed" in _event_name(item) or "deleted" in _event_name(item)),
                None,
            )
        name = _event_name(event)
        node = kwargs.get("node")
        if node is None:
            node = next((item for item in args if hasattr(item, "path")), None)

        if "deleted" in name:
            registration.status = "Missing"
            self._set_notification_state(
                registration,
                "suppressed",
                "node_missing",
            )
            self._snapshots.pop(registration.id, None)
            self._persist()
            self._emit(registration, "missing")
            return
        if "namechanged" in name or "changed" in name:
            new_path = str(_call(node, "path", registration.node_path))
            if new_path and new_path != registration.node_path:
                registration.node_path = new_path
                registration.display_name = str(_call(node, "name", registration.display_name))
                registration.node_type = self._node_type_name(node)
                self._persist()
                self._emit(registration, "renamed")

    def _on_rop_event(self, registration_id: str, *args: Any, **kwargs: Any) -> None:
        if not self.enabled or self.suspended:
            return
        registration = self._resolve(registration_id)
        if registration is None or not registration.enabled:
            return
        event = kwargs.get("event_type")
        if event is None:
            event = next((item for item in args if "render" in _event_name(item)), None)
        name = _event_name(event)
        if any(token in name for token in ("prerender", "renderstart", "started")):
            self._cook_started_at[registration_id] = time.monotonic()
            registration.status = "Cooking"
            self._emit(registration, "cooking")
            return
        if not any(
            token in name
            for token in ("postrender", "rendercomplete", "completed", "rendererror", "failed", "cancel")
        ):
            return
        node = self._node(registration.node_path)
        snapshot = self._snapshot(node) if node is not None else NodeSnapshot()
        forced = (
            "failed"
            if any(token in name for token in ("error", "failed", "cancel"))
            else None
        )
        duration = self._completion_duration(registration_id, snapshot)
        self._snapshots[registration_id] = snapshot
        self._record_completion(registration, snapshot, duration, "rop", forced)
        self._persist()

    def _on_pdg_event_ui(self, registration_id: str, *args: Any, **kwargs: Any) -> None:
        if not self.enabled or self.suspended:
            return
        registration = self._resolve(registration_id)
        if registration is None or not registration.enabled:
            return
        event = kwargs.get("event_type") or kwargs.get("event")
        if event is None and args:
            event = args[-1]
        name = _event_name(event)
        if "cookstart" in name or "cookstarted" in name:
            self._cook_started_at[registration_id] = time.monotonic()
            registration.status = "Cooking"
            self._emit(registration, "cooking")
            return
        if not any(
            token in name
            for token in ("cookcomplete", "cookerror", "cookfail", "cookcancel", "completed")
        ):
            return
        node = self._node(registration.node_path)
        snapshot = self._snapshot(node) if node is not None else NodeSnapshot()
        forced = (
            "failed"
            if any(token in name for token in ("error", "fail", "cancel"))
            else None
        )
        duration = self._completion_duration(registration_id, snapshot)
        self._snapshots[registration_id] = snapshot
        self._record_completion(registration, snapshot, duration, "pdg", forced)
        self._persist()

    def _defer_pdg_event(self, registration_id: str, *args: Any, **kwargs: Any) -> None:
        """Copy the event enum before the PDG worker callback returns."""
        event = kwargs.get("event_type") or kwargs.get("event")
        if event is None and args:
            event = args[-1]
        event_type = _call(event, "type")
        safe_event = event_type if event_type is not None else event
        self._post_ui(
            lambda registration_id=registration_id, safe_event=safe_event:
            self._on_pdg_event_ui(registration_id, safe_event)
        )

    def _pdg_event_types(self) -> list[Any]:
        pdg = _optional_import("pdg")
        event_type = getattr(pdg, "EventType", None) if pdg is not None else None
        return [
            value
            for value in (
                getattr(event_type, "CookStart", None),
                getattr(event_type, "CookComplete", None),
                getattr(event_type, "CookError", None),
                getattr(event_type, "CookCancel", None),
            )
            if value is not None
        ]

    def _post_ui(self, callback: Callable[[], None]) -> None:
        available = (
            getattr(self.hou, "isUIAvailable", None)
            if self.hou is not None
            else None
        )
        if not callable(available):
            callback()
            return
        try:
            if not bool(available()):
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

    def _playback_is_active(self) -> bool:
        playbar = getattr(self.hou, "playbar", None) if self.hou is not None else None
        return bool(_call(playbar, "isPlaying", False)) if playbar is not None else False

    def _current_hip_path(self) -> str:
        hip_file = getattr(self.hou, "hipFile", None) if self.hou is not None else None
        return str(_call(hip_file, "path", "") or "")

    def _is_new_file(self) -> bool:
        hip_file = getattr(self.hou, "hipFile", None) if self.hou is not None else None
        return bool(_call(hip_file, "isNewFile", not self._current_hip_path()))

    def _detect_method(self, node: Any | None) -> str:
        if node is None:
            return "generic"
        category = self._node_category_name(node).lower()
        type_name = self._node_type_name(node).lower()
        if "top" in category or type_name.startswith("topnet") or hasattr(node, "cookWorkItems"):
            return "top"
        rop_type = getattr(self.hou, "RopNode", None) if self.hou is not None else None
        if (rop_type is not None and isinstance(node, rop_type)) or "driver" in category:
            return "rop"
        return "generic"

    @staticmethod
    def _node_type_name(node: Any | None) -> str:
        if node is None:
            return ""
        node_type = _call(node, "type")
        return str(_call(node_type, "nameWithCategory", None) or _call(node_type, "name", "") or "")

    @staticmethod
    def _node_category_name(node: Any | None) -> str:
        if node is None:
            return ""
        node_type = _call(node, "type")
        category = _call(node_type, "category")
        return str(_call(category, "name", "") or "")

    @staticmethod
    def _sync_snapshot_fields(
        registration: MonitorRegistration,
        snapshot: NodeSnapshot,
    ) -> None:
        registration.last_cook_count = snapshot.cook_count
        registration.last_cook_time = snapshot.last_cook_time

    def _set_notification_state(
        self,
        registration: MonitorRegistration,
        state: str,
        reason: str,
    ) -> bool:
        state = str(state)
        reason = str(reason)
        changed = (
            registration.notification_state != state
            or registration.suppression_reason != reason
        )
        registration.notification_state = state
        registration.suppression_reason = reason
        if reason:
            self.last_suppression_reason = reason
        if changed:
            self._emit(registration, "notification_state")
        return changed

    def _registration_notification_state(
        self,
        registration: MonitorRegistration,
    ) -> dict[str, Any]:
        try:
            threshold = max(
                0.0,
                float(self.settings.get("minimum_cook_duration_seconds", 5.0)),
            )
        except (TypeError, ValueError):
            threshold = 5.0
        return {
            "id": registration.id,
            "node_path": registration.node_path,
            "state": registration.notification_state,
            "suppression_reason": registration.suppression_reason,
            "last_notification_at": registration.last_notification_at,
            "last_duration_seconds": registration.last_duration_seconds,
            "minimum_duration_seconds": threshold,
            "notify_on_complete": registration.notify_on_complete,
            "notify_on_warning": registration.notify_on_warning,
            "notify_on_failure": registration.notify_on_failure,
        }

    def _resolve(
        self,
        registration_or_id: MonitorRegistration | str,
    ) -> MonitorRegistration | None:
        if isinstance(registration_or_id, MonitorRegistration):
            return registration_or_id if registration_or_id in self._entries else None
        return next((item for item in self._entries if item.id == registration_or_id), None)

    def _persist(self) -> None:
        self._registry[self._hip_key] = [item.to_dict() for item in self._entries]
        if self._hip_key == "__untitled__":
            return
        self.storage.save_monitor_registry(self._registry)

    def _emit(self, registration: MonitorRegistration, event: str) -> None:
        for callback in tuple(self._listeners):
            try:
                callback(registration, event)
            except Exception:
                pass
