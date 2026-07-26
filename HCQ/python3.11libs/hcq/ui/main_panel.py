"""Main dockable HCQ Python Panel widget."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from hcq.constants import USAGE_URL

from . import text
from .bridge import call, connect_refresh, item_value, value
from .dialogs import OutputInspectionDialog, RecoveryDialog
from .tabs import HistoryTab, MonitorTab, QueuesTab, RunTab, SettingsTab
from .toast import ToastArea


class _UpdateSignals(QtCore.QObject):
    finished = QtCore.Signal(object)


class _UpdateTask(QtCore.QRunnable):
    def __init__(self, updater: Any):
        super().__init__()
        self.updater = updater
        self.signals = _UpdateSignals()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            result = self.updater.check_and_stage()
        except Exception as error:
            result = error
        self.signals.finished.emit(result)


class HCQPanel(QtWidgets.QWidget):
    """Shared-manager view used by Houdini's Python Panel interface."""

    def __init__(
        self,
        manager: Any,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.setObjectName("hcqMainPanel")
        self.setWindowTitle(text.APP_TITLE)
        self.setMinimumSize(520, 420)
        self._active_update_task: _UpdateTask | None = None
        self._build()
        self._disconnect_refresh = connect_refresh(manager, self.refresh)
        call(manager, "refresh_all")
        self.refresh()
        QtCore.QTimer.singleShot(0, self._offer_recovery)

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        header = QtWidgets.QVBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        title_row = QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self.title_label = QtWidgets.QLabel(text.APP_TITLE)
        self.title_label.setStyleSheet("font-weight: bold;")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.usage_button = self._header_button(
            text.USAGE, text.USAGE_TOOLTIP, self._open_usage
        )
        self.update_button = self._header_button(
            text.UPDATE,
            text.UPDATE_TOOLTIP,
            self._check_for_updates,
            text.CHECKING_FOR_UPDATES,
        )
        title_row.addWidget(self.usage_button)
        title_row.addWidget(self.update_button)
        header.addLayout(title_row)
        status_row = QtWidgets.QHBoxLayout()
        self.monitor_status = QtWidgets.QLabel(text.MONITOR_ON)
        self.queue_status = QtWidgets.QLabel(text.QUEUE_IDLE)
        self.environment_status = QtWidgets.QLabel(text.HOUDINI_REQUIREMENT)
        status_row.addWidget(self.monitor_status)
        status_row.addWidget(self.queue_status)
        status_row.addStretch(1)
        status_row.addWidget(self.environment_status)
        header.addLayout(status_row)
        layout.addLayout(header)

        self.toast_area = ToastArea()
        layout.addWidget(self.toast_area)

        self.tabs = QtWidgets.QTabWidget()
        self.monitor_tab = MonitorTab(self.manager)
        self.queues_tab = QueuesTab(self.manager)
        self.run_tab = RunTab(self.manager)
        self.history_tab = HistoryTab(self.manager)
        self.settings_tab = SettingsTab(self.manager)
        for label, tab in (
            (text.TAB_MONITOR, self.monitor_tab),
            (text.TAB_QUEUES, self.queues_tab),
            (text.TAB_RUN, self.run_tab),
            (text.TAB_HISTORY, self.history_tab),
            (text.TAB_SETTINGS, self.settings_tab),
        ):
            self.tabs.addTab(tab, label)
        settings = value(self.manager, "settings", {}) or {}
        index = (
            settings.get("last_opened_tab", 0)
            if isinstance(settings, dict)
            else item_value(settings, "last_opened_tab", 0)
        )
        self.tabs.setCurrentIndex(max(0, min(int(index), self.tabs.count() - 1)))
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs, 1)

    @staticmethod
    def _header_button(
        label: str,
        tooltip: str,
        callback: Any,
        *alternate_labels: str,
    ) -> QtWidgets.QToolButton:
        button = QtWidgets.QToolButton()
        button.setText(label)
        button.setToolTip(tooltip)
        button.setAccessibleName(label)
        button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        button.setAutoRaise(False)
        button.ensurePolished()
        font_metrics = button.fontMetrics()
        text_width = max(
            font_metrics.horizontalAdvance(value)
            for value in (label, *alternate_labels)
        )
        button.setMinimumWidth(
            max(button.sizeHint().width(), text_width + 20)
        )
        button.setMinimumHeight(max(button.sizeHint().height(), 24))
        button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        button.clicked.connect(callback)
        return button

    def _open_url(self, url: str) -> bool:
        opened = QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))
        if not opened:
            self.show_notification(
                "Could Not Open Browser",
                f"Open this URL manually:\n{url}",
                timeout_ms=0,
            )
        return bool(opened)

    def _open_usage(self) -> None:
        self._open_url(USAGE_URL)

    def _check_for_updates(self) -> None:
        if self._active_update_task is not None:
            return
        updater = value(self.manager, "updater")
        if updater is None:
            self.show_notification(
                "Update Unavailable",
                "The HCQ update service is not available.",
                timeout_ms=0,
            )
            return
        self.update_button.setEnabled(False)
        self.update_button.setText(text.CHECKING_FOR_UPDATES)
        task = _UpdateTask(updater)
        self._active_update_task = task
        task.signals.finished.connect(self._update_finished)
        QtCore.QThreadPool.globalInstance().start(task)

    @QtCore.Slot(object)
    def _update_finished(self, result: Any) -> None:
        self._active_update_task = None
        self.update_button.setEnabled(True)
        self.update_button.setText(text.UPDATE)
        if isinstance(result, Exception):
            self.show_notification(
                "Update Failed",
                f"Could not check for updates: {result}",
                timeout_ms=0,
            )
            return
        status = str(getattr(result, "status", "error"))
        message = str(
            getattr(result, "message", "The update check did not complete.")
        )
        release_url = str(getattr(result, "release_url", ""))
        if status in {"ready", "migration_ready"}:
            self._offer_update_restart(result, release_url)
            return
        actions = []
        if status in {"manual_required", "unavailable", "error"} and release_url:
            actions.append(
                ("Open Release", lambda url=release_url: self._open_url(url))
            )
        title = {
            "ready": "Update Ready",
            "migration_ready": "Standard Installation Ready",
            "up_to_date": "HCQ Is Up to Date",
            "no_release": "No Release Available",
            "busy": "Update Already in Progress",
            "manual_required": "Manual Update Required",
            "unavailable": "Update Files Unavailable",
        }.get(status, "Update Failed")
        self.show_notification(
            title,
            message,
            actions=actions,
            timeout_ms=0 if status == "error" else 8000,
        )

    def _offer_update_restart(self, result: Any, release_url: str) -> None:
        migration = bool(getattr(result, "migration_required", False))
        dialog = QtWidgets.QMessageBox(self)
        dialog.setWindowTitle(
            "Standard Installation Ready" if migration else "Update Ready"
        )
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Information)
        dialog.setText(str(getattr(result, "message", "Update ready.")))
        dialog.setInformativeText(
            "Houdini will show its standard save prompt before closing. "
            "HCQ will reopen the same saved HIP file after the current "
            "Houdini process exits."
        )
        restart_label = "Install and Restart" if migration else "Restart Now"
        restart_button = dialog.addButton(
            restart_label,
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        later_button = dialog.addButton(
            "Later",
            QtWidgets.QMessageBox.ButtonRole.RejectRole,
        )
        release_button = None
        if release_url:
            release_button = dialog.addButton(
                "Open Release",
                QtWidgets.QMessageBox.ButtonRole.ActionRole,
            )
        dialog.setDefaultButton(restart_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is release_button:
            self._open_url(release_url)
            return
        if clicked is not restart_button:
            self.show_notification(
                "Restart Deferred",
                "Restart Houdini later to finish the HCQ update.",
                timeout_ms=8000,
            )
            return
        try:
            restarted = call(
                self.manager,
                "restart_for_update",
                result,
                default=False,
            )
        except SystemExit:
            raise
        except Exception as error:
            self.show_notification(
                "Could Not Restart Houdini",
                str(error),
                timeout_ms=0,
            )
            return
        if not restarted:
            self.show_notification(
                "Restart Canceled",
                "The HCQ update remains ready and will be applied later.",
                timeout_ms=8000,
            )

    def _tab_changed(self, index: int) -> None:
        settings = value(self.manager, "settings")
        if isinstance(settings, dict):
            settings["last_opened_tab"] = index
            storage = value(self.manager, "storage")
            saver = getattr(storage, "save_settings", None)
            if callable(saver):
                saver(settings)
            else:
                call(self.manager, "save_settings")

    def refresh(self, topic: str = "all") -> None:
        settings = value(self.manager, "settings", {}) or {}
        enabled = (
            settings.get("monitor_enabled", True)
            if isinstance(settings, dict)
            else item_value(settings, "monitor_enabled", True)
        )
        self.monitor_status.setText(
            text.MONITOR_ON if enabled else text.MONITOR_OFF
        )
        runner = value(self.manager, "runner")
        state = str(value(runner, "state", "idle"))
        self.queue_status.setText(
            f"Queue: {state.replace('_', ' ').title()}"
        )
        topic = topic if isinstance(topic, str) else "all"
        targets = {
            "monitor": {"all", "monitor", "settings", "hip"},
            "queues": {"all", "queues", "hip"},
            "run": {"all", "run", "run_list", "settings", "hip"},
            "history": {"all", "history", "run", "hip"},
            "settings": {"all", "settings"},
        }
        known_topics = set().union(*targets.values())
        if topic not in known_topics:
            topic = "all"
        for name, tab in (
            ("monitor", self.monitor_tab),
            ("queues", self.queues_tab),
            ("run", self.run_tab),
            ("history", self.history_tab),
            ("settings", self.settings_tab),
        ):
            if topic not in targets[name]:
                continue
            try:
                tab.refresh()
            except RuntimeError:
                # A refresh may arrive while Houdini is destroying a panel.
                pass

    @QtCore.Slot(str, str)
    def show_notification(
        self,
        title: str,
        message: str,
        actions: list[tuple[str, Any]] | None = None,
        timeout_ms: int = 7000,
    ) -> None:
        self.toast_area.show_toast(title, message, actions, timeout_ms)

    def _pending_recovery(self) -> Any:
        recovery = value(self.manager, "recovery")
        for owner in (recovery, self.manager):
            pending = call(
                owner,
                (
                    "pending_session",
                    "get_pending_session",
                    "load_interrupted",
                    "detect_interrupted",
                ),
            )
            if pending:
                return pending
        pending = value(recovery, "pending")
        return pending if pending else None

    def _offer_recovery(self) -> None:
        session = self._pending_recovery()
        if not session:
            return
        dialog = RecoveryDialog(session, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        recovery = value(self.manager, "recovery")
        action = dialog.action
        if action == "inspect_output":
            inspections = call(
                recovery, "inspect_output", session, default=[]
            ) or []
            navigation = value(self.manager, "navigation")
            OutputInspectionDialog(
                list(inspections),
                lambda path: call(navigation, "open_output_folder", path),
                self,
            ).exec()
        elif action == "retry_job":
            call(self.manager, "restore_recovery_retry", session)
            self.tabs.setCurrentIndex(2)
        elif action == "restart_queue":
            call(self.manager, "restore_recovery_restart", session)
            self.tabs.setCurrentIndex(2)
        elif action == "mark_complete":
            call(self.manager, "mark_recovery_job_complete", session)
        elif action == "archive":
            call(self.manager, "archive_recovery", session)
        call(self.manager, "notify_changed", "recovery")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # The manager is deliberately not stopped: monitoring survives closing
        # a Python Panel, as required by HCQ's application lifecycle.
        self._tab_changed(self.tabs.currentIndex())
        self._disconnect_refresh()
        super().closeEvent(event)
