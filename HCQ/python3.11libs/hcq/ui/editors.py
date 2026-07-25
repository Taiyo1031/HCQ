"""Queue and job editing widgets."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from PySide6 import QtCore, QtGui, QtWidgets

from . import text
from .bridge import item_value, mapping
from .common import (
    ReorderTable,
    compact_button_row,
    make_button,
    set_row,
    show_error,
    show_warning,
)

try:
    from hcq.models import CpuSetting, FrameRange, Job, QueueTemplate
except ImportError:  # pragma: no cover - installed with the core package
    CpuSetting = FrameRange = Job = QueueTemplate = None  # type: ignore


ACTION_ITEMS = [
    ("Auto Detect", "auto_detect"),
    ("File Cache — Save to Disk", "filecache_save_to_disk"),
    ("ROP Render", "rop_render"),
    ("TOP Cook", "top_cook"),
    ("Force Cook Node", "force_cook"),
    ("Press Button Parameter", "press_button"),
]
CPU_ITEMS = [
    ("Use Queue Setting", "inherit"),
    ("Use Current Houdini Setting", "current"),
    ("Use All Threads", "all"),
    ("Fixed Thread Count", "threads"),
    ("Reserve Threads", "reserve"),
    ("Single Thread", "single"),
]
QUEUE_CPU_ITEMS = [item for item in CPU_ITEMS if item[1] != "inherit"]
HIP_ITEMS = [
    ("Use Queue HIP", "queue"),
    ("Use Current HIP", "current"),
    ("Specify HIP Path", "path"),
]
FRAME_ITEMS = [
    ("Use Node Settings", "node"),
    ("Use Houdini Playback Range", "playback"),
    ("Custom Range", "custom"),
]
ERROR_ITEMS = [
    ("Stop Queue", "stop_queue"),
    ("Skip Job and Continue", "skip_continue"),
    ("Wait for User Decision", "wait_for_user"),
]
VERIFY_ITEMS = [("Basic", "basic"), ("None", "none")]


def _fill_combo(combo: QtWidgets.QComboBox, items: list[tuple[str, str]]) -> None:
    for label, data in items:
        combo.addItem(label, data)


def _select_data(combo: QtWidgets.QComboBox, data: Any) -> None:
    index = combo.findData(data)
    combo.setCurrentIndex(index if index >= 0 else 0)


class JobSettingsWidget(QtWidgets.QWidget):
    """Form for every public HCQ job setting."""

    changed = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._job: Any = None
        layout = QtWidgets.QFormLayout(self)
        layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self.enabled = QtWidgets.QCheckBox("Enabled")
        self.display_name = QtWidgets.QLineEdit()
        self.node_path = QtWidgets.QLineEdit()
        self.hip_mode = QtWidgets.QComboBox()
        _fill_combo(self.hip_mode, HIP_ITEMS)
        self.hip_path = QtWidgets.QLineEdit()
        self.action = QtWidgets.QComboBox()
        _fill_combo(self.action, ACTION_ITEMS)
        self.button_parameter = QtWidgets.QLineEdit()
        self.button_parameter.setPlaceholderText("Button parameter name")

        self.frame_mode = QtWidgets.QComboBox()
        _fill_combo(self.frame_mode, FRAME_ITEMS)
        self.frame_start = QtWidgets.QSpinBox()
        self.frame_start.setRange(-1_000_000, 1_000_000)
        self.frame_end = QtWidgets.QSpinBox()
        self.frame_end.setRange(-1_000_000, 1_000_000)
        self.frame_step = QtWidgets.QSpinBox()
        self.frame_step.setRange(1, 1_000_000)
        frame_row = QtWidgets.QHBoxLayout()
        for label, control in (
            ("Start", self.frame_start),
            ("End", self.frame_end),
            ("Step", self.frame_step),
        ):
            frame_row.addWidget(QtWidgets.QLabel(label))
            frame_row.addWidget(control)

        self.cpu_mode = QtWidgets.QComboBox()
        _fill_combo(self.cpu_mode, CPU_ITEMS)
        self.cpu_value = QtWidgets.QSpinBox()
        self.cpu_value.setRange(1, 1024)
        cpu_row = QtWidgets.QHBoxLayout()
        cpu_row.addWidget(self.cpu_mode, 1)
        cpu_row.addWidget(self.cpu_value)

        self.on_error = QtWidgets.QComboBox()
        _fill_combo(self.on_error, ERROR_ITEMS)
        self.retry_count = QtWidgets.QSpinBox()
        self.retry_count.setRange(0, 100)
        self.verification = QtWidgets.QComboBox()
        _fill_combo(self.verification, VERIFY_ITEMS)
        self.expected_outputs = QtWidgets.QPlainTextEdit()
        self.expected_outputs.setPlaceholderText("One optional output pattern per line")
        self.expected_outputs.setMaximumHeight(68)
        self.notify_complete = QtWidgets.QCheckBox("Notify on Completion")
        self.notify_failure = QtWidgets.QCheckBox("Notify on Failure")
        notification_row = QtWidgets.QHBoxLayout()
        notification_row.addWidget(self.notify_complete)
        notification_row.addWidget(self.notify_failure)
        notification_row.addStretch(1)

        layout.addRow("", self.enabled)
        layout.addRow("Display Name", self.display_name)
        layout.addRow("Node Path", self.node_path)
        layout.addRow("HIP File", self.hip_mode)
        layout.addRow("HIP Path", self.hip_path)
        layout.addRow("Action", self.action)
        layout.addRow("Button Parameter", self.button_parameter)
        layout.addRow("Frame Range", self.frame_mode)
        layout.addRow("", frame_row)
        layout.addRow("CPU", cpu_row)
        layout.addRow("On Error", self.on_error)
        layout.addRow("Retry Count", self.retry_count)
        layout.addRow("Output Verification", self.verification)
        layout.addRow("Expected Outputs", self.expected_outputs)
        layout.addRow("Notifications", notification_row)

        self.frame_mode.currentIndexChanged.connect(self._sync_visibility)
        self.cpu_mode.currentIndexChanged.connect(self._sync_visibility)
        self.hip_mode.currentIndexChanged.connect(self._sync_visibility)
        self.action.currentIndexChanged.connect(self._sync_visibility)
        for widget in self.findChildren(QtWidgets.QWidget):
            for signal_name in (
                "textChanged",
                "valueChanged",
                "toggled",
                "currentIndexChanged",
            ):
                signal = getattr(widget, signal_name, None)
                if signal is not None:
                    try:
                        signal.connect(self.changed)
                    except (TypeError, RuntimeError):
                        pass
        self.setEnabled(False)
        self._sync_visibility()

    def _sync_visibility(self) -> None:
        custom = self.frame_mode.currentData() == "custom"
        for widget in (self.frame_start, self.frame_end, self.frame_step):
            widget.setEnabled(custom)
        self.cpu_value.setEnabled(self.cpu_mode.currentData() in {"threads", "reserve"})
        self.hip_path.setEnabled(self.hip_mode.currentData() == "path")
        self.button_parameter.setEnabled(self.action.currentData() == "press_button")

    def set_job(self, job: Any) -> None:
        self._job = job
        self.setEnabled(job is not None)
        if job is None:
            return
        blocked = self.blockSignals(True)
        try:
            self.enabled.setChecked(bool(item_value(job, "enabled", True)))
            self.display_name.setText(str(item_value(job, "display_name", "")))
            self.node_path.setText(str(item_value(job, "node_path", "")))
            _select_data(self.hip_mode, item_value(job, "hip_file_mode", "queue"))
            self.hip_path.setText(str(item_value(job, "hip_file", "")))
            _select_data(self.action, item_value(job, "action", "auto_detect"))
            self.button_parameter.setText(
                str(item_value(job, "button_parameter", ""))
            )
            frame = item_value(job, "frame_range", {})
            _select_data(self.frame_mode, item_value(frame, "mode", "node"))
            self.frame_start.setValue(int(item_value(frame, "start", 1) or 1))
            self.frame_end.setValue(int(item_value(frame, "end", 240) or 240))
            self.frame_step.setValue(int(item_value(frame, "step", 1) or 1))
            cpu = item_value(job, "cpu", {})
            _select_data(self.cpu_mode, item_value(cpu, "mode", "inherit"))
            self.cpu_value.setValue(int(item_value(cpu, "value", 1) or 1))
            _select_data(self.on_error, item_value(job, "on_error", "stop_queue"))
            self.retry_count.setValue(int(item_value(job, "retry_count", 0)))
            _select_data(
                self.verification, item_value(job, "verification", "basic")
            )
            self.expected_outputs.setPlainText(
                "\n".join(item_value(job, "expected_outputs", []) or [])
            )
            self.notify_complete.setChecked(
                bool(item_value(job, "notify_on_complete", True))
            )
            self.notify_failure.setChecked(
                bool(item_value(job, "notify_on_failure", True))
            )
        finally:
            self.blockSignals(blocked)
        self._sync_visibility()

    def apply(self) -> Any:
        job = self._job
        if job is None:
            return None
        data = {
            "enabled": self.enabled.isChecked(),
            "display_name": self.display_name.text().strip() or "Untitled Job",
            "node_path": self.node_path.text().strip(),
            "hip_file_mode": self.hip_mode.currentData(),
            "hip_file": self.hip_path.text().strip(),
            "action": self.action.currentData(),
            "button_parameter": self.button_parameter.text().strip(),
            "on_error": self.on_error.currentData(),
            "retry_count": self.retry_count.value(),
            "verification": self.verification.currentData(),
            "expected_outputs": [
                line.strip()
                for line in self.expected_outputs.toPlainText().splitlines()
                if line.strip()
            ],
            "notify_on_complete": self.notify_complete.isChecked(),
            "notify_on_failure": self.notify_failure.isChecked(),
        }
        frame_data = {
            "mode": self.frame_mode.currentData(),
            "start": self.frame_start.value(),
            "end": self.frame_end.value(),
            "step": self.frame_step.value(),
        }
        cpu_data = {
            "mode": self.cpu_mode.currentData(),
            "value": self.cpu_value.value(),
        }
        if isinstance(job, dict):
            job.update(data)
            job["frame_range"] = frame_data
            job["cpu"] = cpu_data
        else:
            for name, value in data.items():
                setattr(job, name, value)
            if FrameRange is not None:
                job.frame_range = FrameRange(**frame_data)
            else:
                job.frame_range = frame_data
            if CpuSetting is not None:
                job.cpu = CpuSetting(**cpu_data)
            else:
                job.cpu = cpu_data
        return job


class QueueEditorDialog(QtWidgets.QDialog):
    """Modeless editor that commits its deep copy only through Save."""

    def __init__(
        self,
        queue: Any | None = None,
        parent: QtWidgets.QWidget | None = None,
        *,
        save_handler: Callable[[Any], Any] | None = None,
        existing_queue: bool | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.setWindowTitle(text.QUEUE_EDITOR_TITLE)
        self.resize(980, 720)
        self._save_handler = save_handler
        self._existing_queue = (
            queue is not None if existing_queue is None else existing_queue
        )
        self._committing = False
        self._completed = False
        if queue is not None:
            self.queue = copy.deepcopy(queue)
        elif QueueTemplate is not None:
            self.queue = QueueTemplate()
        else:
            self.queue = {
                "name": "Untitled Queue",
                "description": "",
                "group": "",
                "favorite": False,
                "hip_file": "",
                "jobs": [],
            }
        self._dirty = False
        self._build()
        self._load_queue()
        self._connect_queue_changes()
        self._dirty = False

    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit()
        self.group = QtWidgets.QLineEdit()
        self.description = QtWidgets.QLineEdit()
        self.hip_file = QtWidgets.QLineEdit()
        self.favorite = QtWidgets.QCheckBox("Favorite")
        self.cpu_mode = QtWidgets.QComboBox()
        _fill_combo(self.cpu_mode, QUEUE_CPU_ITEMS)
        self.cpu_value = QtWidgets.QSpinBox()
        self.cpu_value.setRange(1, 1024)
        self.cpu_value.setValue(1)
        cpu_row = QtWidgets.QHBoxLayout()
        cpu_row.addWidget(self.cpu_mode, 1)
        cpu_row.addWidget(self.cpu_value)
        self.cpu_mode.currentIndexChanged.connect(self._sync_cpu_value)
        form.addRow("Name", self.name)
        form.addRow("Group", self.group)
        form.addRow("Description", self.description)
        form.addRow("Queue HIP", self.hip_file)
        form.addRow("Queue CPU", cpu_row)
        form.addRow("", self.favorite)
        outer.addLayout(form)

        self.add_selected = make_button(text.ADD_SELECTED_NODES, self._add_selected)
        self.add_path = make_button(text.ADD_BY_PATH, self._add_by_path)
        self.import_jobs = make_button(text.IMPORT_JOBS, self._import_jobs)
        self.add_order = QtWidgets.QComboBox()
        self.add_order.addItems(
            ["Selection Order", "Network Dependency Order", "Node Name Order"]
        )
        tools = compact_button_row(
            self.add_selected, self.add_path, self.import_jobs, QtWidgets.QLabel("Add Order")
        )
        tools.addWidget(self.add_order)
        outer.addLayout(tools)

        splitter = QtWidgets.QSplitter()
        self.jobs = ReorderTable(["#", "Job", "Node", "Action", "CPU"])
        self.jobs.setMinimumWidth(480)
        self.jobs.currentCellChanged.connect(self._select_job)
        self.jobs.itemChanged.connect(self._job_check_changed)
        self.jobs.orderChanged.connect(self._reordered)
        splitter.addWidget(self.jobs)
        settings_group = QtWidgets.QGroupBox(text.JOB_SETTINGS)
        settings_layout = QtWidgets.QVBoxLayout(settings_group)
        self.job_settings = JobSettingsWidget()
        self.job_settings.changed.connect(self._job_changed)
        settings_layout.addWidget(self.job_settings)
        splitter.addWidget(settings_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        up = make_button(text.MOVE_UP, lambda: self._move(-1))
        down = make_button(text.MOVE_DOWN, lambda: self._move(1))
        duplicate = make_button(text.DUPLICATE, self._duplicate_job)
        toggle = make_button("Enable / Disable", self._toggle_job)
        remove = make_button(text.REMOVE, self._remove_job)
        outer.addLayout(compact_button_row(up, down, duplicate, toggle, remove))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Discard
        )
        save_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Save)
        save_button.setText(text.SAVE)
        save_as = buttons.addButton(
            text.SAVE_AS, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
        )
        discard = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Discard)
        discard.setText(text.DISCARD)
        save_button.clicked.connect(lambda: self._save_and_close(False))
        save_as.clicked.connect(lambda: self._save_and_close(True))
        discard.clicked.connect(self._discard)
        outer.addWidget(buttons)

    def _connect_queue_changes(self) -> None:
        for widget, signal_name in (
            (self.name, "textChanged"),
            (self.group, "textChanged"),
            (self.description, "textChanged"),
            (self.hip_file, "textChanged"),
            (self.favorite, "toggled"),
            (self.cpu_mode, "currentIndexChanged"),
            (self.cpu_value, "valueChanged"),
        ):
            getattr(widget, signal_name).connect(self._mark_dirty)

    def _mark_dirty(self, *_args: Any) -> None:
        if not self._completed:
            self._dirty = True

    def _jobs(self) -> list[Any]:
        if isinstance(self.queue, dict):
            return self.queue.setdefault("jobs", [])
        return self.queue.jobs

    def _load_queue(self) -> None:
        self.name.setText(str(item_value(self.queue, "name", "Untitled Queue")))
        self.group.setText(str(item_value(self.queue, "group", "")))
        self.description.setText(str(item_value(self.queue, "description", "")))
        self.hip_file.setText(str(item_value(self.queue, "hip_file", "")))
        self.favorite.setChecked(bool(item_value(self.queue, "favorite", False)))
        cpu = item_value(self.queue, "cpu", {})
        _select_data(self.cpu_mode, item_value(cpu, "mode", "current"))
        self.cpu_value.setValue(int(item_value(cpu, "value", 1) or 1))
        self._sync_cpu_value()
        self._refresh_jobs()

    def _sync_cpu_value(self) -> None:
        self.cpu_value.setEnabled(
            self.cpu_mode.currentData() in {"threads", "reserve"}
        )

    def _refresh_jobs(self, current: Any = None) -> None:
        self.jobs.blockSignals(True)
        self.jobs.setRowCount(0)
        for row, job in enumerate(self._jobs()):
            cpu = item_value(job, "cpu", {})
            cpu_label = item_value(cpu, "mode", "inherit")
            set_row(
                self.jobs,
                row,
                [
                    row + 1,
                    item_value(job, "display_name", "Untitled Job"),
                    item_value(job, "node_path", ""),
                    item_value(job, "action", "auto_detect"),
                    cpu_label,
                ],
                job,
                checked=bool(item_value(job, "enabled", True)),
            )
            if job is current:
                self.jobs.selectRow(row)
        self.jobs.blockSignals(False)
        self.jobs.resizeColumnsToContents()

    def _new_job(self, node_path: str, name: str = "") -> Any:
        if Job is not None:
            return Job(
                display_name=name or Path(node_path).name or "Untitled Job",
                node_path=node_path,
            )
        return {
            "display_name": name or Path(node_path).name or "Untitled Job",
            "node_path": node_path,
            "enabled": True,
            "action": "auto_detect",
        }

    def _add_selected(self) -> None:
        try:
            import hou

            nodes = list(hou.selectedNodes())
            if self.add_order.currentIndex() == 1:
                nodes.sort(key=lambda node: (len(node.inputAncestors()), node.path()))
            elif self.add_order.currentIndex() == 2:
                nodes.sort(key=lambda node: node.name().lower())
            for node in nodes:
                job = self._new_job(node.path(), node.name())
                try:
                    job.node_type = node.type().nameWithCategory()
                except Exception:
                    pass
                self._jobs().append(job)
            self._dirty = self._dirty or bool(nodes)
            self._refresh_jobs()
        except Exception:
            show_warning(self, "No Houdini nodes are selected.")

    def _add_by_path(self) -> None:
        node_path, accepted = QtWidgets.QInputDialog.getText(
            self, text.ADD_BY_PATH, "Node Path"
        )
        if accepted and node_path.strip():
            job = self._new_job(node_path.strip())
            self._jobs().append(job)
            self._dirty = True
            self._refresh_jobs(job)

    def _import_jobs(self) -> None:
        path, _selected = QtWidgets.QFileDialog.getOpenFileName(
            self, text.IMPORT_JSON, "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            from hcq.import_export import missing_node_paths, remap_document_paths
            from hcq.utils import new_id
            from hcq.validation import parse_queue_document
            from .bridge import mapping
            from .dialogs import ImportPreviewDialog, MissingNodesDialog

            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
            preview = ImportPreviewDialog(document, self)
            if preview.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            selected = preview.selected_queues()
            selected_document = copy.deepcopy(document)
            selected_document["queues"] = [
                copy.deepcopy(mapping(queue)) for queue in selected
            ]
            for source, target in preview.path_mappings:
                selected_document = remap_document_paths(
                    selected_document, source, target
                )
            queues = parse_queue_document(selected_document)
            try:
                import hou

                missing = missing_node_paths(queues, hou.node)
            except Exception:
                missing = []
            if missing:
                resolution = MissingNodesDialog(queues, missing, self)
                if resolution.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                    return
                resolution.apply_resolutions()
            imported_jobs: list[Any] = []
            for queue in queues:
                for job in queue.jobs:
                    clone = copy.deepcopy(job)
                    clone.id = new_id("job")
                    imported_jobs.append(clone)
            self._jobs().extend(imported_jobs)
            self._dirty = self._dirty or bool(imported_jobs)
            self._refresh_jobs(imported_jobs[-1] if imported_jobs else None)
        except Exception as error:
            show_error(self, f"Could not import jobs:\n{error}")

    def _select_job(self, row: int, _column: int, *_unused: Any) -> None:
        item = self.jobs.item(row, 0)
        self.job_settings.set_job(
            item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
        )

    def _job_changed(self) -> None:
        current = self.job_settings.apply()
        if current is not None:
            self._dirty = True
            self._refresh_jobs(current)

    def _job_check_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        job = item.data(QtCore.Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == QtCore.Qt.CheckState.Checked
        if isinstance(job, dict):
            job["enabled"] = enabled
        elif job is not None:
            job.enabled = enabled
        self._dirty = True

    def _reordered(self, jobs: list[Any]) -> None:
        target = self._jobs()
        target[:] = jobs
        self._dirty = True
        self._refresh_jobs()

    def _move(self, offset: int) -> None:
        row = self.jobs.currentRow()
        target = row + offset
        jobs = self._jobs()
        if not (0 <= row < len(jobs) and 0 <= target < len(jobs)):
            return
        jobs[row], jobs[target] = jobs[target], jobs[row]
        self._dirty = True
        self._refresh_jobs(jobs[target])

    def _duplicate_job(self) -> None:
        job = self.jobs.current_object()
        if job is None:
            return
        clone = copy.deepcopy(job)
        if isinstance(clone, dict):
            clone.pop("id", None)
            clone["display_name"] = f"{clone.get('display_name', 'Job')} Copy"
        else:
            try:
                from hcq.utils import new_id

                clone.id = new_id("job")
            except Exception:
                pass
            clone.display_name = f"{clone.display_name} Copy"
        self._jobs().append(clone)
        self._dirty = True
        self._refresh_jobs(clone)

    def _toggle_job(self) -> None:
        job = self.jobs.current_object()
        if job is None:
            return
        enabled = not bool(item_value(job, "enabled", True))
        if isinstance(job, dict):
            job["enabled"] = enabled
        else:
            job.enabled = enabled
        self._dirty = True
        self._refresh_jobs(job)

    def _remove_job(self) -> None:
        selected = self.jobs.selected_objects()
        jobs = self._jobs()
        jobs[:] = [job for job in jobs if job not in selected]
        self._dirty = self._dirty or bool(selected)
        self._refresh_jobs()

    def _apply_fields(self) -> Any:
        self.job_settings.apply()
        cpu = {
            "mode": self.cpu_mode.currentData(),
            "value": (
                self.cpu_value.value()
                if self.cpu_mode.currentData() in {"threads", "reserve"}
                else None
            ),
        }
        data = {
            "name": self.name.text().strip() or "Untitled Queue",
            "group": self.group.text().strip(),
            "description": self.description.text().strip(),
            "hip_file": self.hip_file.text().strip(),
            "favorite": self.favorite.isChecked(),
        }
        if isinstance(self.queue, dict):
            self.queue.update(data)
            self.queue["cpu"] = {
                key: value for key, value in cpu.items() if value is not None
            }
        else:
            for key, value in data.items():
                setattr(self.queue, key, value)
            self.queue.cpu = CpuSetting(**cpu) if CpuSetting is not None else cpu
            normalize = getattr(self.queue, "normalize_order", None)
            if callable(normalize):
                normalize()
        return self.queue

    def _save_candidate(self, save_as: bool) -> Any:
        queue = self._apply_fields()
        if not (save_as and self._existing_queue):
            return queue
        candidate = copy.deepcopy(queue)
        from hcq.utils import new_id, now_iso

        timestamp = now_iso()
        if isinstance(candidate, dict):
            candidate["id"] = new_id("queue")
            candidate["created_at"] = timestamp
            candidate["updated_at"] = timestamp
            for job in candidate.get("jobs", []):
                if isinstance(job, dict):
                    job["id"] = new_id("job")
        else:
            candidate.id = new_id("queue")
            candidate.created_at = timestamp
            candidate.updated_at = timestamp
            for job in item_value(candidate, "jobs", []):
                job.id = new_id("job")
        return candidate

    def _commit(self, save_as: bool) -> bool:
        if self._completed or self._committing:
            return False
        self._committing = True
        try:
            candidate = self._save_candidate(save_as)
            if self._save_handler is not None:
                self._save_handler(candidate)
            self.queue = candidate
            self._dirty = False
            self._completed = True
            self.setProperty("saveAs", save_as)
            return True
        except Exception as error:
            show_error(self, f"Could not save the queue:\n{error}")
            return False
        finally:
            self._committing = False

    def _save_and_close(self, save_as: bool) -> None:
        if self._commit(save_as):
            self.setResult(QtWidgets.QDialog.DialogCode.Accepted)
            self.close()

    def _discard(self) -> None:
        if self._dirty:
            decision = QtWidgets.QMessageBox.question(
                self,
                "Discard Changes",
                "Discard all unsaved queue changes?",
                QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel,
            )
            if decision != QtWidgets.QMessageBox.StandardButton.Discard:
                return
        self._dirty = False
        self._completed = True
        self.setResult(QtWidgets.QDialog.DialogCode.Rejected)
        self.close()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._completed or not self._dirty:
            event.accept()
            return
        decision = QtWidgets.QMessageBox.warning(
            self,
            "Unsaved Queue Changes",
            "Save changes before closing the Queue Editor?",
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Save,
        )
        if decision == QtWidgets.QMessageBox.StandardButton.Save:
            if self._commit(False):
                self.setResult(QtWidgets.QDialog.DialogCode.Accepted)
                event.accept()
            else:
                event.ignore()
        elif decision == QtWidgets.QMessageBox.StandardButton.Discard:
            self._dirty = False
            self._completed = True
            self.setResult(QtWidgets.QDialog.DialogCode.Rejected)
            event.accept()
        else:
            event.ignore()

    def reject(self) -> None:
        self._discard()

    def _accept(self) -> None:
        """Compatibility helper for non-interactive smoke tests."""
        self._apply_fields()
        self._dirty = False
        self._completed = True
        super().accept()
