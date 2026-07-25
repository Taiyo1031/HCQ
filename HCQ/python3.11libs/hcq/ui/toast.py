"""Non-modal notifications displayed inside the HCQ panel."""

from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets


class Toast(QtWidgets.QFrame):
    dismissed = QtCore.Signal()

    def __init__(
        self,
        title: str,
        message: str,
        actions: list[tuple[str, Callable[[], None]]] | None = None,
        timeout_ms: int = 7000,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(title)
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        body = QtWidgets.QLabel(message)
        body.setWordWrap(True)
        layout.addWidget(body)
        row = QtWidgets.QHBoxLayout()
        for label, callback in actions or []:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            button.clicked.connect(self.close)
            row.addWidget(button)
        row.addStretch(1)
        dismiss = QtWidgets.QToolButton()
        dismiss.setText("×")
        dismiss.setToolTip("Dismiss")
        dismiss.clicked.connect(self.close)
        row.addWidget(dismiss)
        layout.addLayout(row)
        if timeout_ms > 0:
            QtCore.QTimer.singleShot(timeout_ms, self.close)

    def closeEvent(self, event) -> None:
        self.dismissed.emit()
        super().closeEvent(event)


class ToastArea(QtWidgets.QWidget):
    """Stacked notification host that does not block Houdini interaction."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)
        self.setVisible(False)

    def show_toast(
        self,
        title: str,
        message: str,
        actions: list[tuple[str, Callable[[], None]]] | None = None,
        timeout_ms: int = 7000,
    ) -> Toast:
        toast = Toast(title, message, actions, timeout_ms, self)
        toast.dismissed.connect(lambda: self._remove(toast))
        self.layout.insertWidget(0, toast)
        self.setVisible(True)
        return toast

    def _remove(self, toast: Toast) -> None:
        self.layout.removeWidget(toast)
        toast.deleteLater()
        self.setVisible(self.layout.count() > 0)
