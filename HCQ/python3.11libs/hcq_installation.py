"""Installation identity and cross-process coordination for HCQ.

This module deliberately lives outside the ``hcq`` package so Houdini's
``uiready.py`` bootstrap can use it before importing code that may be updated.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from hcq_update_lock import UpdateFileLock, UpdateLockError


INSTALLATION_SCHEMA = "hcq.installation"
INSTALLATION_FILE = "HCQ_INSTALLATION.json"


def normalized_install_root(value: str | Path) -> Path:
    return Path(value).resolve()


def installation_id(value: str | Path) -> str:
    root = normalized_install_root(value)
    normalized = os.path.normcase(str(root)).replace("\\", "/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def local_app_data_root(
    *,
    environment: dict[str, str] | None = None,
    fallback: str | Path | None = None,
) -> Path:
    values = os.environ if environment is None else environment
    local = str(values.get("LOCALAPPDATA", "")).strip()
    if local:
        return Path(local).resolve()
    if fallback is not None:
        return Path(fallback).resolve()
    return (Path.home() / "AppData" / "Local").resolve()


def shared_updates_root(
    install_root: str | Path,
    *,
    environment: dict[str, str] | None = None,
    fallback: str | Path | None = None,
) -> Path:
    base = local_app_data_root(environment=environment, fallback=fallback)
    return base / "HCQ" / "updates" / installation_id(install_root)


def development_checkout(install_root: str | Path) -> bool:
    root = normalized_install_root(install_root)
    for parent in (root, *root.parents):
        if (parent / ".git").exists():
            return True
        if parent == parent.parent:
            break
    return False


def _load_installation_marker(install_root: Path) -> dict[str, Any]:
    marker = install_root / INSTALLATION_FILE
    if not marker.is_file():
        return {}
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if (
        not isinstance(value, dict)
        or value.get("schema") != INSTALLATION_SCHEMA
        or value.get("schema_version") != 1
    ):
        return {}
    return value


def installation_mode(install_root: str | Path) -> str:
    root = normalized_install_root(install_root)
    if development_checkout(root):
        return "development"
    marker = _load_installation_marker(root)
    mode = str(marker.get("install_mode", "")).strip()
    if mode in {"inno", "package_archive", "legacy"}:
        return mode
    package = root.parent / "packages" / "hcq.json"
    if package.is_file():
        try:
            content = package.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if "$HOUDINI_PACKAGE_PATH/../HCQ" in content:
            return "legacy"
    return "package_archive"


class RuntimeInstanceLock:
    """Hold a process-specific marker for one loaded HCQ installation."""

    def __init__(self, updates_root: str | Path, pid: int | None = None) -> None:
        self.updates_root = Path(updates_root).resolve()
        self.pid = int(os.getpid() if pid is None else pid)
        self.path = self.updates_root / "runtime" / f"{self.pid}.lock"
        self._lock = UpdateFileLock(self.path)

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()

    def __enter__(self) -> "RuntimeInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def active_runtime_instances(
    updates_root: str | Path,
    *,
    exclude_pid: int | None = None,
) -> list[int]:
    runtime = Path(updates_root).resolve() / "runtime"
    if not runtime.is_dir():
        return []
    active: list[int] = []
    for marker in sorted(runtime.glob("*.lock")):
        try:
            pid = int(marker.stem)
        except ValueError:
            continue
        if exclude_pid is not None and pid == int(exclude_pid):
            continue
        probe = UpdateFileLock(marker)
        try:
            probe.acquire()
        except UpdateLockError:
            active.append(pid)
            continue
        finally:
            probe.release()
        try:
            marker.unlink()
        except OSError:
            pass
    return active
