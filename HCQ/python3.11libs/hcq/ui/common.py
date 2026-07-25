"""Reusable HCQ widgets and UI helpers."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from . import text


ROLE_OBJECT = QtCore.Qt.ItemDataRole.UserRole


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
