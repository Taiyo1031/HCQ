from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

import hcq_update_bootstrap
from hcq_update_lock import UpdateFileLock
from hcq.updater import UpdateService, parse_version


def _write_installed_manifest(install: Path, version: str = "1.1.0") -> None:
    install.mkdir(parents=True, exist_ok=True)
    (install / "HCQ_MANIFEST.json").write_text(
        json.dumps(
            {
                "schema": "hcq.release-manifest",
                "schema_version": 1,
                "hcq_version": version,
                "files": [],
            }
        ),
        encoding="utf-8",
    )


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _release_archive(
    version: str,
    payload: bytes = b"new",
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    files = {
        "HCQ/python3.11libs/hcq/new_version.py": payload,
        "packages/hcq.json": b'{"hpath":"$HCQ_ROOT"}\n',
    }
    files.update(extra_files or {})
    manifest = {
        "schema": "hcq.release-manifest",
        "schema_version": 1,
        "hcq_version": version,
        "files": [
            {
                "path": name,
                "sha256": hashlib.sha256(value).hexdigest(),
            }
            for name, value in sorted(files.items())
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        archive.writestr(
            "HCQ/HCQ_MANIFEST.json",
            json.dumps(manifest, indent=2) + "\n",
        )
        archive.writestr("INSTALL.txt", "Install into Houdini preferences.\n")
    return output.getvalue()


class UpdaterTests(unittest.TestCase):
    def test_parse_semantic_version(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        with self.assertRaises(ValueError):
            parse_version("1.2")

    def test_stage_and_apply_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            storage = install
            (install / "python3.11libs" / "hcq").mkdir(parents=True)
            _write_installed_manifest(install)
            (root / "packages").mkdir()
            settings = storage / "settings.json"
            settings.write_text('{"monitor_enabled": true}\n', encoding="utf-8")
            archive = _release_archive("1.2.0")
            checksum = hashlib.sha256(archive).hexdigest()
            release = {
                "tag_name": "v1.2.0",
                "draft": False,
                "prerelease": False,
                "html_url": "https://example.test/release",
                "assets": [
                    {
                        "name": "HCQ-1.2.0-windows.zip",
                        "browser_download_url": "https://example.test/archive",
                    },
                    {
                        "name": "HCQ-1.2.0-windows.zip.sha256",
                        "browser_download_url": "https://example.test/checksum",
                    },
                ],
            }
            values = {
                "https://example.test/api": json.dumps(release).encode(),
                "https://example.test/archive": archive,
                "https://example.test/checksum": (
                    f"{checksum}  HCQ-1.2.0-windows.zip\n".encode()
                ),
            }

            def opener(request, **_kwargs):
                return _Response(values[request.full_url])

            service = UpdateService(
                storage,
                install_root=install,
                current_version="1.1.0",
                api_url="https://example.test/api",
                opener=opener,
            )
            result = service.check_and_stage()
            self.assertEqual(result.status, "ready")
            self.assertTrue(service.pending_path.is_file())

            applied = hcq_update_bootstrap.apply_pending(
                plugin_root=install,
                storage_root=storage,
            )
            self.assertEqual(applied, "1.2.0")
            self.assertEqual(
                (install / "python3.11libs" / "hcq" / "new_version.py").read_bytes(),
                b"new",
            )
            self.assertEqual(
                json.loads(settings.read_text(encoding="utf-8")),
                {"monitor_enabled": True},
            )
            self.assertFalse(service.pending_path.exists())

    def test_checksum_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            _write_installed_manifest(install)
            archive = _release_archive("1.2.0")
            release = {
                "tag_name": "1.2.0",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "HCQ-1.2.0-windows.zip",
                        "browser_download_url": "https://example.test/archive",
                    },
                    {
                        "name": "HCQ-1.2.0-windows.zip.sha256",
                        "browser_download_url": "https://example.test/checksum",
                    },
                ],
            }
            values = {
                "https://example.test/api": json.dumps(release).encode(),
                "https://example.test/archive": archive,
                "https://example.test/checksum": (
                    f"{'0' * 64}  HCQ-1.2.0-windows.zip\n".encode()
                ),
            }

            def opener(request, **_kwargs):
                return _Response(values[request.full_url])

            service = UpdateService(
                install,
                install_root=install,
                current_version="1.1.0",
                api_url="https://example.test/api",
                opener=opener,
            )
            result = service.check_and_stage()
            self.assertEqual(result.status, "error")
            self.assertIn("checksum", result.message.lower())
            self.assertFalse(service.pending_path.exists())

    def test_development_checkout_requires_manual_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            _write_installed_manifest(install)
            (root / ".git").mkdir()
            release = {
                "tag_name": "1.2.0",
                "draft": False,
                "prerelease": False,
                "html_url": "https://example.test/release",
                "assets": [],
            }

            def opener(_request, **_kwargs):
                return _Response(json.dumps(release).encode())

            service = UpdateService(
                install,
                install_root=install,
                current_version="1.1.0",
                api_url="https://example.test/api",
                opener=opener,
            )
            result = service.check_and_stage()
            self.assertEqual(result.status, "manual_required")

    def test_update_lock_reports_busy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            _write_installed_manifest(install)
            service = UpdateService(install, install_root=install)
            with UpdateFileLock(install / "updates" / "update.lock"):
                result = service.check_and_stage()
            self.assertEqual(result.status, "busy")

    def test_release_manifest_cannot_target_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            _write_installed_manifest(install)
            archive = _release_archive(
                "1.2.0",
                extra_files={"HCQ/settings.json": b'{"poisoned":true}'},
            )
            checksum = hashlib.sha256(archive).hexdigest()
            release = {
                "tag_name": "1.2.0",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "HCQ-1.2.0-windows.zip",
                        "browser_download_url": "https://example.test/archive",
                    },
                    {
                        "name": "HCQ-1.2.0-windows.zip.sha256",
                        "browser_download_url": "https://example.test/checksum",
                    },
                ],
            }
            values = {
                "https://example.test/api": json.dumps(release).encode(),
                "https://example.test/archive": archive,
                "https://example.test/checksum": (
                    f"{checksum}  HCQ-1.2.0-windows.zip\n".encode()
                ),
            }

            def opener(request, **_kwargs):
                return _Response(values[request.full_url])

            result = UpdateService(
                install,
                install_root=install,
                current_version="1.1.0",
                api_url="https://example.test/api",
                opener=opener,
            ).check_and_stage()
            self.assertEqual(result.status, "error")
            self.assertIn("user data", result.message.lower())

    def test_stale_pending_does_not_downgrade_manual_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            storage = install
            _write_installed_manifest(install, "1.3.0")
            stage = storage / "updates" / "staged" / "1.2.0"
            stage.mkdir(parents=True)
            pending_path = storage / "updates" / "pending.json"
            pending_path.write_text(
                json.dumps(
                    {
                        "schema": "hcq.pending-update",
                        "schema_version": 1,
                        "from_version": "1.1.0",
                        "to_version": "1.2.0",
                        "install_root": str(install),
                        "install_parent": str(root),
                        "stage_root": str(stage),
                        "files": [],
                        "remove": [],
                    }
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                applied = hcq_update_bootstrap.apply_pending(
                    plugin_root=install,
                    storage_root=storage,
                )

            self.assertIsNone(applied)
            self.assertFalse(pending_path.exists())
            self.assertTrue(
                (storage / "updates" / "stale-1.2.0.json").is_file()
            )

    def test_failed_apply_rolls_back_replaced_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            storage = install
            _write_installed_manifest(install)
            stage = storage / "updates" / "staged" / "1.2.0"
            first_source = stage / "HCQ" / "first.py"
            second_source = stage / "HCQ" / "second.py"
            first_source.parent.mkdir(parents=True)
            first_source.write_bytes(b"new-first")
            second_source.write_bytes(b"new-second")
            first_target = install / "first.py"
            first_target.write_bytes(b"old-first")
            pending = {
                "schema": "hcq.pending-update",
                "schema_version": 1,
                "from_version": "1.1.0",
                "to_version": "1.2.0",
                "install_root": str(install),
                "install_parent": str(root),
                "stage_root": str(stage),
                "files": [
                    {
                        "path": "HCQ/first.py",
                        "sha256": hashlib.sha256(b"new-first").hexdigest(),
                    },
                    {
                        "path": "HCQ/second.py",
                        "sha256": hashlib.sha256(b"new-second").hexdigest(),
                    },
                ],
                "remove": [],
            }
            pending_path = storage / "updates" / "pending.json"
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            pending_path.write_text(json.dumps(pending), encoding="utf-8")

            original_copy = hcq_update_bootstrap._atomic_copy

            def fail_second(source, target):
                if target.name == "second.py":
                    raise OSError("simulated replacement failure")
                return original_copy(source, target)

            with mock.patch.object(
                hcq_update_bootstrap, "_atomic_copy", fail_second
            ), redirect_stdout(io.StringIO()):
                applied = hcq_update_bootstrap.apply_pending(
                    plugin_root=install,
                    storage_root=storage,
                )
            self.assertIsNone(applied)
            self.assertEqual(first_target.read_bytes(), b"old-first")
            self.assertFalse(pending_path.exists())
            self.assertTrue(
                (storage / "updates" / "failed-1.2.0.json").is_file()
            )


if __name__ == "__main__":
    unittest.main()
