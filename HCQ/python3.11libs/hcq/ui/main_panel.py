"""Main dockable HCQ Python Panel widget."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from . import text
from .bridge import call, connect_refresh, item_value, value
from .dialogs import OutputInspectionDialog, RecoveryDialog
from .tabs import HistoryTab, MonitorTab, QueuesTab, RunTab, SettingsTab
from .toast import ToastArea


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
        self._build()
        self._disconnect_refresh = connect_refresh(manager, self.refresh)
        call(manager, "refresh_all")
        self.refresh()
        QtCore.QTimer.singleShot(0, self._offer_recovery)

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(text.APP_TITLE)
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title)
        header.addStretch(1)
        self.monitor_status = QtWidgets.QLabel(text.MONITOR_ON)
        self.queue_status = QtWidgets.QLabel(text.QUEUE_IDLE)
        self.environment_status = QtWidgets.QLabel(text.HOUDINI_REQUIREMENT)
        header.addWidget(self.monitor_status)
        header.addWidget(self.queue_status)
        header.addWidget(self.environment_status)
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

    def _tab_changed(self, index: int) -> None:
        settings = value(self.manager, "settings")
        if isinstance(settings, dict):
            settings["last_opened_tab"] = index
            call(self.manager, "save_settings")

    def refresh(self) -> None:
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
        for tab in (
            self.monitor_tab,
            self.queues_tab,
            self.run_tab,
            self.history_tab,
            self.settings_tab,
        ):
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
