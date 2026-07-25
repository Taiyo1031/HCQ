"""HCQ bootstrap and Python Panel entry points."""

from __future__ import annotations

import traceback
from typing import Any

from .environment import inspect_environment

try:
    import hou  # type: ignore
except ImportError:  # pragma: no cover - exercised outside Houdini
    hou = None  # type: ignore

_manager: Any | None = None


def startup() -> Any | None:
    """Start HCQ once after Houdini's interactive UI is ready."""
    global _manager
    if _manager is not None:
        return _manager
    status = inspect_environment(hou)
    if not status.supported:
        print(f"HCQ: {status.message}")
        return None
    try:
        from .manager import HCQManager

        _manager = HCQManager(hou)
        _manager.start()
        return _manager
    except Exception:
        traceback.print_exc()
        return None


def get_manager() -> Any:
    manager = startup()
    if manager is None:
        raise RuntimeError("HCQ is not available in this Houdini session.")
    return manager


def create_panel() -> Any:
    """Create the root widget embedded by the HCQ Python Panel."""
    from .ui.main_panel import HCQPanel

    return HCQPanel(get_manager())


def _is_hcq_panel(pane_tab: Any) -> bool:
    try:
        if pane_tab.type() != hou.paneTabType.PythonPanel:
            return False
        interface = pane_tab.activeInterface()
        name = interface.name() if hasattr(interface, "name") else str(interface)
        return name == "hcq"
    except Exception:
        return False


def open_panel() -> Any:
    """Focus an existing HCQ panel or create a new floating Python Panel."""
    manager = get_manager()
    del manager
    for pane_tab in hou.ui.paneTabs():
        if not _is_hcq_panel(pane_tab):
            continue
        try:
            window = pane_tab.qtParentWindow()
            window.show()
            window.raise_()
            window.activateWindow()
        except Exception:
            pass
        return pane_tab
    pane_tab = hou.ui.curDesktop().createFloatingPaneTab(
        hou.paneTabType.PythonPanel,
        position=(100, 100),
        size=(1120, 760),
        python_panel_interface="hcq",
        immediate=True,
    )
    try:
        pane_tab.setName("HCQ")
    except Exception:
        pass
    return pane_tab


def shutdown() -> None:
    global _manager
    if _manager is not None:
        try:
            _manager.shutdown()
        finally:
            _manager = None
