"""Stable GitHub Release updater for copy-installed HCQ packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from hcq_update_lock import UpdateFileLock, UpdateLockError

from .constants import (
    LATEST_RELEASE_API_URL,
    LATEST_RELEASE_URL,
    VERSION,
)
from .storage import atomic_write_json
from .utils import now_iso


RELEASE_MANIFEST = "HCQ/HCQ_MANIFEST.json"
PENDING_SCHEMA = "hcq.pending-update"
MANIFEST_SCHEMA = "hcq.release-manifest"
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_CHECKSUM_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_RESERVED_DATA_PATHS = (
    "HCQ/settings.json",
    "HCQ/monitor_registry.json",
    "HCQ/queues",
    "HCQ/runs",
    "HCQ/logs",
    "HCQ/recovery",
    "HCQ/updates",
)


@dataclass(frozen=True)
class UpdateResult:
    """Outcome returned to the UI for one manual update request."""

    status: str
    message: str
    current_version: str = VERSION
    latest_version: str = ""
    release_url: str = LATEST_RELEASE_URL
    restart_required: bool = False


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"Unsupported HCQ version: {value}")
    return tuple(int(part) for part in match.groups())


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise ValueError(f"Unsafe archive path: {value}")
    if path.parts[0] not in {"HCQ", "packages"}:
        raise ValueError(f"Unexpected archive root: {value}")
    if path.parts[0] == "packages" and path != PurePosixPath(
        "packages/hcq.json"
    ):
        raise ValueError(f"Unexpected package file: {value}")
    normalized = path.as_posix()
    if any(
        normalized == reserved or normalized.startswith(f"{reserved}/")
        for reserved in _RESERVED_DATA_PATHS
    ):
        raise ValueError(f"Release manifest targets HCQ user data: {value}")
    return path


def _safe_archive_member(value: str) -> PurePosixPath:
    if value == "INSTALL.txt":
        return PurePosixPath(value)
    return _safe_archive_path(value)


def _read_checksum(value: bytes, archive_name: str) -> str:
    text = value.decode("utf-8-sig").strip()
    fields = text.split()
    if not fields or not _CHECKSUM_PATTERN.fullmatch(fields[0]):
        raise ValueError("The release checksum file is invalid.")
    if len(fields) > 1 and fields[-1].lstrip("*") != archive_name:
        raise ValueError("The checksum does not identify the release archive.")
    return fields[0].lower()


class UpdateService:
    """Check, validate, and stage the latest stable HCQ GitHub Release."""

    def __init__(
        self,
        storage_root: str | Path,
        install_root: str | Path | None = None,
        current_version: str = VERSION,
        api_url: str = LATEST_RELEASE_API_URL,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.storage_root = Path(storage_root).resolve()
        self.install_root = (
            Path(install_root).resolve()
            if install_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.current_version = current_version
        self.api_url = api_url
        self._opener = opener or urllib.request.urlopen

    @property
    def updates_root(self) -> Path:
        return self.storage_root / "updates"

    @property
    def pending_path(self) -> Path:
        return self.updates_root / "pending.json"

    def check_and_stage(self) -> UpdateResult:
        try:
            with UpdateFileLock(self.updates_root / "update.lock"):
                return self._check_and_stage_locked()
        except UpdateLockError:
            return UpdateResult(
                "busy",
                "Another HCQ update operation is already active.",
            )

    def _check_and_stage_locked(self) -> UpdateResult:
        try:
            release = self._latest_release()
            latest = self._release_version(release)
            release_url = str(release.get("html_url") or LATEST_RELEASE_URL)
            if parse_version(latest) <= parse_version(self.current_version):
                return UpdateResult(
                    "up_to_date",
                    f"HCQ {self.current_version} is up to date.",
                    self.current_version,
                    latest,
                    release_url,
                )
            if self._is_development_checkout():
                return UpdateResult(
                    "manual_required",
                    (
                        f"HCQ {latest} is available. Automatic installation "
                        "is disabled for Git checkouts; open the release page "
                        "and update the checkout manually."
                    ),
                    self.current_version,
                    latest,
                    release_url,
                )
            archive_name = f"HCQ-{latest}-windows.zip"
            checksum_name = f"{archive_name}.sha256"
            assets = {
                str(item.get("name")): str(item.get("browser_download_url"))
                for item in release.get("assets", [])
                if isinstance(item, dict)
            }
            if archive_name not in assets or checksum_name not in assets:
                return UpdateResult(
                    "unavailable",
                    (
                        f"HCQ {latest} is published, but its Windows archive "
                        "or SHA-256 checksum is missing."
                    ),
                    self.current_version,
                    latest,
                    release_url,
                )
            self._stage_release(
                latest,
                archive_name,
                assets[archive_name],
                assets[checksum_name],
                release_url,
            )
            return UpdateResult(
                "ready",
                "Update ready. Restart Houdini to install.",
                self.current_version,
                latest,
                release_url,
                True,
            )
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return UpdateResult(
                    "no_release",
                    "No published HCQ release is available yet.",
                )
            return UpdateResult(
                "error",
                f"Could not check for updates: HTTP {error.code}.",
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            return UpdateResult("error", f"Could not prepare the update: {error}")

    def _latest_release(self) -> dict[str, Any]:
        request = urllib.request.Request(
            self.api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"HCQ/{self.current_version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with self._open(request, timeout=15) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("GitHub returned an invalid release document.")
        if value.get("draft") or value.get("prerelease"):
            raise ValueError("GitHub returned a non-stable release.")
        return value

    @staticmethod
    def _release_version(release: dict[str, Any]) -> str:
        value = str(release.get("tag_name") or "").strip()
        parsed = parse_version(value)
        return ".".join(str(part) for part in parsed)

    def _open(self, request: Any, timeout: int) -> Any:
        try:
            return self._opener(request, timeout=timeout)
        except TypeError:
            return self._opener(request)

    def _download(self, url: str, destination: Path) -> None:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"HCQ/{self.current_version}"},
        )
        with self._open(request, timeout=60) as response:
            with destination.open("wb") as stream:
                shutil.copyfileobj(response, stream)

    def _download_bytes(self, url: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"HCQ/{self.current_version}"},
        )
        with self._open(request, timeout=30) as response:
            return response.read()

    def _stage_release(
        self,
        version: str,
        archive_name: str,
        archive_url: str,
        checksum_url: str,
        release_url: str,
    ) -> None:
        self.updates_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".download-", dir=str(self.updates_root)
        ) as temporary:
            archive_path = Path(temporary) / archive_name
            self._download(archive_url, archive_path)
            expected = _read_checksum(
                self._download_bytes(checksum_url), archive_name
            )
            actual = sha256_file(archive_path)
            if actual != expected:
                raise ValueError("The release archive checksum does not match.")

            staged_root = self.updates_root / "staged"
            staged_root.mkdir(parents=True, exist_ok=True)
            candidate = Path(
                tempfile.mkdtemp(prefix=f".{version}-", dir=str(staged_root))
            )
            try:
                manifest = self._extract_and_validate(
                    archive_path, candidate, version
                )
                stage = staged_root / version
                if stage.exists():
                    shutil.rmtree(stage)
                os.replace(candidate, stage)
            finally:
                if candidate.exists():
                    shutil.rmtree(candidate)

        files = list(manifest["files"])
        files.append(
            {
                "path": RELEASE_MANIFEST,
                "sha256": sha256_file(stage / Path(RELEASE_MANIFEST)),
            }
        )
        current_manifest = self.install_root / "HCQ_MANIFEST.json"
        remove = self._obsolete_files(current_manifest, files)
        pending = {
            "schema": PENDING_SCHEMA,
            "schema_version": 1,
            "from_version": self.current_version,
            "to_version": version,
            "created_at": now_iso(),
            "release_url": release_url,
            "install_root": str(self.install_root),
            "install_parent": str(self.install_root.parent),
            "stage_root": str(stage),
            "files": files,
            "remove": remove,
        }
        atomic_write_json(self.pending_path, pending)

    def _extract_and_validate(
        self, archive_path: Path, stage: Path, version: str
    ) -> dict[str, Any]:
        with zipfile.ZipFile(archive_path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            safe_members = {
                str(_safe_archive_member(item.filename)): item for item in members
            }
            if len(safe_members) != len(members):
                raise ValueError("The release archive contains duplicate paths.")
            if RELEASE_MANIFEST not in safe_members:
                raise ValueError("The release manifest is missing.")
            for name, member in safe_members.items():
                destination = stage / Path(name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)

        manifest_path = stage / Path(RELEASE_MANIFEST)
        with manifest_path.open("r", encoding="utf-8") as stream:
            manifest = json.load(stream)
        if (
            manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("schema_version") != 1
            or manifest.get("hcq_version") != version
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("The release manifest is invalid.")

        declared: set[str] = set()
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise ValueError("The release manifest has an invalid file.")
            name = str(_safe_archive_path(str(item.get("path", ""))))
            checksum = str(item.get("sha256", "")).lower()
            if not _CHECKSUM_PATTERN.fullmatch(checksum):
                raise ValueError(f"The manifest checksum is invalid: {name}")
            if name in declared or name == RELEASE_MANIFEST:
                raise ValueError(f"The manifest file list is invalid: {name}")
            path = stage / Path(name)
            if not path.is_file() or sha256_file(path) != checksum:
                raise ValueError(f"Release file verification failed: {name}")
            declared.add(name)
        actual = set(safe_members) - {RELEASE_MANIFEST, "INSTALL.txt"}
        if actual != declared:
            raise ValueError("The archive and release manifest do not match.")
        return manifest

    @staticmethod
    def _obsolete_files(
        current_manifest_path: Path,
        new_files: list[dict[str, Any]],
    ) -> list[str]:
        if not current_manifest_path.is_file():
            return []
        try:
            with current_manifest_path.open("r", encoding="utf-8") as stream:
                current = json.load(stream)
            old = {
                str(_safe_archive_path(str(item.get("path", ""))))
                for item in current.get("files", [])
                if isinstance(item, dict)
            }
            new = {str(item["path"]) for item in new_files}
            return sorted(old - new)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return []

    def _is_development_checkout(self) -> bool:
        for parent in (self.install_root, *self.install_root.parents):
            if (parent / ".git").exists():
                return True
            if parent == parent.parent:
                break
        return False
