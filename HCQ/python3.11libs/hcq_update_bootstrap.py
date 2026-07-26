"""Apply a staged HCQ update before importing the HCQ package."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from hcq_installation import active_runtime_instances, shared_updates_root
from hcq_update_lock import UpdateFileLock, UpdateLockError


PENDING_SCHEMA = "hcq.pending-update"
TRANSACTION_SCHEMA = "hcq.update-transaction"
_CHECKSUM = re.compile(r"^[0-9a-fA-F]{64}$")
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_RESERVED_DATA_PATHS = (
    "HCQ/settings.json",
    "HCQ/monitor_registry.json",
    "HCQ/queues",
    "HCQ/runs",
    "HCQ/logs",
    "HCQ/recovery",
    "HCQ/updates",
)


class UpdateRecoveryError(RuntimeError):
    """Raised when HCQ cannot prove that a failed update was rolled back."""


def _safe_relative(value: str) -> Path:
    posix = PurePosixPath(value)
    normalized = posix.as_posix()
    if (
        posix.is_absolute()
        or not posix.parts
        or any(part in {"", ".", ".."} for part in posix.parts)
        or "\\" in value
        or posix.parts[0] not in {"HCQ", "packages"}
        or (
            posix.parts[0] == "packages"
            and posix != PurePosixPath("packages/hcq.json")
        )
        or any(
            normalized == reserved or normalized.startswith(f"{reserved}/")
            for reserved in _RESERVED_DATA_PATHS
        )
    ):
        raise ValueError(f"Unsafe update target: {value}")
    return Path(*posix.parts)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".update", dir=str(target.parent)
    )
    os.close(handle)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _load_pending(path: Path) -> dict[str, Any] | None:
    value = _load_json(path)
    if value is None:
        return None
    if (
        value.get("schema") != PENDING_SCHEMA
        or value.get("schema_version") not in {1, 2}
    ):
        raise ValueError("The pending HCQ update is invalid.")
    return value


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"Invalid HCQ update version: {value}")
    return tuple(int(part) for part in match.groups())


def _installed_version(install_root: Path) -> str:
    manifest = _load_json(install_root / "HCQ_MANIFEST.json")
    if manifest is None:
        return ""
    if (
        manifest.get("schema") != "hcq.release-manifest"
        or manifest.get("schema_version") != 1
    ):
        raise ValueError("The installed HCQ release manifest is invalid.")
    version = str(manifest.get("hcq_version", ""))
    _version_tuple(version)
    return version


def _development_checkout(install_root: Path) -> bool:
    for parent in (install_root, *install_root.parents):
        if (parent / ".git").exists():
            return True
        if parent == parent.parent:
            break
    return False


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unique_state_path(path: Path, prefix: str, version: str) -> Path:
    candidate = path.with_name(f"{prefix}-{version}.json")
    if not candidate.exists():
        return candidate
    return path.with_name(f"{prefix}-{version}-{_timestamp()}.json")


def _restore_records(
    records: list[dict[str, Any]],
    install_parent: Path,
    updates_root: Path,
) -> bool:
    restored = True
    backup_root = updates_root / "backups"
    for record in reversed(records):
        try:
            relative = _safe_relative(str(record["path"]))
            target = install_parent / relative
            if not _inside(target, install_parent):
                raise ValueError(f"Unsafe rollback target: {relative}")
            backup_value = str(record.get("backup", ""))
            if backup_value:
                backup = updates_root / Path(*PurePosixPath(backup_value).parts)
                if not _inside(backup, backup_root) or not backup.is_file():
                    raise ValueError(f"Rollback backup is missing: {relative}")
                _atomic_copy(backup, target)
                if _sha256(target) != str(record["original_sha256"]):
                    raise ValueError(f"Rollback verification failed: {relative}")
            elif target.exists():
                if not target.is_file():
                    raise ValueError(f"Rollback target is not a file: {relative}")
                target.unlink()
        except Exception:
            restored = False
    return restored


def _recover_incomplete_transaction(
    journal_path: Path,
    install_parent: Path,
    updates_root: Path,
) -> None:
    journal = _load_json(journal_path)
    if journal is None:
        return
    if (
        journal.get("schema") != TRANSACTION_SCHEMA
        or journal.get("schema_version") != 1
        or Path(str(journal.get("install_parent", ""))).resolve()
        != install_parent
        or not isinstance(journal.get("records"), list)
    ):
        raise UpdateRecoveryError(
            "HCQ found an invalid update recovery journal."
        )
    if not _restore_records(journal["records"], install_parent, updates_root):
        raise UpdateRecoveryError(
            "HCQ could not recover an interrupted update. "
            "Restore the latest installation-scoped update backup manually."
        )
    journal_path.unlink()


def _apply_locked(
    pending_path: Path,
    install_root: Path,
    updates_root: Path,
) -> str | None:
    install_parent = install_root.parent
    journal_path = updates_root / "applying.json"
    _recover_incomplete_transaction(
        journal_path, install_parent, updates_root
    )

    pending = _load_pending(pending_path)
    if pending is None:
        return None
    expected_install = Path(str(pending["install_root"])).resolve()
    expected_parent = Path(str(pending["install_parent"])).resolve()
    stage_root = Path(str(pending["stage_root"])).resolve()
    if (
        expected_install != install_root
        or expected_parent != install_parent
        or _development_checkout(install_root)
        or not _inside(stage_root, updates_root / "staged")
    ):
        raise ValueError("The pending update does not match this installation.")

    from_version = str(pending.get("from_version", ""))
    to_version = str(pending.get("to_version", ""))
    if _version_tuple(to_version) <= _version_tuple(from_version):
        raise ValueError("The pending update is not newer than HCQ.")
    installed_version = _installed_version(install_root)
    if installed_version == to_version:
        os.replace(
            pending_path,
            _unique_state_path(pending_path, "already-applied", to_version),
        )
        return to_version
    if installed_version != from_version:
        os.replace(
            pending_path,
            _unique_state_path(pending_path, "stale", to_version),
        )
        print(
            "HCQ update was skipped because the installed version changed "
            f"from {from_version or 'unknown'} to "
            f"{installed_version or 'unknown'}."
        )
        return None

    operations: list[tuple[Path, Path, Path, str]] = []
    targets: set[str] = set()
    for item in pending.get("files", []):
        relative = _safe_relative(str(item["path"]))
        source = stage_root / relative
        target = install_parent / relative
        checksum = str(item.get("sha256", "")).lower()
        if (
            not _inside(source, stage_root)
            or not _inside(target, install_parent)
            or not _CHECKSUM.fullmatch(checksum)
            or not source.is_file()
            or _sha256(source) != checksum
        ):
            raise ValueError(f"Staged update file is corrupt: {relative}")
        key = os.path.normcase(str(target.resolve()))
        if key in targets:
            raise ValueError(f"Duplicate update target: {relative}")
        targets.add(key)
        operations.append((relative, source, target, checksum))

    removals: list[tuple[Path, Path]] = []
    for value in pending.get("remove", []):
        relative = _safe_relative(str(value))
        target = install_parent / relative
        if not _inside(target, install_parent):
            raise ValueError(f"Unsafe update removal: {relative}")
        key = os.path.normcase(str(target.resolve()))
        if key in targets:
            raise ValueError(f"Conflicting update target: {relative}")
        targets.add(key)
        removals.append((relative, target))

    stamp = _timestamp()
    backup_root = (
        updates_root / "backups" / f"{stamp}-{to_version}"
    )
    records: list[dict[str, Any]] = []
    for relative, target in [
        *((relative, target) for relative, _source, target, _hash in operations),
        *removals,
    ]:
        if target.exists() and not target.is_file():
            raise ValueError(f"Update target is not a file: {relative}")
        record = {
            "path": PurePosixPath(*relative.parts).as_posix(),
            "backup": "",
            "original_sha256": "",
        }
        if target.is_file():
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            original_hash = _sha256(target)
            if _sha256(backup) != original_hash:
                raise ValueError(f"Could not verify update backup: {relative}")
            record["backup"] = (
                PurePosixPath(*backup.relative_to(updates_root).parts).as_posix()
            )
            record["original_sha256"] = original_hash
        records.append(record)

    _atomic_json(
        journal_path,
        {
            "schema": TRANSACTION_SCHEMA,
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "install_parent": str(install_parent),
            "from_version": from_version,
            "to_version": to_version,
            "records": records,
        },
    )

    try:
        for _relative, source, target, _checksum in operations:
            _atomic_copy(source, target)
        for _relative, target in removals:
            if target.is_file():
                target.unlink()
        for relative, _source, target, checksum in operations:
            if not target.is_file() or _sha256(target) != checksum:
                raise ValueError(
                    f"Installed update verification failed: {relative}"
                )
    except Exception as error:
        restored = _restore_records(records, install_parent, updates_root)
        if restored:
            try:
                journal_path.unlink()
            except OSError:
                pass
            if pending_path.exists():
                os.replace(
                    pending_path,
                    _unique_state_path(pending_path, "failed", to_version),
                )
            print(f"HCQ update was rolled back: {error}")
            return None
        _atomic_json(
            updates_root / "UPDATE_RECOVERY_REQUIRED.json",
            {
                "error": str(error),
                "journal": str(journal_path),
                "backup_root": str(backup_root),
            },
        )
        raise UpdateRecoveryError(
            "HCQ update and rollback verification failed. "
            "Restore the latest installation-scoped update backup manually."
        ) from error

    journal_path.unlink()
    os.replace(
        pending_path,
        _unique_state_path(pending_path, "applied", to_version),
    )
    return to_version


def apply_pending(
    hou_module: Any | None = None,
    plugin_root: str | Path | None = None,
    storage_root: str | Path | None = None,
    updates_root: str | Path | None = None,
) -> str | None:
    """Apply a staged update and return the installed version, if any."""
    install_root = (
        Path(plugin_root).resolve()
        if plugin_root is not None
        else Path(__file__).resolve().parents[1]
    )
    if storage_root is None:
        if hou_module is not None:
            pref = Path(hou_module.expandString("$HOUDINI_USER_PREF_DIR"))
        else:
            pref = Path(
                os.environ.get("HOUDINI_USER_PREF_DIR", install_root.parent)
            )
        legacy_data_root = (pref / "HCQ").resolve()
    else:
        legacy_data_root = Path(storage_root).resolve()
    if updates_root is not None:
        update_state_root = Path(updates_root).resolve()
    elif storage_root is not None:
        # Explicit storage roots are retained for tests and embedders using
        # the original updater contract.
        update_state_root = legacy_data_root / "updates"
    else:
        update_state_root = shared_updates_root(
            install_root,
            fallback=legacy_data_root.parent,
        )
        legacy_updates = legacy_data_root / "updates"
        if (
            not (update_state_root / "pending.json").is_file()
            and (legacy_updates / "pending.json").is_file()
        ):
            update_state_root = legacy_updates
    pending_path = update_state_root / "pending.json"
    try:
        if active_runtime_instances(update_state_root):
            print(
                "HCQ update was deferred because another Houdini session "
                "is using this installation."
            )
            return None
        with UpdateFileLock(update_state_root / "update.lock"):
            return _apply_locked(
                pending_path,
                install_root,
                update_state_root,
            )
    except UpdateLockError:
        print("HCQ update was deferred because another update is active.")
        return None
    except UpdateRecoveryError:
        raise
    except Exception as error:
        print(f"HCQ update was not applied: {error}")
        return None
