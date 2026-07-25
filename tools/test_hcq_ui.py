"""Offscreen PySide6 smoke tests for the HCQ Houdini Python Panel."""

from __future__ import annotations

import copy
from types import SimpleNamespace

from PySide6 import QtGui, QtWidgets

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


class FakeMonitor:
    registrations = ()

    def update_settings(self, _settings):
        return None


class FakeStorage:
    def history_documents(self):
        return []


class FakeManager:
    def __init__(self):
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.monitor = FakeMonitor()
        self.runner = SimpleNamespace(state="idle", active=False, session=None)
        self.recovery = SimpleNamespace(pending=None)
        self.storage = FakeStorage()
        self.run_list = RunList()
        self.queues = []
        self.listeners = []

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
    settings.default_cpu.setCurrentIndex(
        settings.default_cpu.findData("reserve")
    )
    settings.default_cpu_value.setValue(2)
    settings._save()
    assert manager.settings["default_cpu"] == {"mode": "reserve", "value": 2}

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
        "preflight error gate, listener cleanup"
    )


if __name__ == "__main__":
    main()
