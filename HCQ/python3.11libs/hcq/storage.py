"""Atomic JSON persistence under the Houdini user preference directory."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .constants import DEFAULT_SETTINGS
from .models import QueueTemplate, RunSession, queue_library_document
from .utils import now_iso


@dataclass(frozen=True)
class StoragePaths:
    root: Path
    settings: Path
    monitor_registry: Path
    queue_library: Path
    exported_queues: Path
    active_runs: Path
    history: Path
    logs: Path
    recovery: Path
    lock_file: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "StoragePaths":
        root = Path(root)
        return cls(
            root=root,
            settings=root / "settings.json",
            monitor_registry=root / "monitor_registry.json",
            queue_library=root / "queues" / "queue_library.json",
            exported_queues=root / "queues" / "exported",
            active_runs=root / "runs" / "active",
            history=root / "runs" / "history",
            logs=root / "logs",
            recovery=root / "recovery",
            lock_file=root / "runs" / "active" / "run.lock",
        )


def default_storage_root(hou_module: Any | None = None) -> Path:
    if hou_module is not None:
        return Path(hou_module.expandString("$HOUDINI_USER_PREF_DIR")) / "HCQ"
    pref = os.environ.get("HOUDINI_USER_PREF_DIR")
    if not pref:
        pref = str(Path.home() / "houdini21.0")
    return Path(pref) / "HCQ"


def atomic_write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def read_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    with target.open("r", encoding="utf-8") as stream:
        return json.load(stream)


class Storage:
    def __init__(self, root: str | Path, houdini_version: str = "21.0") -> None:
        self.paths = StoragePaths.from_root(root)
        self.houdini_version = houdini_version
        self.ensure_layout()

    def ensure_layout(self) -> None:
        for path in (
            self.paths.root,
            self.paths.queue_library.parent,
            self.paths.exported_queues,
            self.paths.active_runs,
            self.paths.history,
            self.paths.logs,
            self.paths.recovery,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def load_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        try:
            loaded = read_json(self.paths.settings, {})
            if isinstance(loaded, dict):
                settings.update(loaded)
        except (OSError, ValueError):
            self._quarantine(self.paths.settings)
        return settings

    def save_settings(self, settings: dict[str, Any]) -> None:
        atomic_write_json(self.paths.settings, settings)

    def load_monitor_registry(self) -> dict[str, list[dict[str, Any]]]:
        try:
            value = read_json(self.paths.monitor_registry, {"hip_files": {}})
            hip_files = value.get("hip_files", {}) if isinstance(value, dict) else {}
            return hip_files if isinstance(hip_files, dict) else {}
        except (OSError, ValueError):
            self._quarantine(self.paths.monitor_registry)
            return {}

    def save_monitor_registry(self, registry: dict[str, list[dict[str, Any]]]) -> None:
        atomic_write_json(
            self.paths.monitor_registry,
            {
                "schema": "hcq.monitor-registry",
                "schema_version": 1,
                "updated_at": now_iso(),
                "hip_files": registry,
            },
        )

    def load_queues(self) -> list[QueueTemplate]:
        try:
            value = read_json(self.paths.queue_library, {"queues": []})
            return [QueueTemplate.from_dict(item) for item in value.get("queues", [])]
        except (OSError, ValueError, TypeError):
            self._quarantine(self.paths.queue_library)
            return []

    def save_queues(self, queues: list[QueueTemplate]) -> None:
        atomic_write_json(
            self.paths.queue_library,
            queue_library_document(queues, self.houdini_version),
        )

    def save_active_session(self, session: RunSession) -> Path:
        path = self.paths.active_runs / f"{session.id}.json"
        atomic_write_json(path, session.to_document(completed=False))
        return path

    def complete_session(self, session: RunSession) -> Path:
        destination = self.paths.history / f"{session.id}.json"
        atomic_write_json(destination, session.to_document(completed=True))
        active = self.paths.active_runs / f"{session.id}.json"
        if active.exists():
            active.unlink()
        return destination

    def active_sessions(self) -> list[RunSession]:
        result: list[RunSession] = []
        for path in sorted(self.paths.active_runs.glob("session-*.json")):
            try:
                result.append(RunSession.from_dict(read_json(path, {})))
            except (OSError, ValueError, TypeError):
                self._quarantine(path)
        return result

    def history_documents(self) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        for path in sorted(self.paths.history.glob("session-*.json"), reverse=True):
            try:
                document = read_json(path, {})
                document["_path"] = str(path)
                documents.append(document)
            except (OSError, ValueError):
                self._quarantine(path)
        return documents

    def prune_history(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
        removed = 0
        for path in self.paths.history.glob("session-*.json"):
            modified = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            if modified < cutoff:
                path.unlink()
                removed += 1
        return removed

    def _quarantine(self, path: Path) -> None:
        if not path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.paths.recovery / f"{path.name}.invalid-{stamp}"
        try:
            os.replace(path, destination)
        except OSError:
            pass
