"""Safe Houdini restart support used after staging an HCQ update."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import hcq_restart_helper


ACTIVE_RUN_STATES = {
    "preparing",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
}


def restart_block_reason(manager: Any) -> str:
    runner = getattr(manager, "runner", None)
    state = str(getattr(runner, "state", "idle"))
    active = bool(getattr(runner, "active", False))
    if active or state in ACTIVE_RUN_STATES:
        return "Finish or cancel the active HCQ queue before restarting Houdini."
    updater = getattr(manager, "updater", None)
    other_instances = getattr(updater, "other_runtime_instances", None)
    if callable(other_instances) and other_instances():
        return (
            "Another Houdini session is using this HCQ installation. "
            "Close it before restarting for the update."
        )
    return ""


def _current_hip_path(hou_module: Any) -> str:
    try:
        if bool(hou_module.hipFile.isNewFile()):
            return ""
        path = str(hou_module.hipFile.path())
        return path if path and Path(path).is_file() else ""
    except Exception:
        return ""


def _restart_python(hou_module: Any) -> Path:
    root = Path(str(hou_module.expandString("$HFS")))
    candidate = root / "python311" / "python.exe"
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def restart_houdini(
    manager: Any,
    *,
    installer_path: str = "",
    popen: Callable[..., Any] = subprocess.Popen,
) -> bool:
    """Request a standard save prompt and relaunch only after accepted exit."""
    reason = restart_block_reason(manager)
    if reason:
        raise RuntimeError(reason)
    hou_module = manager.hou
    python = _restart_python(hou_module)
    helper = Path(hcq_restart_helper.__file__).resolve()
    executable = Path(sys.executable).resolve()
    if not python.is_file() or not helper.is_file() or not executable.is_file():
        raise RuntimeError(
            "HCQ could not locate the Houdini restart components."
        )
    installer = str(Path(installer_path).resolve()) if installer_path else ""
    if installer and not Path(installer).is_file():
        raise RuntimeError("The staged HCQ installer is missing.")
    try:
        hou_module.exit(0, suppress_save_prompt=False)
    except SystemExit:
        hip_file = _current_hip_path(hou_module)
        command = [
            str(python),
            str(helper),
            "--wait-pid",
            str(os.getpid()),
            "--executable",
            str(executable),
        ]
        if hip_file:
            command.extend(["--hip-file", hip_file])
        if installer:
            command.extend(["--installer", installer])
        popen(
            command,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raise
    return False
