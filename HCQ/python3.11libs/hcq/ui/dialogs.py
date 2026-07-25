"""HCQ decision, preview, and recovery dialogs."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from . import text
from .bridge import item_value, mapping, sequence
from .common import make_button


def _severity_text(issue: Any) -> str:
    return str(
        item_value(issue, "severity", item_value(issue, "level", "info"))
    ).lower()


class PreflightDialog(QtWidgets.QDialog):
    """Display preflight results and collect existing-output policy."""

    def __init__(
        self,
        issues: Any,
        parent: QtWidgets.QWidget | None = None,
        output_policy: str = "ask_each",
    ):
        super().__init__(parent)
        self.setWindowTitle(text.PREFLIGHT_TITLE)
        self.resize(720, 470)
        layout = QtWidgets.QVBoxLayout(self)
        summary = QtWidgets.QLabel(
            "Review all checks before starting the queue."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        self.table = QtWidgets.QTreeWidget()
        self.table.setHeaderLabels(["Result", "Check", "Details"])
        self.table.setRootIsDecorated(False)
        issue_list = sequence(issues)
        for issue in issue_list:
            severity = _severity_text(issue)
            symbol = {"error": "×", "warning": "!", "info": "✓", "ok": "✓"}.get(
                severity, "•"
            )
            name = item_value(issue, "check", item_value(issue, "title", "Check"))
            details = item_value(
                issue, "message", item_value(issue, "details", "")
            )
            row = QtWidgets.QTreeWidgetItem([symbol, str(name), str(details)])
            if severity == "error":
                row.setIcon(0, self.style().standardIcon(
                    QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical
                ))
            elif severity == "warning":
                row.setIcon(0, self.style().standardIcon(
                    QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning
                ))
            else:
                row.setIcon(0, self.style().standardIcon(
                    QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton
                ))
            self.table.addTopLevelItem(row)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        layout.addWidget(self.table, 1)

        policy_row = QtWidgets.QFormLayout()
        self.existing_outputs = QtWidgets.QComboBox()
        for label, data in (
            ("Ask for Each Job", "ask_each"),
            ("Overwrite", "overwrite"),
            ("Stop Before This Job", "stop"),
            ("Skip This Job", "skip"),
        ):
            self.existing_outputs.addItem(label, data)
        policy_index = self.existing_outputs.findData(output_policy)
        self.existing_outputs.setCurrentIndex(max(policy_index, 0))
        policy_row.addRow("Existing Outputs", self.existing_outputs)
        layout.addLayout(policy_row)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        continue_button = buttons.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        )
        continue_button.setText("Continue")
        continue_button.setEnabled(
            not any(_severity_text(issue) == "error" for issue in issue_list)
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def output_policy(self) -> str:
        return str(self.existing_outputs.currentData())


class ImportPreviewDialog(QtWidgets.QDialog):
    """Preview imported queue documents without executing them."""

    def __init__(
        self,
        document: Any,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(text.IMPORT_PREVIEW_TITLE)
        self.resize(760, 500)
        layout = QtWidgets.QVBoxLayout(self)
        data = mapping(document)
        schema = data.get("schema", "Unknown")
        version = data.get("schema_version", "Unknown")
        layout.addWidget(
            QtWidgets.QLabel(f"Schema: {schema}    Version: {version}")
        )
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Import", "Name", "Type", "Path / Details"])
        queues = data.get("queues")
        if queues is None and data.get("jobs") is not None:
            queues = [data]
        for queue in sequence(queues):
            queue_item = QtWidgets.QTreeWidgetItem(
                [
                    "",
                    str(item_value(queue, "name", "Untitled Queue")),
                    "Queue",
                    str(item_value(queue, "hip_file", "")),
                ]
            )
            queue_item.setFlags(
                queue_item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            )
            queue_item.setCheckState(0, QtCore.Qt.CheckState.Checked)
            queue_item.setData(0, QtCore.Qt.ItemDataRole.UserRole, queue)
            self.tree.addTopLevelItem(queue_item)
            for job in sequence(item_value(queue, "jobs", [])):
                job_item = QtWidgets.QTreeWidgetItem(
                    [
                        "",
                        str(item_value(job, "display_name", "Untitled Job")),
                        str(item_value(job, "action", "auto_detect")),
                        str(item_value(job, "node_path", "")),
                    ]
                )
                queue_item.addChild(job_item)
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        layout.addWidget(self.tree, 1)
        note = QtWidgets.QLabel(
            "Imported data is added to the library only. It will never run automatically."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.path_mappings: list[tuple[str, str]] = []
        remap = make_button("Path Remap...", self._configure_path_remap)
        layout.addWidget(remap, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Open
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Open).setText(
            "Import Selected"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _configure_path_remap(self) -> None:
        dialog = PathRemapDialog(self.path_mappings, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.path_mappings = dialog.mappings()

    def selected_queues(self) -> list[Any]:
        result = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.checkState(0) == QtCore.Qt.CheckState.Checked:
                result.append(item.data(0, QtCore.Qt.ItemDataRole.UserRole))
        return result


class PathRemapDialog(QtWidgets.QDialog):
    """Collect portable HIP/node/output prefix remaps."""

    def __init__(
        self,
        mappings: list[tuple[str, str]] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(text.PATH_REMAP_TITLE)
        self.resize(680, 360)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                "Replace path prefixes while importing. Original JSON remains unchanged."
            )
        )
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Original Prefix", "Replacement Prefix"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        for source, target in mappings or []:
            self._append(source, target)
        add = make_button("Add Mapping", lambda: self._append("", ""))
        remove = make_button(text.REMOVE, self._remove)
        tools = QtWidgets.QHBoxLayout()
        tools.addWidget(add)
        tools.addWidget(remove)
        tools.addStretch(1)
        layout.addLayout(tools)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _append(self, source: str, target: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(source))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(target))

    def _remove(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()}, reverse=True
        )
        for row in rows:
            self.table.removeRow(row)

    def mappings(self) -> list[tuple[str, str]]:
        result = []
        for row in range(self.table.rowCount()):
            source_item = self.table.item(row, 0)
            target_item = self.table.item(row, 1)
            source = source_item.text().strip() if source_item else ""
            target = target_item.text().strip() if target_item else ""
            if source:
                result.append((source, target))
        return result


class MissingNodesDialog(QtWidgets.QDialog):
    """Resolve imported jobs whose node paths are absent in the current HIP."""

    def __init__(
        self,
        queues: list[Any],
        missing: list[tuple[str, str, str]],
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.queues = queues
        self.missing = missing
        self.setWindowTitle("Resolve Missing Nodes")
        self.resize(900, 440)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(
            "Every enabled job must reference an existing node. Replace, disable, "
            "or remove each missing job before importing."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = QtWidgets.QTableWidget(len(missing), 5)
        self.table.setHorizontalHeaderLabels(
            ["Queue", "Job", "Missing Path", "Resolution", "Replacement Path"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, (queue_id, job_id, node_path) in enumerate(missing):
            queue = next(
                (item for item in queues if item_value(item, "id", "") == queue_id),
                None,
            )
            job = next(
                (
                    item
                    for item in sequence(item_value(queue, "jobs", []))
                    if item_value(item, "id", "") == job_id
                ),
                None,
            )
            self.table.setItem(
                row,
                0,
                QtWidgets.QTableWidgetItem(
                    str(item_value(queue, "name", queue_id))
                ),
            )
            self.table.setItem(
                row,
                1,
                QtWidgets.QTableWidgetItem(
                    str(item_value(job, "display_name", job_id))
                ),
            )
            self.table.setItem(row, 2, QtWidgets.QTableWidgetItem(node_path))
            mode = QtWidgets.QComboBox()
            mode.addItem("Replace Path", "replace")
            mode.addItem("Disable Job", "disable")
            mode.addItem("Remove Job", "remove")
            mode.setCurrentIndex(1)
            mode.setProperty("queueId", queue_id)
            mode.setProperty("jobId", job_id)
            self.table.setCellWidget(row, 3, mode)
            self.table.setCellWidget(row, 4, QtWidgets.QLineEdit())
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)
        use_selected = make_button(
            "Use Selected Houdini Node", self._use_selected_node
        )
        layout.addWidget(use_selected, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText(
            "Apply Resolutions"
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _use_selected_node(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QtWidgets.QMessageBox.warning(
                self, "Resolve Missing Nodes", "Select a table row first."
            )
            return
        try:
            import hou

            nodes = list(hou.selectedNodes())
        except Exception:
            nodes = []
        if not nodes:
            QtWidgets.QMessageBox.warning(
                self, "Resolve Missing Nodes", "No Houdini node is selected."
            )
            return
        mode = self.table.cellWidget(row, 3)
        replacement = self.table.cellWidget(row, 4)
        if isinstance(mode, QtWidgets.QComboBox):
            mode.setCurrentIndex(mode.findData("replace"))
        if isinstance(replacement, QtWidgets.QLineEdit):
            replacement.setText(nodes[-1].path())

    def _validate_and_accept(self) -> None:
        for row in range(self.table.rowCount()):
            mode = self.table.cellWidget(row, 3)
            replacement = self.table.cellWidget(row, 4)
            if (
                isinstance(mode, QtWidgets.QComboBox)
                and mode.currentData() == "replace"
                and (
                    not isinstance(replacement, QtWidgets.QLineEdit)
                    or not replacement.text().strip().startswith("/")
                )
            ):
                QtWidgets.QMessageBox.warning(
                    self,
                    "Resolve Missing Nodes",
                    f"Row {row + 1} requires an absolute replacement path.",
                )
                return
        self.accept()

    def apply_resolutions(self) -> None:
        from hcq.import_export import replace_job_node

        for row in range(self.table.rowCount()):
            mode = self.table.cellWidget(row, 3)
            replacement = self.table.cellWidget(row, 4)
            if not isinstance(mode, QtWidgets.QComboBox):
                continue
            resolution = str(mode.currentData())
            path = (
                replacement.text().strip()
                if isinstance(replacement, QtWidgets.QLineEdit)
                else ""
            )
            replace_job_node(
                self.queues,
                str(mode.property("queueId")),
                str(mode.property("jobId")),
                path if resolution == "replace" else None,
                disable=resolution == "disable",
                remove=resolution == "remove",
            )


class OutputInspectionDialog(QtWidgets.QDialog):
    """Display recovery output evidence without inferring job completion."""

    def __init__(
        self,
        inspections: list[Any],
        open_folder: Any = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self._open_folder = open_folder
        self.setWindowTitle("Inspect Interrupted Output")
        self.resize(820, 380)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "Output presence does not prove that an interrupted job completed."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Path", "Exists", "Size", "Modified"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        for inspection in inspections:
            row = self.table.rowCount()
            self.table.insertRow(row)
            modified = item_value(inspection, "modified_at", None)
            values = [
                item_value(inspection, "path", ""),
                "Yes" if item_value(inspection, "exists", False) else "No",
                (
                    str(item_value(inspection, "size_bytes", ""))
                    if item_value(inspection, "size_bytes", None) is not None
                    else ""
                ),
                str(modified or ""),
            ]
            for column, value in enumerate(values):
                self.table.setItem(
                    row, column, QtWidgets.QTableWidgetItem(str(value))
                )
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)
        if not inspections:
            layout.addWidget(
                QtWidgets.QLabel(
                    "No expected output paths were recorded for the interrupted job."
                )
            )
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        open_button = buttons.addButton(
            "Open Output Folder",
            QtWidgets.QDialogButtonBox.ButtonRole.ActionRole,
        )
        open_button.setEnabled(bool(inspections) and callable(open_folder))
        open_button.clicked.connect(self._open_selected)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 and self.table.rowCount():
            row = 0
        item = self.table.item(row, 0) if row >= 0 else None
        if item is not None and callable(self._open_folder):
            self._open_folder(item.text())


class RecoveryDialog(QtWidgets.QDialog):
    """Resolve an active status file left by an interrupted Houdini process."""

    actionSelected = QtCore.Signal(str)

    def __init__(
        self,
        session: Any,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(text.RECOVERY_TITLE)
        self.resize(560, 330)
        self.action = ""
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(text.INTERRUPTED_FOUND)
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        data = mapping(session)
        current_id = data.get("current_job_id", "")
        jobs = sequence(data.get("jobs"))
        current = next(
            (job for job in jobs if item_value(job, "job_id", "") == current_id),
            jobs[-1] if jobs else {},
        )
        details = QtWidgets.QFormLayout()
        details.addRow("Session", QtWidgets.QLabel(str(
            data.get("session_id", data.get("id", text.UNKNOWN))
        )))
        details.addRow("Last Job", QtWidgets.QLabel(str(
            item_value(current, "display_name", current_id or text.UNKNOWN)
        )))
        details.addRow("Last Known State", QtWidgets.QLabel(str(
            item_value(current, "state", data.get("state", text.UNKNOWN))
        ).title()))
        details.addRow("HIP File", QtWidgets.QLabel(str(data.get("hip_file", ""))))
        layout.addLayout(details)
        layout.addStretch(1)
        grid = QtWidgets.QGridLayout()
        actions = [
            ("Inspect Output", "inspect_output"),
            ("Retry This Job", "retry_job"),
            ("Restart Queue", "restart_queue"),
            ("Mark Complete", "mark_complete"),
            ("Archive Interrupted", "archive"),
        ]
        for index, (label, action) in enumerate(actions):
            button = make_button(label, lambda _checked=False, a=action: self._choose(a))
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)
        dismiss = make_button("Dismiss", self.reject)
        layout.addWidget(dismiss, 0, QtCore.Qt.AlignmentFlag.AlignRight)

    def _choose(self, action: str) -> None:
        self.action = action
        self.actionSelected.emit(action)
        self.accept()


class ErrorDecisionDialog(QtWidgets.QDialog):
    """Retry/skip/stop prompt for wait-for-user jobs."""

    def __init__(
        self,
        job_name: str,
        error: str,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(text.ERROR_DECISION_TITLE)
        self.decision = "stop"
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(f"{job_name} failed.")
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)
        details = QtWidgets.QPlainTextEdit(error)
        details.setReadOnly(True)
        details.setMinimumSize(500, 150)
        layout.addWidget(details)
        buttons = QtWidgets.QDialogButtonBox()
        for label, result, role in (
            (text.RETRY, "retry", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole),
            (text.SKIP, "skip", QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole),
            (text.STOP, "stop", QtWidgets.QDialogButtonBox.ButtonRole.RejectRole),
        ):
            button = buttons.addButton(label, role)
            button.clicked.connect(lambda _checked=False, r=result: self._choose(r))
        layout.addWidget(buttons)

    def _choose(self, decision: str) -> None:
        self.decision = decision
        self.accept()


class RunConfirmDialog(QtWidgets.QDialog):
    def __init__(
        self,
        queue_count: int,
        job_count: int,
        settings: Any = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(text.RUN_CONFIRM_TITLE)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.addRow("Queues", QtWidgets.QLabel(str(queue_count)))
        form.addRow("Jobs", QtWidgets.QLabel(str(job_count)))
        self.save_mode = QtWidgets.QComboBox()
        for label, data in (
            ("Always Save", "always"),
            ("Ask Before Saving", "ask"),
            ("Do Not Save", "never"),
        ):
            self.save_mode.addItem(label, data)
        current = item_value(settings, "save_before_running", "always")
        index = self.save_mode.findData(current)
        self.save_mode.setCurrentIndex(max(index, 0))
        self.backup = QtWidgets.QCheckBox("Create a Backup Before Saving")
        self.backup.setChecked(
            bool(item_value(settings, "create_backup_before_saving", False))
        )
        form.addRow("Save Before Running", self.save_mode)
        form.addRow("", self.backup)
        layout.addLayout(form)
        warning = QtWidgets.QLabel(text.FOREGROUND_WARNING)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText(
            "Save and Run"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
