"""Houdini node and output navigation helpers."""

from __future__ import annotations

import importlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _optional_hou() -> Any | None:
    try:
        return importlib.import_module("hou")
    except (ImportError, RuntimeError):
        return None


@dataclass(frozen=True)
class NavigationResult:
    success: bool
    message: str
    node_path: str = ""


class HoudiniNavigation:
    def __init__(self, hou_module: Any | None = None) -> None:
        self.hou = hou_module

    def find_node(self, node_path: str) -> Any | None:
        hou_module = self.hou or _optional_hou()
        if hou_module is None:
            return None
        try:
            return hou_module.node(node_path)
        except Exception:
            return None

    def go_to_node(self, node_path: str) -> NavigationResult:
        """Select, frame, and expose a node in relevant Houdini panes."""
        hou_module = self.hou or _optional_hou()
        if hou_module is None:
            return NavigationResult(False, "Houdini is not available.", node_path)
        node = self.find_node(node_path)
        if node is None:
            return NavigationResult(False, f"Node not found: {node_path}", node_path)

        try:
            node.setSelected(True, clear_all_selected=True)
            setter = getattr(node, "setCurrent", None)
            if callable(setter):
                setter(True, clear_all_selected=True)
        except Exception:
            pass

        network_updated = False
        parameters_updated = False
        ui = getattr(hou_module, "ui", None)
        pane_tabs = getattr(ui, "paneTabs", None)
        try:
            panes = tuple(pane_tabs()) if callable(pane_tabs) else ()
        except Exception:
            panes = ()

        pane_tab_type = getattr(hou_module, "paneTabType", None)
        network_type = getattr(pane_tab_type, "NetworkEditor", None)
        parameter_type = getattr(pane_tab_type, "Parm", None)
        for pane in panes:
            try:
                current_type = pane.type()
            except Exception:
                continue
            if current_type == network_type and not network_updated:
                try:
                    pane.setPwd(node.parent())
                    current_setter = getattr(pane, "setCurrentNode", None)
                    if callable(current_setter):
                        current_setter(node)
                    frame_selection = getattr(pane, "frameSelection", None)
                    if callable(frame_selection):
                        frame_selection()
                    else:
                        home = getattr(pane, "homeToSelection", None)
                        if callable(home):
                            home()
                    network_updated = True
                except Exception:
                    pass
            elif current_type == parameter_type and not parameters_updated:
                try:
                    pane.setCurrentNode(node)
                    parameters_updated = True
                except Exception:
                    pass

        if not parameters_updated:
            try:
                ui.showNodeEditor(node)
                parameters_updated = True
            except Exception:
                pass

        return NavigationResult(
            True,
            "Node selected.",
            str(getattr(node, "path", lambda: node_path)()),
        )

    def open_output_folder(self, output_path: str) -> NavigationResult:
        """Open the containing folder using the platform file manager."""
        expanded = os.path.expandvars(os.path.expanduser(output_path))
        target = Path(expanded)
        folder = target if target.is_dir() else target.parent
        if not folder.exists():
            return NavigationResult(False, f"Output folder not found: {folder}")
        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            else:
                command = "open" if os.uname().sysname == "Darwin" else "xdg-open"
                subprocess.Popen([command, str(folder)])
        except (OSError, AttributeError) as exc:
            return NavigationResult(False, f"Could not open output folder: {exc}")
        return NavigationResult(True, "Output folder opened.")


def go_to_node(node_path: str, hou_module: Any | None = None) -> NavigationResult:
    return HoudiniNavigation(hou_module).go_to_node(node_path)


def open_output_folder(output_path: str) -> NavigationResult:
    return HoudiniNavigation().open_output_folder(output_path)
