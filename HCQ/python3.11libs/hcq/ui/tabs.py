"""The five primary HCQ panel tabs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtWidgets

from . import text
from .bridge import call, item_value, manager_collection, mapping, sequence, value
from .common import (
    ReorderTable,
    compact_button_row,
    make_button,
    set_row,
    show_error,
    show_warning,
)
from .dialogs import (
    ImportPreviewDialog,
    MissingNodesDialog,
    PreflightDialog,
    RunConfirmDialog,
)
from .editors import QueueEditorDialog


_OPEN_QUEUE_EDITORS: dict[tuple[int, str], QueueEditorDialog] = {}


def _identifier(item: Any) -> str:
    return str(item_value(item, "id", item_value(item, "queue_id", "")))


def _cpu_label(source: Any) -> str:
    cpu = item_value(source, "cpu", {})
    mode = str(item_value(cpu, "mode", "current"))
    amount = item_value(cpu, "value", None)
    labels = {
        "current": "Current",
        "all": "All Threads",
        "inherit": "Queue Setting",
        "single": "Single Thread",
    }
    if mode == "threads":
        return f"{amount} Threads"
    if mode == "reserve":
        return f"Reserve {amount}"
    return labels.get(mode, mode.replace("_", " ").title())


def _show_navigation_result(
    parent: QtWidgets.QWidget,
    result: Any,
    fallback_message: str,
) -> bool:
    """Show failed NavigationResult messages while tolerating facade values."""
    if result is None:
        show_warning(parent, fallback_message)
        return False
    success = item_value(result, "success", None)
    if success is False:
        message = str(item_value(result, "message", fallback_message))
        show_warning(parent, message or fallback_message)
        return False
    return True


def _history_items(manager: Any) -> list[Any]:
    storage = value(manager, "storage")
    for owner in (manager, storage):
        result = call(
            owner,
            (
                "list_history",
                "load_history",
                "history",
                "get_history",
                "read_history",
            ),
        )
        if result is not None:
            return sequence(result)
    return sequence(value(manager, "history", []))


def _interactive_import_queues(
    manager: Any,
    path: str,
    parent: QtWidgets.QWidget,
) -> list[Any]:
    """Preview, remap, resolve, validate, and then import without auto-running."""
    from hcq.import_export import missing_node_paths, remap_document_paths
    from hcq.validation import parse_queue_document

    with open(path, "r", encoding="utf-8") as handle:
        original = json.load(handle)
    preview = ImportPreviewDialog(original, parent)
    if preview.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return []
    selected = preview.selected_queues()
    if not selected:
        return []
    document = copy.deepcopy(original)
    document["queues"] = [copy.deepcopy(mapping(queue)) for queue in selected]
    for source, target in preview.path_mappings:
        document = remap_document_paths(document, source, target)
    queues = parse_queue_document(document)
    hou_module = value(manager, "hou")
    node_lookup = getattr(hou_module, "node", None)
    missing = (
        missing_node_paths(queues, node_lookup)
        if callable(node_lookup)
        else []
    )
    if missing:
        resolution = MissingNodesDialog(queues, missing, parent)
        if resolution.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return []
        resolution.apply_resolutions()
    document["queues"] = [queue.to_dict() for queue in queues]
    imported = call(manager, "import_queue_document", document, default=[])
    return sequence(imported)


class MonitorTab(QtWidgets.QWidget):
    def __init__(self, manager: Any, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        layout = QtWidgets.QVBoxLayout(self)
        self.toggle = QtWidgets.QCheckBox("Monitoring Enabled")
        self.toggle.toggled.connect(self._set_global_enabled)
        layout.addWidget(self.toggle)
        self.notification_summary = QtWidgets.QLabel()
        self.notification_summary.setWordWrap(True)
        layout.addWidget(self.notification_summary)
        add_selected = make_button(text.ADD_SELECTED_NODES, self._add_selected)
        add_path = make_button(text.ADD_BY_PATH, self._add_path)
        remove = make_button(text.REMOVE, self._remove)
        refresh = make_button(text.REFRESH, self.refresh)
        layout.addLayout(compact_button_row(add_selected, add_path, remove, refresh))
        self.table = ReorderTable(
            [
                "On",
                "Display Name",
                "Node Path",
                "Node Type",
                "Method",
                "Status",
                "Duration",
                "Last Cook",
                "Result",
                "Notification",
            ]
        )
        self.table.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.table.itemChanged.connect(self._item_enabled)
        self.table.itemDoubleClicked.connect(lambda *_: self._go_to_node())
        layout.addWidget(self.table, 1)
        enable = make_button(text.ENABLE, lambda: self._set_selected(True))
        disable = make_button(text.DISABLE, lambda: self._set_selected(False))
        go_to = make_button(text.GO_TO_NODE, self._go_to_node)
        locate = make_button(text.LOCATE_REPLACEMENT, self._locate)
        edit_path = make_button(text.EDIT_PATH, self._edit_path)
        layout.addLayout(
            compact_button_row(enable, disable, go_to, locate, edit_path)
        )
        self.refresh()

    def _monitor(self) -> Any:
        return value(self.manager, "monitor")

    def _registrations(self) -> list[Any]:
        monitor = self._monitor()
        for name in ("registrations", "nodes", "items"):
            result = value(monitor, name)
            if callable(result):
                try:
                    result = result()
                except Exception:
                    continue
            if result is not None:
                if isinstance(result, dict):
                    return list(result.values())
                return sequence(result)
        result = call(monitor, ("list_registrations", "get_registrations"))
        return sequence(result)

    def refresh(self) -> None:
        settings = value(self.manager, "settings", {}) or {}
        enabled = bool(
            settings.get("monitor_enabled", True)
            if isinstance(settings, dict)
            else item_value(settings, "monitor_enabled", True)
        )
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.blockSignals(False)
        threshold = float(
            settings.get("minimum_cook_duration_seconds", 5.0)
            if isinstance(settings, dict)
            else item_value(
                settings, "minimum_cook_duration_seconds", 5.0
            )
        )
        self.notification_summary.setText(
            (
                "Notifications are enabled"
                if enabled
                else "Notifications are suppressed because Monitor is disabled"
            )
            + f" · Minimum Cook Duration: {threshold:g} s"
        )
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, registration in enumerate(self._registrations()):
            status = item_value(
                registration,
                "status",
                "Missing" if item_value(registration, "missing", False) else "Watching",
            )
            notification = self._notification_label(
                registration, threshold
            )
            duration_value = item_value(
                registration,
                "last_duration_seconds",
                item_value(registration, "last_duration", None),
            )
            if duration_value is None:
                duration_label = "--"
            else:
                duration_seconds = float(duration_value)
                duration_label = (
                    f"{duration_seconds * 1000.0:.1f} ms"
                    if duration_seconds < 1.0
                    else f"{duration_seconds:.1f} s"
                )
            last_cook = item_value(
                registration,
                "last_completed_at",
                item_value(registration, "last_cook", None),
            )
            set_row(
                self.table,
                row,
                [
                    "",
                    item_value(
                        registration,
                        "display_name",
                        item_value(registration, "name", ""),
                    ),
                    item_value(registration, "node_path", item_value(registration, "path", "")),
                    item_value(registration, "node_type", ""),
                    item_value(registration, "method", "Polling"),
                    str(status).title(),
                    duration_label,
                    last_cook or "--",
                    str(item_value(registration, "last_result", "--")).title(),
                    notification,
                ],
                registration,
                checked=bool(item_value(registration, "enabled", True)),
            )
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()

    @staticmethod
    def _notification_label(registration: Any, threshold: float) -> str:
        state = str(
            item_value(registration, "notification_state", "ready")
        )
        reason = str(item_value(registration, "suppression_reason", ""))
        if state == "notified":
            return "Notified"
        if state == "merged":
            return "Merged with recent notification"
        if reason == "below_minimum_duration":
            duration = float(
                item_value(registration, "last_duration_seconds", 0.0) or 0.0
            )
            rendered = (
                f"{duration * 1000.0:.1f} ms"
                if duration < 1.0
                else f"{duration:.1f} s"
            )
            return f"Suppressed: {rendered} < {threshold:g} s"
        reasons = {
            "registration_disabled": "Suppressed: Row disabled",
            "monitor_disabled": "Suppressed: Monitor disabled",
            "playback_active": "Suppressed: Playback active",
            "queue_suspended": "Suppressed: Queue running",
            "duplicate_cook": "Suppressed: Duplicate cook",
            "node_missing": "Suppressed: Node missing",
            "completed_notifications_disabled": (
                "Suppressed: Completion notifications disabled"
            ),
            "warning_notifications_disabled": (
                "Suppressed: Warning notifications disabled"
            ),
            "failed_notifications_disabled": (
                "Suppressed: Failure notifications disabled"
            ),
            "notification_service_unavailable": (
                "Suppressed: Notification service unavailable"
            ),
        }
        if reason:
            return reasons.get(
                reason, f"Suppressed: {reason.replace('_', ' ').title()}"
            )
        return state.replace("_", " ").title()

    def _set_global_enabled(self, enabled: bool) -> None:
        settings = value(self.manager, "settings")
        if isinstance(settings, dict):
            settings["monitor_enabled"] = enabled
            call(self.manager, "save_settings")
        call(self._monitor(), ("set_enabled", "set_global_enabled"), enabled)
        call(self.manager, "notify_changed", "monitor")

    def _add_selected(self) -> None:
        result = call(
            self._monitor(),
            ("add_selected_nodes", "register_selected_nodes", "add_selected"),
        )
        if result is None:
            try:
                import hou

                nodes = hou.selectedNodes()
                for node in nodes:
                    call(
                        self._monitor(),
                        ("add_node", "register_node", "register"),
                        node.path(),
                    )
            except Exception:
                show_warning(self, "No Houdini nodes are selected.")
        call(self.manager, "notify_changed", "monitor")
        self.refresh()

    def _add_path(self) -> None:
        node_path, accepted = QtWidgets.QInputDialog.getText(
            self, text.ADD_BY_PATH, "Node Path"
        )
        if accepted and node_path.strip():
            call(
                self._monitor(),
                ("add_node", "register_node", "register"),
                node_path.strip(),
            )
            call(self.manager, "notify_changed", "monitor")
            self.refresh()

    def _remove(self) -> None:
        for registration in self.table.selected_objects():
            target = _identifier(registration) or str(
                item_value(registration, "node_path", item_value(registration, "path", ""))
            )
            call(
                self._monitor(),
                ("remove", "remove_node", "unregister_node", "unregister"),
                target,
            )
        call(self.manager, "notify_changed", "monitor")
        self.refresh()

    def _item_enabled(self, item: QtWidgets.QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        registration = item.data(QtCore.Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == QtCore.Qt.CheckState.Checked
        self._set_one(registration, enabled)

    def _set_one(self, registration: Any, enabled: bool) -> None:
        target = _identifier(registration) or str(
            item_value(registration, "node_path", item_value(registration, "path", ""))
        )
        result = call(
            self._monitor(),
            ("set_registration_enabled", "set_node_enabled", "set_enabled"),
            target,
            enabled,
        )
        if result is None:
            if isinstance(registration, dict):
                registration["enabled"] = enabled
            elif registration is not None:
                try:
                    registration.enabled = enabled
                except Exception:
                    pass

    def _set_selected(self, enabled: bool) -> None:
        for registration in self.table.selected_objects():
            self._set_one(registration, enabled)
        call(self.manager, "notify_changed", "monitor")
        self.refresh()

    def _go_to_node(self) -> None:
        registration = self.table.current_object()
        if registration is None:
            return
        path = str(
            item_value(registration, "node_path", item_value(registration, "path", ""))
        )
        navigation = value(self.manager, "navigation")
        result = call(navigation, "go_to_node", path)
        if result is None:
            result = call(
                self._monitor(), ("go_to_node", "navigate_to_node"), path
            )
        _show_navigation_result(self, result, f"Could not navigate to node: {path}")

    def _locate(self) -> None:
        registration = self.table.current_object()
        if registration is None:
            return
        try:
            import hou

            selected = hou.selectedNodes()
            replacement = selected[0].path() if len(selected) == 1 else ""
        except Exception:
            replacement = ""
        if not replacement:
            replacement, accepted = QtWidgets.QInputDialog.getText(
                self, text.LOCATE_REPLACEMENT, "Replacement Node Path"
            )
            if not accepted:
                return
        target = _identifier(registration) or item_value(registration, "node_path", "")
        call(
            self._monitor(),
            ("replace_node", "locate_replacement", "edit_path"),
            target,
            replacement,
        )
        self.refresh()

    def _edit_path(self) -> None:
        registration = self.table.current_object()
        if registration is None:
            return
        old_path = str(
            item_value(registration, "node_path", item_value(registration, "path", ""))
        )
        new_path, accepted = QtWidgets.QInputDialog.getText(
            self, text.EDIT_PATH, "Node Path", text=old_path
        )
        if accepted and new_path.strip() and new_path != old_path:
            target = _identifier(registration) or old_path
            call(
                self._monitor(),
                ("edit_path", "replace_node", "update_path"),
                target,
                new_path.strip(),
            )
            self.refresh()


class QueuesTab(QtWidgets.QWidget):
    def __init__(self, manager: Any, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        layout = QtWidgets.QVBoxLayout(self)
        filters = QtWidgets.QHBoxLayout()
        filters.addWidget(QtWidgets.QLabel(text.SEARCH))
        self.search = QtWidgets.QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search, 1)
        filters.addWidget(QtWidgets.QLabel(text.GROUP))
        self.group = QtWidgets.QComboBox()
        self.group.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.group)
        self.favorites = QtWidgets.QCheckBox(text.FAVORITES)
        self.favorites.toggled.connect(self.refresh)
        filters.addWidget(self.favorites)
        filters.addWidget(make_button(text.NEW_QUEUE, self._new))
        layout.addLayout(filters)
        self.table = ReorderTable(["★", "Queue Name", "Group", "Jobs", "HIP File"])
        self.table.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.table.itemDoubleClicked.connect(lambda *_: self._edit())
        layout.addWidget(self.table, 1)
        primary_buttons = [
            make_button(text.ADD_TO_RUN_LIST, self._add_to_run),
            make_button(text.EDIT, self._edit),
            make_button(text.DUPLICATE, self._duplicate),
        ]
        file_buttons = [
            make_button(text.IMPORT_JSON, self._import),
            make_button(text.EXPORT_JSON, self._export),
            make_button(text.DELETE, self._delete),
        ]
        primary_row = compact_button_row(*primary_buttons)
        primary_row.setSpacing(3)
        layout.addLayout(primary_row)
        layout.addLayout(compact_button_row(*file_buttons))
        self._groups: list[str] = []
        self.refresh()

    def refresh(self) -> None:
        queues = manager_collection(self.manager, "queues")
        groups = sorted(
            {str(item_value(queue, "group", "")) for queue in queues if item_value(queue, "group", "")}
        )
        if groups != self._groups:
            current = self.group.currentText()
            self.group.blockSignals(True)
            self.group.clear()
            self.group.addItem(text.ALL_GROUPS)
            self.group.addItems(groups)
            index = self.group.findText(current)
            self.group.setCurrentIndex(max(index, 0))
            self.group.blockSignals(False)
            self._groups = groups
        needle = self.search.text().strip().lower()
        group = self.group.currentText()
        favorites_only = self.favorites.isChecked()
        self.table.setRowCount(0)
        for queue in queues:
            name = str(item_value(queue, "name", "Untitled Queue"))
            queue_group = str(item_value(queue, "group", ""))
            favorite = bool(item_value(queue, "favorite", False))
            haystack = f"{name} {queue_group} {item_value(queue, 'description', '')}".lower()
            if needle and needle not in haystack:
                continue
            if group != text.ALL_GROUPS and queue_group != group:
                continue
            if favorites_only and not favorite:
                continue
            row = self.table.rowCount()
            set_row(
                self.table,
                row,
                [
                    "★" if favorite else "",
                    name,
                    queue_group,
                    len(sequence(item_value(queue, "jobs", []))),
                    item_value(queue, "hip_file", ""),
                ],
                queue,
            )
        self.table.resizeColumnsToContents()

    def _houdini_window(self) -> QtWidgets.QWidget:
        hou_module = value(self.manager, "hou")
        qt_namespace = getattr(hou_module, "qt", None)
        main_window = getattr(qt_namespace, "mainWindow", None)
        try:
            parent = main_window() if callable(main_window) else None
        except Exception:
            parent = None
        if isinstance(parent, QtWidgets.QWidget):
            return parent
        return self.window()

    def _open_editor(
        self,
        queue: Any,
        editor_key: str,
        *,
        existing_queue: bool,
    ) -> QueueEditorDialog:
        registry_key = (id(self.manager), editor_key)
        existing = _OPEN_QUEUE_EDITORS.get(registry_key)
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return existing
            except RuntimeError:
                _OPEN_QUEUE_EDITORS.pop(registry_key, None)

        save_handler = getattr(self.manager, "update_queue", None)
        if not callable(save_handler):
            raise RuntimeError("The Queue Library is not writable.")
        editor = QueueEditorDialog(
            queue,
            self._houdini_window(),
            save_handler=save_handler,
            existing_queue=existing_queue,
        )
        editor.setWindowFlag(QtCore.Qt.WindowType.Window, True)
        _OPEN_QUEUE_EDITORS[registry_key] = editor

        def release(*_args: Any) -> None:
            if _OPEN_QUEUE_EDITORS.get(registry_key) is editor:
                _OPEN_QUEUE_EDITORS.pop(registry_key, None)

        editor.destroyed.connect(release)
        editor.show()
        editor.raise_()
        editor.activateWindow()
        return editor

    def _new_queue(self) -> Any:
        from hcq.models import QueueTemplate

        hip_file = ""
        hou_module = value(self.manager, "hou")
        hip = getattr(hou_module, "hipFile", None)
        try:
            if hip is not None and not hip.isNewFile():
                hip_file = str(hip.path())
        except Exception:
            pass
        return QueueTemplate(hip_file=hip_file)

    def _new(self) -> QueueEditorDialog:
        return self._open_editor(
            self._new_queue(), "new", existing_queue=False
        )

    def _edit(self) -> QueueEditorDialog | None:
        queue = self.table.current_object()
        if queue is None:
            return None
        return self._open_editor(
            queue,
            f"edit:{_identifier(queue)}",
            existing_queue=True,
        )

    def _duplicate(self) -> QueueEditorDialog | None:
        queue = self.table.current_object()
        if queue is None:
            return None
        duplicate = getattr(queue, "duplicate", None)
        if callable(duplicate):
            candidate = duplicate()
        else:
            from hcq.models import QueueTemplate

            candidate = QueueTemplate.from_dict(mapping(queue)).duplicate()
        return self._open_editor(
            candidate,
            f"duplicate:{_identifier(queue)}",
            existing_queue=False,
        )

    def _delete(self) -> None:
        queues = self.table.selected_objects()
        if not queues:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete Queues",
            f"Delete {len(queues)} selected queue(s)?",
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        for queue in queues:
            call(self.manager, "delete_queue", _identifier(queue))
        self.refresh()

    def _add_to_run(self) -> None:
        ids = [_identifier(queue) for queue in self.table.selected_objects()]
        if ids:
            call(self.manager, "add_to_run_list", ids)

    def _import(self) -> None:
        path, _selected = QtWidgets.QFileDialog.getOpenFileName(
            self, text.IMPORT_JSON, "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            _interactive_import_queues(self.manager, path, self)
            self.refresh()
        except Exception as error:
            show_error(self, f"Could not import JSON:\n{error}")

    def _export(self) -> None:
        ids = [_identifier(queue) for queue in self.table.selected_objects()]
        if not ids:
            show_warning(self, text.NO_SELECTION)
            return
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self, text.EXPORT_JSON, "hcq-queues.json", "JSON Files (*.json)"
        )
        if path:
            try:
                call(self.manager, "export_queue_file", path, ids)
            except Exception as error:
                show_error(self, f"Could not export JSON:\n{error}")


class RunTab(QtWidgets.QWidget):
    def __init__(self, manager: Any, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        layout = QtWidgets.QVBoxLayout(self)
        self.table = ReorderTable(["#", "Queue", "Jobs", "CPU", "Status"])
        self.table.orderChanged.connect(self._drag_reorder)
        self.table.itemDoubleClicked.connect(lambda *_: self._edit_overrides())
        layout.addWidget(self.table, 1)
        tools = [
            make_button(text.ADD_QUEUE, self._add_queue),
            make_button(text.IMPORT_JSON, self._import),
            make_button(text.MOVE_UP, lambda: self._move(-1)),
            make_button(text.MOVE_DOWN, lambda: self._move(1)),
            make_button(text.REMOVE, self._remove),
            make_button(text.CLEAR_RUN_LIST, self._clear),
            make_button(text.TEMPORARY_OVERRIDES, self._edit_overrides),
        ]
        layout.addLayout(compact_button_row(*tools))
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        layout.addWidget(self.progress)
        self.current_job = QtWidgets.QLabel("No active job")
        layout.addWidget(self.current_job)
        controls = [
            make_button(text.PREFLIGHT_CHECK, self._preflight),
            make_button(text.EXPORT_RUN_LIST, self._export),
            make_button(text.RUN_QUEUE, self._run, object_name="hcqPrimaryButton"),
            make_button(text.PAUSE_AFTER_CURRENT, self._pause),
            make_button(text.RESUME, self._resume),
            make_button(text.CANCEL_CURRENT, self._cancel),
        ]
        layout.addLayout(compact_button_row(*controls))
        self.refresh()

    def _queues(self) -> list[Any]:
        return manager_collection(self.manager, "run_list")

    def refresh(self) -> None:
        current_obj = self.table.current_object()
        queues = self._queues()
        runner = value(self.manager, "runner")
        state = str(value(runner, "state", "idle"))
        self.table.setRowCount(0)
        for index, queue in enumerate(queues):
            set_row(
                self.table,
                index,
                [
                    index + 1,
                    item_value(queue, "name", "Untitled Queue"),
                    len(sequence(item_value(queue, "jobs", []))),
                    _cpu_label(queue),
                    state.title() if value(runner, "active", False) else text.READY,
                ],
                queue,
            )
            if queue is current_obj:
                self.table.selectRow(index)
        session = value(runner, "session")
        jobs = sequence(value(session, "jobs", []))
        completed = sum(
            str(item_value(job, "state", "")) in {
                "completed",
                "completed_with_warning",
                "failed",
                "cancelled",
                "skipped",
            }
            for job in jobs
        )
        percent = int((completed / len(jobs)) * 100) if jobs else 0
        self.progress.setValue(percent)
        self.progress.setFormat(f"{state.replace('_', ' ').title()} — {completed}/{len(jobs)}")
        current_id = value(session, "current_job_id", "")
        current = next(
            (job for job in jobs if item_value(job, "job_id", "") == current_id),
            None,
        )
        self.current_job.setText(
            f"Current Job: {item_value(current, 'display_name', 'None')}"
        )

    def _add_queue(self) -> None:
        queues = manager_collection(self.manager, "queues")
        if not queues:
            show_warning(self, "The Queue Library is empty.")
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(text.ADD_QUEUE)
        layout = QtWidgets.QVBoxLayout(dialog)
        choices = QtWidgets.QListWidget()
        choices.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        for queue in queues:
            item = QtWidgets.QListWidgetItem(str(item_value(queue, "name", "Untitled Queue")))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, _identifier(queue))
            choices.addItem(item)
        layout.addWidget(choices)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            ids = [
                item.data(QtCore.Qt.ItemDataRole.UserRole)
                for item in choices.selectedItems()
            ]
            call(self.manager, "add_to_run_list", ids)
            self.refresh()

    def _import(self) -> None:
        path, _selected = QtWidgets.QFileDialog.getOpenFileName(
            self, text.IMPORT_JSON, "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            imported = _interactive_import_queues(self.manager, path, self)
            ids = [_identifier(queue) for queue in imported]
            if ids:
                call(self.manager, "add_to_run_list", ids)
            self.refresh()
        except Exception as error:
            show_error(self, f"Could not import JSON:\n{error}")

    def _move(self, delta: int) -> None:
        row = self.table.currentRow()
        if row >= 0:
            call(self.manager, "move_run_queue", row, delta)
            self.refresh()
            self.table.selectRow(max(0, row + delta))

    def _drag_reorder(self, queues: list[Any]) -> None:
        run_list = value(self.manager, "run_list")
        target = value(run_list, "queues")
        if isinstance(target, list):
            target[:] = queues
            call(self.manager, "notify_changed", "run_list")
        self.refresh()

    def _remove(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            call(self.manager, "remove_run_queue", row)
        self.refresh()

    def _edit_overrides(self) -> QueueEditorDialog | None:
        row = self.table.currentRow()
        queues = self._queues()
        if not (0 <= row < len(queues)):
            show_warning(self, text.NO_SELECTION)
            return None
        source = queues[row]
        source_id = _identifier(source) or str(id(source))
        registry_key = (
            id(self.manager),
            f"override:{source_id}:{id(source)}",
        )
        existing = _OPEN_QUEUE_EDITORS.get(registry_key)
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return existing
            except RuntimeError:
                _OPEN_QUEUE_EDITORS.pop(registry_key, None)

        manager = self.manager

        def save_override(candidate: Any) -> None:
            run_list = value(manager, "run_list")
            target = value(run_list, "queues")
            if not isinstance(target, list):
                raise RuntimeError("The Run List is not writable.")
            index = next(
                (
                    position
                    for position, queue in enumerate(target)
                    if queue is source
                ),
                -1,
            )
            if index < 0:
                raise RuntimeError("The queue is no longer in the Run List.")
            target[index] = candidate
            call(manager, "notify_changed", "run_list")

        hou_module = value(self.manager, "hou")
        qt_namespace = getattr(hou_module, "qt", None)
        main_window = getattr(qt_namespace, "mainWindow", None)
        try:
            parent = main_window() if callable(main_window) else None
        except Exception:
            parent = None
        if not isinstance(parent, QtWidgets.QWidget):
            parent = self.window()
        editor = QueueEditorDialog(
            source,
            parent,
            save_handler=save_override,
            existing_queue=False,
        )
        editor.setWindowTitle(text.TEMPORARY_OVERRIDES)
        editor.setWindowFlag(QtCore.Qt.WindowType.Window, True)
        _OPEN_QUEUE_EDITORS[registry_key] = editor

        def release(*_args: Any) -> None:
            if _OPEN_QUEUE_EDITORS.get(registry_key) is editor:
                _OPEN_QUEUE_EDITORS.pop(registry_key, None)

        editor.destroyed.connect(release)
        editor.show()
        editor.raise_()
        editor.activateWindow()
        return editor

    def _clear(self) -> None:
        for row in range(len(self._queues()) - 1, -1, -1):
            call(self.manager, "remove_run_queue", row)
        self.refresh()

    def _preflight(self) -> bool:
        issues = call(self.manager, "preflight_run", default=[])
        settings = value(self.manager, "settings", {}) or {}
        dialog = PreflightDialog(
            issues,
            self,
            str(item_value(settings, "existing_output_behavior", "ask_each")),
        )
        return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted

    def _export(self) -> None:
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self, text.EXPORT_RUN_LIST, "hcq-run-list.json", "JSON Files (*.json)"
        )
        if not path:
            return
        result = call(
            self.manager,
            ("export_run_list_file", "export_run_list"),
            path,
        )
        if result is None:
            storage = value(self.manager, "storage")
            call(storage, ("save_run_list", "export_run_list"), value(self.manager, "run_list"), path)

    def _run(self) -> None:
        queues = self._queues()
        jobs = sum(len(sequence(item_value(queue, "jobs", []))) for queue in queues)
        if not queues or not jobs:
            show_warning(self, "The run list contains no enabled jobs.")
            return
        issues = call(self.manager, "preflight_run", default=[])
        settings = value(self.manager, "settings", {}) or {}
        preflight = PreflightDialog(
            issues,
            self,
            str(item_value(settings, "existing_output_behavior", "ask_each")),
        )
        if preflight.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        confirmation = RunConfirmDialog(
            len(queues), jobs, value(self.manager, "settings"), self
        )
        if confirmation.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        settings = value(self.manager, "settings")
        if isinstance(settings, dict):
            settings["save_before_running"] = confirmation.save_mode.currentData()
            settings["create_backup_before_saving"] = confirmation.backup.isChecked()
            settings["existing_output_behavior"] = preflight.output_policy
        call(self.manager, "start_run")

    def _pause(self) -> None:
        call(value(self.manager, "runner"), "request_pause")

    def _resume(self) -> None:
        call(value(self.manager, "runner"), "resume")

    def _cancel(self) -> None:
        call(value(self.manager, "runner"), "request_cancel")


class HistoryTab(QtWidgets.QWidget):
    def __init__(self, manager: Any, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        layout = QtWidgets.QVBoxLayout(self)
        self.table = ReorderTable(
            ["Date", "Session", "Result", "Duration", "HIP File"]
        )
        self.table.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.NoDragDrop
        )
        self.table.itemDoubleClicked.connect(lambda *_: self._show_details())
        layout.addWidget(self.table, 1)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(170)
        self.table.itemSelectionChanged.connect(self._show_details)
        layout.addWidget(self.details)
        primary_buttons = [
            make_button(text.RUN_AGAIN, lambda: self._action("run_history")),
            make_button(text.RUN_FAILED, lambda: self._action("run_failed_jobs")),
            make_button(text.RUN_FROM_FAILED, lambda: self._action("run_from_failed_job")),
            make_button(text.RESTORE_RUN_LIST, lambda: self._action("restore_history")),
        ]
        navigation_buttons = [
            make_button(text.EXPORT_RESULT, self._export),
            make_button(text.GO_TO_NODE, self._go_to_node),
        ]
        for button in navigation_buttons:
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Maximum,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )
        primary_row = compact_button_row(*primary_buttons)
        primary_row.setSpacing(3)
        layout.addLayout(primary_row)
        layout.addLayout(compact_button_row(*navigation_buttons))
        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for row, session in enumerate(_history_items(self.manager)):
            start = item_value(session, "started_at", "")
            session_id = item_value(
                session, "session_id", item_value(session, "id", "")
            )
            duration = item_value(session, "duration_seconds", None)
            if duration is None:
                duration_label = "--"
            else:
                seconds = int(float(duration))
                duration_label = f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
            set_row(
                self.table,
                row,
                [
                    start,
                    session_id,
                    str(item_value(session, "state", text.UNKNOWN)).title(),
                    duration_label,
                    item_value(session, "hip_file", ""),
                ],
                session,
            )
        self.table.resizeColumnsToContents()

    def _show_details(self) -> None:
        session = self.table.current_object()
        if session is None:
            self.details.clear()
            return
        if hasattr(session, "to_document"):
            try:
                session = session.to_document(completed=True)
            except Exception:
                pass
        try:
            if not isinstance(session, dict):
                session = vars(session)
            self.details.setPlainText(
                json.dumps(session, ensure_ascii=False, indent=2, default=str)
            )
        except Exception:
            self.details.setPlainText(str(session))

    def _action(self, name: str) -> None:
        session = self.table.current_object()
        if session is None:
            return
        session_id = item_value(session, "session_id", item_value(session, "id", ""))
        result = call(self.manager, name, session_id)
        if result is None:
            show_warning(self, "This history action is not available.")

    def _go_to_node(self) -> None:
        session = self.table.current_object()
        if session is None:
            return
        session_id = item_value(
            session, "session_id", item_value(session, "id", "")
        )
        result = call(self.manager, "go_to_history_node", session_id)
        _show_navigation_result(
            self,
            result,
            "Could not navigate to a node from this history session.",
        )

    def _export(self) -> None:
        session = self.table.current_object()
        if session is None:
            return
        session_id = item_value(session, "session_id", item_value(session, "id", ""))
        path, _selected = QtWidgets.QFileDialog.getSaveFileName(
            self, text.EXPORT_RESULT, f"{session_id}.json", "JSON Files (*.json)"
        )
        if path:
            result = call(
                self.manager, ("export_history_result", "export_result"), session_id, path
            )
            if result is None:
                storage = value(self.manager, "storage")
                call(storage, ("export_history", "export_result"), session_id, path)


class SettingsTab(QtWidgets.QWidget):
    def __init__(self, manager: Any, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        outer = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(content)
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self.monitor_enabled = QtWidgets.QCheckBox("Enable Cook Monitor")
        self.poll_interval = QtWidgets.QSpinBox()
        self.poll_interval.setRange(250, 10_000)
        self.poll_interval.setSuffix(" ms")
        self.minimum_duration = QtWidgets.QDoubleSpinBox()
        self.minimum_duration.setRange(0.0, 86_400.0)
        self.minimum_duration.setSuffix(" s")
        self.suppress_playback = QtWidgets.QCheckBox("Suppress During Playback")
        self.merge_notifications = QtWidgets.QCheckBox("Merge Rapid Notifications")
        self.windows_notifications = QtWidgets.QCheckBox(
            "Enable Windows Notifications"
        )
        self.windows_notification_status = QtWidgets.QLabel()
        windows_notification_row = QtWidgets.QHBoxLayout()
        windows_notification_row.addWidget(self.windows_notifications)
        windows_notification_row.addWidget(self.windows_notification_status)
        windows_notification_row.addStretch(1)
        self.save_behavior = QtWidgets.QComboBox()
        for label, data in (
            ("Always Save", "always"),
            ("Ask", "ask"),
            ("Do Not Save", "never"),
        ):
            self.save_behavior.addItem(label, data)
        self.backup = QtWidgets.QCheckBox("Create Backup Before Saving")
        self.default_cpu = QtWidgets.QComboBox()
        for label, data in (
            ("Use Current Houdini Setting", "current"),
            ("All Threads", "all"),
            ("Fixed Thread Count", "threads"),
            ("Reserve Threads", "reserve"),
            ("Single Thread", "single"),
        ):
            self.default_cpu.addItem(label, data)
        self.default_cpu_value = QtWidgets.QSpinBox()
        self.default_cpu_value.setRange(1, 1024)
        self.default_cpu_value.setValue(1)
        default_cpu_row = QtWidgets.QHBoxLayout()
        default_cpu_row.addWidget(self.default_cpu, 1)
        default_cpu_row.addWidget(self.default_cpu_value)
        self.default_cpu.currentIndexChanged.connect(self._sync_cpu_value)
        self.default_error = QtWidgets.QComboBox()
        for label, data in (
            ("Stop Queue", "stop_queue"),
            ("Skip Job and Continue", "skip_continue"),
            ("Wait for User Decision", "wait_for_user"),
        ):
            self.default_error.addItem(label, data)
        self.default_retry = QtWidgets.QSpinBox()
        self.default_retry.setRange(0, 100)
        self.default_verification = QtWidgets.QComboBox()
        self.default_verification.addItem("Basic", "basic")
        self.default_verification.addItem("None", "none")
        self.existing_outputs = QtWidgets.QComboBox()
        for label, data in (
            ("Ask for Each Job", "ask_each"),
            ("Overwrite", "overwrite"),
            ("Stop", "stop"),
            ("Skip", "skip"),
        ):
            self.existing_outputs.addItem(label, data)
        self.retention = QtWidgets.QSpinBox()
        self.retention.setRange(1, 3650)
        self.retention.setSuffix(" days")
        self.notify_job = QtWidgets.QCheckBox("Notify After Each Job")
        self.notify_queue = QtWidgets.QCheckBox("Notify When Queue Completes")

        for label, widget in (
            ("Cook Monitor", self.monitor_enabled),
            ("Polling Interval", self.poll_interval),
            ("Minimum Cook Duration", self.minimum_duration),
            ("Playback", self.suppress_playback),
            ("Notifications", self.merge_notifications),
            ("Windows Notifications", windows_notification_row),
            ("Save Before Running", self.save_behavior),
            ("HIP Backup", self.backup),
            ("Default CPU", default_cpu_row),
            ("Default Error Behavior", self.default_error),
            ("Default Retry Count", self.default_retry),
            ("Default Verification", self.default_verification),
            ("Existing Outputs", self.existing_outputs),
            ("History Retention", self.retention),
            ("Job Notifications", self.notify_job),
            ("Queue Notifications", self.notify_queue),
        ):
            form.addRow(label, widget)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        outer.addLayout(
            compact_button_row(
                make_button(text.SAVE, self._save, object_name="hcqPrimaryButton"),
                make_button("Test Notification", self._test_notification),
                make_button("Restore Defaults", self._restore_defaults),
            )
        )
        self.refresh()

    @staticmethod
    def _set_combo(combo: QtWidgets.QComboBox, value: Any) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def refresh(self) -> None:
        settings = value(self.manager, "settings", {}) or {}
        get = settings.get if isinstance(settings, dict) else lambda key, default=None: item_value(settings, key, default)
        self.monitor_enabled.setChecked(bool(get("monitor_enabled", True)))
        self.poll_interval.setValue(int(get("monitor_poll_interval_ms", 750)))
        self.minimum_duration.setValue(
            float(get("minimum_cook_duration_seconds", 5.0))
        )
        self.suppress_playback.setChecked(
            bool(get("suppress_monitor_during_playback", True))
        )
        self.merge_notifications.setChecked(
            bool(get("merge_rapid_notifications", True))
        )
        self.windows_notifications.setChecked(
            bool(get("windows_notifications_enabled", False))
        )
        notifications = value(self.manager, "notifications")
        available = call(notifications, "windows_available", default=False)
        self.windows_notification_status.setText(
            "Available" if available else "Unavailable"
        )
        self._set_combo(self.save_behavior, get("save_before_running", "always"))
        self.backup.setChecked(
            bool(get("create_backup_before_saving", False))
        )
        cpu = get("default_cpu", {"mode": "current"})
        self._set_combo(self.default_cpu, item_value(cpu, "mode", "current"))
        self.default_cpu_value.setValue(int(item_value(cpu, "value", 1) or 1))
        self._sync_cpu_value()
        self._set_combo(
            self.default_error, get("default_on_error", "stop_queue")
        )
        self.default_retry.setValue(int(get("default_retry_count", 0)))
        self._set_combo(
            self.default_verification, get("default_verification", "basic")
        )
        self._set_combo(
            self.existing_outputs, get("existing_output_behavior", "ask_each")
        )
        self.retention.setValue(int(get("history_retention_days", 90)))
        self.notify_job.setChecked(bool(get("notify_each_job", True)))
        self.notify_queue.setChecked(bool(get("notify_queue_complete", True)))

    def _save(self) -> None:
        settings = value(self.manager, "settings")
        if not isinstance(settings, dict):
            show_error(self, "Settings are not writable.")
            return
        cpu = {"mode": self.default_cpu.currentData()}
        if self.default_cpu.currentData() in {"threads", "reserve"}:
            cpu["value"] = self.default_cpu_value.value()
        settings.update(
            {
                "monitor_enabled": self.monitor_enabled.isChecked(),
                "monitor_poll_interval_ms": self.poll_interval.value(),
                "minimum_cook_duration_seconds": self.minimum_duration.value(),
                "suppress_monitor_during_playback": self.suppress_playback.isChecked(),
                "merge_rapid_notifications": self.merge_notifications.isChecked(),
                "windows_notifications_enabled": (
                    self.windows_notifications.isChecked()
                ),
                "save_before_running": self.save_behavior.currentData(),
                "create_backup_before_saving": self.backup.isChecked(),
                "default_cpu": cpu,
                "default_on_error": self.default_error.currentData(),
                "default_retry_count": self.default_retry.value(),
                "default_verification": self.default_verification.currentData(),
                "existing_output_behavior": self.existing_outputs.currentData(),
                "history_retention_days": self.retention.value(),
                "notify_each_job": self.notify_job.isChecked(),
                "notify_queue_complete": self.notify_queue.isChecked(),
            }
        )
        call(self.manager, "save_settings")
        call(self.manager, "notify_changed", "settings")

    def _test_notification(self) -> None:
        self._save()
        notifications = value(self.manager, "notifications")
        result = call(
            notifications,
            ("test_notification", "send_test_notification"),
        )
        if result is None:
            show_warning(self, "The notification service is not available.")
            return
        wants_windows = self.windows_notifications.isChecked()
        QtCore.QTimer.singleShot(
            250,
            lambda current=result, requested=wants_windows: (
                self._finish_notification_test(current, requested)
            ),
        )

    def _finish_notification_test(
        self,
        notification: Any,
        wants_windows: bool,
    ) -> None:
        if not wants_windows:
            self.windows_notification_status.setText("In-app test sent")
            return
        delivery = mapping(item_value(notification, "delivery", {}))
        if bool(delivery.get("windows", False)):
            self.windows_notification_status.setText(
                "Test sent (Windows may suppress display)"
            )
        else:
            self.windows_notification_status.setText(
                "Windows test failed; in-app fallback used"
            )

    def _sync_cpu_value(self) -> None:
        self.default_cpu_value.setEnabled(
            self.default_cpu.currentData() in {"threads", "reserve"}
        )

    def _restore_defaults(self) -> None:
        try:
            from hcq.constants import DEFAULT_SETTINGS

            settings = value(self.manager, "settings")
            if isinstance(settings, dict):
                settings.clear()
                settings.update(DEFAULT_SETTINGS)
                call(self.manager, "save_settings")
                call(self.manager, "notify_changed", "settings")
                self.refresh()
        except Exception as error:
            show_error(self, f"Could not restore defaults:\n{error}")
