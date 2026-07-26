"""Reusable HCQ widgets and UI helpers."""

from __future__ import annotations

import os
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from . import text


ROLE_OBJECT = QtCore.Qt.ItemDataRole.UserRole
CPU_VALUE_MODES = frozenset({"threads", "reserve"})


def cpu_setting_label(mode: str, value: int | None = None) -> str:
    """Return a compact, user-facing label for a serialized CPU setting."""
    amount = int(value or 1)
    thread_word = "Thread" if amount == 1 else "Threads"
    labels = {
        "inherit": "Queue Setting",
        "current": "Current Houdini Setting",
        "all": "All Logical Threads",
        "single": "Single Logical Thread",
    }
    if mode == "threads":
        return f"Maximum {amount} {thread_word}"
    if mode == "reserve":
        return f"Leave {amount} {thread_word} Free"
    return labels.get(mode, mode.replace("_", " ").title())


def cpu_setting_summary(
    mode: str,
    value: int | None = None,
    *,
    available_threads: int | None = None,
) -> str:
    """Describe the effective Houdini thread cap without promising CPU usage."""
    available = max(1, int(available_threads or (os.cpu_count() or 1)))
    amount = max(1, int(value or 1))
    if mode == "inherit":
        return "This job uses the Queue CPU setting."
    if mode == "current":
        return "HCQ leaves Houdini's current maximum-thread setting unchanged."
    if mode == "all":
        return f"Houdini limit: all {available} logical threads."
    if mode == "single":
        return f"Houdini limit: 1 of {available} logical threads."
    if mode == "threads":
        applied = min(amount, available)
        suffix = f" (requested {amount})." if amount > available else "."
        return f"Houdini limit: {applied} of {available} logical threads{suffix}"
    if mode == "reserve":
        applied = max(1, available - amount)
        free = available - applied
        if amount >= available:
            return (
                f"Houdini limit: {applied} of {available} logical threads "
                f"({free} can be left free; {amount} requested)."
            )
        thread_word = "thread" if free == 1 else "threads"
        return (
            f"Houdini limit: {applied} of {available} logical threads "
            f"({free} {thread_word} left free)."
        )
    return "Select a supported CPU limit."


def sync_cpu_controls(
    mode_combo: QtWidgets.QComboBox,
    value_spin: QtWidgets.QSpinBox,
    help_label: QtWidgets.QLabel,
) -> None:
    """Update a CPU value editor and its effective-limit explanation."""
    mode = str(mode_combo.currentData() or "current")
    value_spin.setEnabled(mode in CPU_VALUE_MODES)
    help_label.setText(
        f"{cpu_setting_summary(mode, value_spin.value())} {text.CPU_LIMIT_NOTE}"
    )


class ReorderTable(QtWidgets.QTableWidget):
    """A row-oriented table with safe internal drag/drop reordering."""

    orderChanged = QtCore.Signal(list)

    def __init__(self, columns: list[str], parent: QtWidgets.QWidget | None = None):
        super().__init__(0, len(columns), parent)
        self.setHorizontalHeaderLabels(columns)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(False)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.InternalMove
        )
        self.setDefaultDropAction(QtCore.Qt.DropAction.MoveAction)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        super().dropEvent(event)
        self.orderChanged.emit(self.objects())

    def objects(self) -> list[Any]:
        result: list[Any] = []
        for row in range(self.rowCount()):
            item = self.item(row, 0)
            if item is not None:
                result.append(item.data(ROLE_OBJECT))
        return result

    def selected_objects(self) -> list[Any]:
        rows = sorted({index.row() for index in self.selectedIndexes()})
        result: list[Any] = []
        for row in rows:
            item = self.item(row, 0)
            if item is not None:
                result.append(item.data(ROLE_OBJECT))
        return result

    def current_object(self) -> Any:
        item = self.item(self.currentRow(), 0)
        return item.data(ROLE_OBJECT) if item is not None else None


def set_row(
    table: QtWidgets.QTableWidget,
    row: int,
    values: list[Any],
    obj: Any,
    *,
    checked: bool | None = None,
) -> None:
    table.insertRow(row)
    for column, raw_value in enumerate(values):
        item = QtWidgets.QTableWidgetItem(str(raw_value))
        if column == 0:
            item.setData(ROLE_OBJECT, obj)
            if checked is not None:
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    QtCore.Qt.CheckState.Checked
                    if checked
                    else QtCore.Qt.CheckState.Unchecked
                )
        table.setItem(row, column, item)


def make_button(
    label: str,
    slot: Any | None = None,
    *,
    object_name: str = "",
) -> QtWidgets.QPushButton:
    button = QtWidgets.QPushButton(label)
    if object_name:
        button.setObjectName(object_name)
    if slot is not None:
        button.clicked.connect(slot)
    return button


def compact_button_row(*buttons: QtWidgets.QWidget) -> QtWidgets.QHBoxLayout:
    layout = QtWidgets.QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)
    return layout


def show_warning(parent: QtWidgets.QWidget, message: str) -> None:
    QtWidgets.QMessageBox.warning(parent, text.APP_SHORT_TITLE, message)


def show_error(parent: QtWidgets.QWidget, message: str) -> None:
    QtWidgets.QMessageBox.critical(parent, text.APP_SHORT_TITLE, message)
