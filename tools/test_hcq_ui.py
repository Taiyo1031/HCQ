"""Offscreen PySide6 smoke tests for the HCQ Houdini Python Panel."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from PySide6 import QtCore, QtGui, QtWidgets

from hcq.constants import DEFAULT_SETTINGS
from hcq.models import Job, QueueTemplate, RunList
from hcq.preflight import PreflightIssue
from hcq.ui.dialogs import (
    ImportPreviewDialog,
    MissingNodesDialog,
    OutputInspectionDialog,
    PreflightDialog,
)
from hcq.ui.editors import QueueEditorDialog
from hcq.ui.main_panel import HCQPanel
from hcq.ui import tabs as ui_tabs
from hcq.navigation import NavigationResult


class FakeMonitor:
    def __init__(self):
        self.registrations = [
            SimpleNamespace(
                id="monitor-1",
                display_name="Fast Cook",
                node_path="/obj/fast",
                node_type="geo",
                method="Polling",
                status="Watching",
                enabled=True,
                last_duration_seconds=0.0004,
                last_completed_at="2026-07-26T00:00:00+00:00",
                last_result="completed",
                notification_state="suppressed",
                suppression_reason="below_minimum_duration",
            )
        ]

    def update_settings(self, _settings):
        return None


class FakeNotifications:
    def __init__(self):
        self.test_count = 0

    def windows_available(self):
        return True

    def test_notification(self):
        self.test_count += 1
        return SimpleNamespace(title="HCQ Notification Test")


class FakeStorage:
    def history_documents(self):
        return []


class FakeUpdater:
    def __init__(self):
        self.calls = 0

    def check_and_stage(self):
        self.calls += 1
        return SimpleNamespace(
            status="up_to_date",
            message="HCQ 1.1.0 is up to date.",
            release_url="https://github.com/Taiyo1031/HCQ/releases/latest",
        )


class FakeManager:
    def __init__(self):
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.monitor = FakeMonitor()
        self.notifications = FakeNotifications()
        self.runner = SimpleNamespace(state="idle", active=False, session=None)
        self.recovery = SimpleNamespace(pending=None)
        self.storage = FakeStorage()
        self.updater = FakeUpdater()
        self.run_list = RunList()
        self.queues = []
        self.listeners = []
        self.queue_updates = []
        self.duplicate_calls = 0

    def add_listener(self, callback):
        self.listeners.append(callback)

        def remove():
            if callback in self.listeners:
                self.listeners.remove(callback)

        return remove

    def refresh_all(self):
        return None

    def save_settings(self):
        return None

    def notify_changed(self, _scope="all"):
        return None

    def update_queue(self, queue):
        saved = copy.deepcopy(queue)
        self.queue_updates.append(saved)
        for index, existing in enumerate(self.queues):
            if existing.id == saved.id:
                self.queues[index] = saved
                return saved
        self.queues.append(saved)
        return saved

    def duplicate_queue(self, _queue_id):
        self.duplicate_calls += 1
        raise AssertionError("Modeless duplicate must save through update_queue.")


def main() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    manager = FakeManager()
    panel = HCQPanel(manager)
    panel.show()
    app.processEvents()
    assert len(manager.listeners) == 1

    assert panel.tabs.count() == 5
    assert [
        panel.tabs.tabText(index) for index in range(panel.tabs.count())
    ] == ["Monitor", "Queues", "Run", "History", "Settings"]
    assert panel.usage_button.text() == "Usage"
    assert panel.update_button.text() == "Update"
    panel._check_for_updates()
    assert QtCore.QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    assert manager.updater.calls == 1
    assert panel.update_button.isEnabled()
    assert panel.update_button.text() == "Update"
    assert (
        panel.environment_status.width()
        >= panel.environment_status.sizeHint().width()
    )
    assert panel.monitor_tab.table.item(0, 9).text() == (
        "Suppressed: 0.4 ms < 5 s"
    )
    panel.tabs.setCurrentWidget(panel.queues_tab)
    app.processEvents()
    queue_buttons = {
        button.text(): button
        for button in panel.queues_tab.findChildren(QtWidgets.QPushButton)
    }
    assert queue_buttons["Import JSON"].y() > queue_buttons["Add to Run List"].y()
    assert (
        queue_buttons["Add to Run List"].width()
        <= queue_buttons["Add to Run List"].sizeHint().width()
    )
    panel.tabs.setCurrentWidget(panel.history_tab)
    panel.resize(520, 520)
    app.processEvents()
    history_buttons = {
        button.text(): button
        for button in panel.history_tab.findChildren(QtWidgets.QPushButton)
    }
    export_button = history_buttons["Export Result JSON"]
    go_to_button = history_buttons["Go to Node"]
    run_again_button = history_buttons["Run Again"]
    assert export_button.y() == go_to_button.y()
    assert go_to_button.y() > run_again_button.y()
    assert export_button.width() <= export_button.sizeHint().width()
    assert go_to_button.width() <= go_to_button.sizeHint().width()
    warnings = []
    original_warning = ui_tabs.show_warning
    ui_tabs.show_warning = lambda _parent, message: warnings.append(message)
    try:
        assert not ui_tabs._show_navigation_result(
            panel.history_tab,
            NavigationResult(False, "Node navigation failed.", "/obj/missing"),
            "Fallback navigation error.",
        )
    finally:
        ui_tabs.show_warning = original_warning
    assert warnings == ["Node navigation failed."]

    library_queue = QueueTemplate(name="Modeless Source")
    manager.queues = [library_queue]
    panel.queues_tab.refresh()
    panel.queues_tab.table.selectRow(0)
    modeless = panel.queues_tab._edit()
    assert modeless is not None
    assert not modeless.isModal()
    assert modeless.testAttribute(
        QtCore.Qt.WidgetAttribute.WA_DeleteOnClose
    )
    assert panel.queues_tab._edit() is modeless
    assert len(manager.queue_updates) == 0

    import hou

    graph_node = hou.node("/obj").createNode("geo", "hcq_modeless_selection")
    graph_node.setSelected(True, clear_all_selected=True)
    modeless._add_selected()
    assert any(job.node_path == graph_node.path() for job in modeless.queue.jobs)
    graph_node.destroy()
    modeless.name.setText("Modeless Saved")
    assert modeless._dirty
    modeless._save_and_close(False)
    app.processEvents()
    assert len(manager.queue_updates) == 1

    panel.queues_tab.refresh()
    panel.queues_tab.table.selectRow(0)
    duplicate_editor = panel.queues_tab._duplicate()
    assert duplicate_editor is not None
    assert len(manager.queue_updates) == 1
    duplicate_editor._save_and_close(False)
    app.processEvents()
    assert len(manager.queue_updates) == 2
    assert manager.duplicate_calls == 0
    assert manager.queue_updates[0].id != manager.queue_updates[1].id

    new_editor = panel.queues_tab._new()
    assert panel.queues_tab._new() is new_editor
    new_editor.name.setText("Modeless New")
    new_editor._save_and_close(False)
    app.processEvents()
    assert len(manager.queue_updates) == 3

    panel.queues_tab.refresh()
    panel.queues_tab.table.selectRow(0)
    save_as_editor = panel.queues_tab._edit()
    source_id = save_as_editor.queue.id
    save_as_editor._save_and_close(True)
    app.processEvents()
    assert len(manager.queue_updates) == 4
    assert manager.queue_updates[-1].id != source_id

    manager.run_list.queues = [copy.deepcopy(manager.queues[0])]
    panel.run_tab.refresh()
    panel.run_tab.table.selectRow(0)
    override_editor = panel.run_tab._edit_overrides()
    assert override_editor is not None
    assert panel.run_tab._edit_overrides() is override_editor
    override_editor.name.setText("Temporary Modeless Override")
    override_editor._save_and_close(False)
    app.processEvents()
    assert manager.run_list.queues[0].name == "Temporary Modeless Override"
    assert len(manager.queue_updates) == 4

    duplicate_run_queue = copy.deepcopy(manager.queues[0])
    manager.run_list.queues = [
        copy.deepcopy(duplicate_run_queue),
        copy.deepcopy(duplicate_run_queue),
    ]
    panel.run_tab.refresh()
    panel.run_tab.table.selectRow(1)
    second_override = panel.run_tab._edit_overrides()
    second_override.name.setText("Second Duplicate Only")
    second_override._save_and_close(False)
    app.processEvents()
    assert manager.run_list.queues[0].name != "Second Duplicate Only"
    assert manager.run_list.queues[1].name == "Second Duplicate Only"

    discarded = []
    discard_editor = QueueEditorDialog(
        QueueTemplate(name="Discard Source"),
        save_handler=lambda queue: discarded.append(queue),
    )
    discard_editor.name.setText("Unsaved")
    original_question = QtWidgets.QMessageBox.warning
    QtWidgets.QMessageBox.warning = lambda *_args, **_kwargs: (
        QtWidgets.QMessageBox.StandardButton.Discard
    )
    try:
        discard_editor.close()
        app.processEvents()
    finally:
        QtWidgets.QMessageBox.warning = original_question
    assert discarded == []

    close_saved = []
    close_save_editor = QueueEditorDialog(
        QueueTemplate(name="Close Save Source"),
        save_handler=lambda queue: close_saved.append(queue),
    )
    close_save_editor.name.setText("Saved on Close")
    QtWidgets.QMessageBox.warning = lambda *_args, **_kwargs: (
        QtWidgets.QMessageBox.StandardButton.Save
    )
    try:
        close_save_editor.close()
        app.processEvents()
    finally:
        QtWidgets.QMessageBox.warning = original_question
    assert len(close_saved) == 1

    close_cancelled = []
    close_cancel_editor = QueueEditorDialog(
        QueueTemplate(name="Close Cancel Source"),
        save_handler=lambda queue: close_cancelled.append(queue),
    )
    close_cancel_editor.name.setText("Keep Open")
    QtWidgets.QMessageBox.warning = lambda *_args, **_kwargs: (
        QtWidgets.QMessageBox.StandardButton.Cancel
    )
    try:
        close_cancel_editor.show()
        close_cancel_editor.close()
        app.processEvents()
    finally:
        QtWidgets.QMessageBox.warning = original_question
    assert close_cancel_editor.isVisible()
    assert close_cancelled == []
    close_cancel_editor._dirty = False
    close_cancel_editor.close()

    queue = QueueTemplate(
        name="UI Smoke Queue",
        jobs=[Job(display_name="Missing", node_path="/obj/missing")],
    )
    editor = QueueEditorDialog(queue)
    editor.cpu_mode.setCurrentIndex(editor.cpu_mode.findData("threads"))
    editor.cpu_value.setValue(6)
    editor._accept()
    assert editor.queue.cpu.mode == "threads"
    assert editor.queue.cpu.value == 6

    settings = panel.settings_tab
    settings.poll_interval.setValue(1234)
    panel.refresh("monitor")
    assert settings.poll_interval.value() == 1234
    settings.default_cpu.setCurrentIndex(
        settings.default_cpu.findData("reserve")
    )
    settings.default_cpu_value.setValue(2)
    settings._save()
    assert manager.settings["default_cpu"] == {"mode": "reserve", "value": 2}
    settings.windows_notifications.setChecked(True)
    settings._test_notification()
    assert manager.settings["windows_notifications_enabled"]
    assert manager.notifications.test_count == 1

    document = {
        "schema": "hcq.queue-template",
        "schema_version": 1,
        "hcq_version": "1.0.0",
        "houdini_version": "21.0",
        "queues": [queue.to_dict()],
    }
    preview = ImportPreviewDialog(document)
    assert len(preview.selected_queues()) == 1
    preflight = PreflightDialog(
        [PreflightIssue("error", "missing_node", "Node is missing.")],
        output_policy="skip",
    )
    assert preflight.output_policy == "skip"
    assert not preflight.findChild(QtWidgets.QDialogButtonBox).button(
        QtWidgets.QDialogButtonBox.StandardButton.Ok
    ).isEnabled()

    missing = MissingNodesDialog(
        [queue], [(queue.id, queue.jobs[0].id, queue.jobs[0].node_path)]
    )
    assert missing.table.rowCount() == 1
    inspection = OutputInspectionDialog([])
    assert inspection.table.rowCount() == 0
    inspection.close()
    missing.close()
    preflight.close()

    preview.close()
    editor.close()
    panel.closeEvent(QtGui.QCloseEvent())
    app.processEvents()
    assert len(manager.listeners) == 0
    print(
        "HCQ UI checks: 5 tabs, CPU settings, import/recovery dialogs, "
        "preflight gate, modeless queue editing, graph selection, notifications, "
        "header links, listener cleanup"
    )


if __name__ == "__main__":
    main()
