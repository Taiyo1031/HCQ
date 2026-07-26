"""Safe legacy-layout migration used by the HCQ Windows installer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


RESERVED_USER_DATA = (
    "HCQ/settings.json",
    "HCQ/monitor_registry.json",
    "HCQ/queues",
    "HCQ/runs",
    "HCQ/logs",
    "HCQ/recovery",
    "HCQ/updates",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_plugin_path(value: str) -> Path:
    path = PurePosixPath(value)
    normalized = path.as_posix()
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
        or path.parts[0] != "HCQ"
        or any(
            normalized == reserved or normalized.startswith(f"{reserved}/")
            for reserved in RESERVED_USER_DATA
        )
    ):
        raise ValueError(f"Unsafe legacy manifest path: {value}")
    return Path(*path.parts)


def _development_checkout(path: Path) -> bool:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return True
        if parent == parent.parent:
            break
    return False


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "hcq.release-manifest"
        or value.get("schema_version") != 1
        or not isinstance(value.get("files"), list)
    ):
        raise ValueError("The legacy HCQ manifest is invalid.")
    return value


def migrate_legacy_install(
    preference_root: str | Path,
    backup_root: str | Path,
    journal_path: str | Path | None = None,
) -> dict[str, list[str]]:
    preference = Path(preference_root).resolve()
    legacy = preference / "HCQ"
    manifest_path = legacy / "HCQ_MANIFEST.json"
    if not manifest_path.is_file():
        return {"removed": [], "preserved": []}
    if _development_checkout(legacy):
        raise RuntimeError(
            "HCQ will not migrate files inside a Git development checkout."
        )
    manifest = _load_manifest(manifest_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = (
        Path(backup_root).resolve()
        / hashlib.sha256(
            os.path.normcase(str(preference)).encode("utf-8")
        ).hexdigest()[:16]
        / stamp
    )
    removed: list[str] = []
    preserved: list[str] = []
    records: list[tuple[Path, Path]] = []
    try:
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise ValueError("The legacy manifest contains an invalid entry.")
            raw = str(item.get("path", ""))
            if raw == "packages/hcq.json":
                continue
            try:
                relative = _safe_plugin_path(raw)
            except ValueError:
                preserved.append(raw)
                continue
            target = preference / relative
            if not target.is_file():
                continue
            expected = str(item.get("sha256", "")).lower()
            if len(expected) != 64 or sha256_file(target) != expected:
                preserved.append(relative.as_posix())
                continue
            backup = destination / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            if sha256_file(backup) != expected:
                raise OSError(f"Could not verify migration backup: {relative}")
            target.unlink()
            records.append((target, backup))
            removed.append(relative.as_posix())

        manifest_backup = destination / "HCQ" / "HCQ_MANIFEST.json"
        manifest_backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path, manifest_backup)
        manifest_path.unlink()
        records.append((manifest_path, manifest_backup))
        removed.append("HCQ/HCQ_MANIFEST.json")
        if journal_path is not None:
            journal = Path(journal_path).resolve()
            journal.parent.mkdir(parents=True, exist_ok=True)
            temporary = journal.with_suffix(f"{journal.suffix}.tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "schema": "hcq.legacy-migration",
                        "schema_version": 1,
                        "preference_root": str(preference),
                        "backup_directory": str(destination),
                        "files": [
                            {
                                "path": target.relative_to(preference).as_posix(),
                                "backup": backup.relative_to(destination).as_posix(),
                            }
                            for target, backup in records
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(temporary, journal)
    except Exception:
        for target, backup in reversed(records):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        raise
    return {"removed": removed, "preserved": preserved}


def rollback_legacy_migration(journal_path: str | Path) -> list[str]:
    journal = Path(journal_path).resolve()
    value = json.loads(journal.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema") != "hcq.legacy-migration"
        or value.get("schema_version") != 1
        or not isinstance(value.get("files"), list)
    ):
        raise ValueError("The HCQ migration journal is invalid.")
    preference = Path(str(value.get("preference_root", ""))).resolve()
    backup_directory = Path(str(value.get("backup_directory", ""))).resolve()
    restored: list[str] = []
    for item in reversed(value["files"]):
        if not isinstance(item, dict):
            raise ValueError("The HCQ migration journal contains an invalid entry.")
        relative = _safe_plugin_path(str(item.get("path", "")))
        backup_relative = _safe_plugin_path(str(item.get("backup", "")))
        target = (preference / relative).resolve()
        backup = (backup_directory / backup_relative).resolve()
        if (
            not _inside(target, preference)
            or not _inside(backup, backup_directory)
            or not backup.is_file()
        ):
            raise ValueError(f"Could not validate migration rollback: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
        if sha256_file(target) != sha256_file(backup):
            raise OSError(f"Could not verify migration rollback: {relative}")
        restored.append(relative.as_posix())
    journal.unlink()
    return restored


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("--preference-root", required=True)
    migrate.add_argument("--backup-root", required=True)
    migrate.add_argument("--journal")
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--journal", required=True)
    arguments = parser.parse_args()
    if arguments.command == "migrate":
        result = migrate_legacy_install(
            arguments.preference_root,
            arguments.backup_root,
            arguments.journal,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if arguments.command == "rollback":
        restored = rollback_legacy_migration(arguments.journal)
        print(json.dumps({"restored": restored}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
