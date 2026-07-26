from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "HCQ" / "python3.11libs"
sys.path.insert(0, str(LIB))

import hcq_installation
import hcq_restart_helper
from hcq.restart import restart_block_reason, restart_houdini
from hcq.updater import UpdateService


HELPER_SPEC = importlib.util.spec_from_file_location(
    "hcq_installer_helper",
    ROOT / "tools" / "hcq_installer_helper.py",
)
assert HELPER_SPEC is not None and HELPER_SPEC.loader is not None
hcq_installer_helper = importlib.util.module_from_spec(HELPER_SPEC)
HELPER_SPEC.loader.exec_module(hcq_installer_helper)


class _Response:
    def __init__(self, value: bytes):
        self.value = value

    def __enter__(self):
        import io

        self.stream = io.BytesIO(self.value)
        return self.stream

    def __exit__(self, *_args):
        self.stream.close()


class InstallationTests(unittest.TestCase):
    def test_shared_update_root_is_installation_scoped(self):
        with tempfile.TemporaryDirectory(prefix="hcq 日本語 ") as temporary:
            base = Path(temporary)
            first = hcq_installation.shared_updates_root(
                base / "Program A",
                environment={"LOCALAPPDATA": str(base / "Local Data")},
            )
            second = hcq_installation.shared_updates_root(
                base / "Program B",
                environment={"LOCALAPPDATA": str(base / "Local Data")},
            )
            self.assertEqual(first.parent.parent, (base / "Local Data" / "HCQ"))
            self.assertNotEqual(first, second)

    def test_installation_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            install.mkdir()
            self.assertEqual(
                hcq_installation.installation_mode(install),
                "package_archive",
            )
            (install / "HCQ_INSTALLATION.json").write_text(
                json.dumps(
                    {
                        "schema": "hcq.installation",
                        "schema_version": 1,
                        "install_mode": "inno",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                hcq_installation.installation_mode(install),
                "inno",
            )
            (install / "HCQ_INSTALLATION.json").unlink()
            (root / "packages").mkdir()
            (root / "packages" / "hcq.json").write_text(
                '{"env":[{"HCQ_ROOT":"$HOUDINI_PACKAGE_PATH/../HCQ"}]}',
                encoding="utf-8",
            )
            self.assertEqual(
                hcq_installation.installation_mode(install),
                "legacy",
            )
            (root / ".git").mkdir()
            self.assertEqual(
                hcq_installation.installation_mode(install),
                "development",
            )

    @unittest.skipUnless(os.name == "nt", "Windows file locking is required")
    def test_runtime_markers_report_only_live_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            updates = Path(temporary)
            live = hcq_installation.RuntimeInstanceLock(updates, pid=12345)
            live.acquire()
            try:
                self.assertEqual(
                    hcq_installation.active_runtime_instances(updates),
                    [12345],
                )
            finally:
                live.release()
            self.assertEqual(
                hcq_installation.active_runtime_instances(updates),
                [],
            )

    def test_legacy_migration_preserves_data_and_modified_files(self):
        with tempfile.TemporaryDirectory(prefix="hcq migrate 日本語 ") as temporary:
            root = Path(temporary)
            preference = root / "OneDrive Documents" / "houdini21.0"
            plugin = preference / "HCQ"
            code = plugin / "python3.11libs" / "hcq" / "module.py"
            modified = plugin / "README.md"
            settings = plugin / "settings.json"
            code.parent.mkdir(parents=True)
            code.write_bytes(b"original")
            modified.write_bytes(b"changed")
            settings.write_text('{"keep": true}', encoding="utf-8")
            manifest = {
                "schema": "hcq.release-manifest",
                "schema_version": 1,
                "hcq_version": "1.1.2",
                "files": [
                    {
                        "path": "HCQ/python3.11libs/hcq/module.py",
                        "sha256": hashlib.sha256(b"original").hexdigest(),
                    },
                    {
                        "path": "HCQ/README.md",
                        "sha256": hashlib.sha256(b"original-readme").hexdigest(),
                    },
                    {
                        "path": "packages/hcq.json",
                        "sha256": "0" * 64,
                    },
                ],
            }
            (plugin / "HCQ_MANIFEST.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            result = hcq_installer_helper.migrate_legacy_install(
                preference,
                root / "Backups",
            )
            self.assertFalse(code.exists())
            self.assertTrue(modified.is_file())
            self.assertTrue(settings.is_file())
            self.assertIn("HCQ/README.md", result["preserved"])
            self.assertIn(
                "HCQ/python3.11libs/hcq/module.py",
                result["removed"],
            )
            self.assertTrue(
                next((root / "Backups").rglob("module.py")).is_file()
            )

    def test_legacy_migration_journal_restores_removed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preference = root / "OneDrive 日本語" / "houdini21.0"
            plugin = preference / "HCQ"
            plugin.mkdir(parents=True)
            owned = plugin / "owned.py"
            owned.write_text("original", encoding="utf-8")
            manifest = plugin / "HCQ_MANIFEST.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema": "hcq.release-manifest",
                        "schema_version": 1,
                        "files": [
                            {
                                "path": "HCQ/owned.py",
                                "sha256": hcq_installer_helper.sha256_file(owned),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            journal = root / "migration.json"
            hcq_installer_helper.migrate_legacy_install(
                preference,
                root / "backups",
                journal,
            )
            self.assertFalse(owned.exists())
            self.assertFalse(manifest.exists())
            restored = hcq_installer_helper.rollback_legacy_migration(journal)
            self.assertEqual(
                set(restored),
                {"HCQ/owned.py", "HCQ/HCQ_MANIFEST.json"},
            )
            self.assertEqual(owned.read_text(encoding="utf-8"), "original")
            self.assertTrue(manifest.is_file())
            self.assertFalse(journal.exists())

    def test_legacy_migration_rejects_manifest_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin = root / "houdini21.0" / "HCQ"
            plugin.mkdir(parents=True)
            (plugin / "HCQ_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "schema": "hcq.release-manifest",
                        "schema_version": 1,
                        "files": [
                            {
                                "path": "HCQ/../outside.txt",
                                "sha256": "0" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = hcq_installer_helper.migrate_legacy_install(
                plugin.parent,
                root / "backup",
            )
            self.assertEqual(result["preserved"], ["HCQ/../outside.txt"])
            self.assertFalse((plugin / "HCQ_MANIFEST.json").exists())

    def test_legacy_up_to_date_install_stages_standard_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "HCQ"
            install.mkdir()
            (install / "HCQ_INSTALLATION.json").write_text(
                json.dumps(
                    {
                        "schema": "hcq.installation",
                        "schema_version": 1,
                        "install_mode": "legacy",
                    }
                ),
                encoding="utf-8",
            )
            installer = b"MZ-test-installer"
            digest = hashlib.sha256(installer).hexdigest()
            release = {
                "tag_name": "v1.2.0",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": "HCQ-Setup-1.2.0.exe",
                        "browser_download_url": "https://example/installer",
                    },
                    {
                        "name": "HCQ-Setup-1.2.0.exe.sha256",
                        "browser_download_url": "https://example/checksum",
                    },
                ],
            }
            values = {
                "https://example/api": json.dumps(release).encode(),
                "https://example/installer": installer,
                "https://example/checksum": (
                    f"{digest}  HCQ-Setup-1.2.0.exe\n".encode()
                ),
            }

            def opener(request, **_kwargs):
                return _Response(values[request.full_url])

            service = UpdateService(
                root,
                install_root=install,
                updates_root=root / "shared-updates",
                current_version="1.2.0",
                api_url="https://example/api",
                opener=opener,
            )
            result = service.check_and_stage()
            self.assertEqual(result.status, "migration_ready")
            self.assertTrue(result.migration_required)
            self.assertTrue(Path(result.installer_path).is_file())


class _FakeHipFile:
    def __init__(self, path: Path, new_file: bool = False):
        self._path = path
        self._new = new_file

    def isNewFile(self):
        return self._new

    def path(self):
        return str(self._path)


class _FakeHou:
    def __init__(self, root: Path, hip: Path, *, cancel: bool = False):
        self.root = root
        self.hipFile = _FakeHipFile(hip)
        self.cancel = cancel

    def expandString(self, _value):
        return str(self.root)

    def exit(self, *_args, **_kwargs):
        if self.cancel:
            return None
        raise SystemExit()


class RestartTests(unittest.TestCase):
    def test_restart_is_blocked_during_queue(self):
        manager = SimpleNamespace(
            runner=SimpleNamespace(state="running", active=True),
            updater=SimpleNamespace(other_runtime_instances=lambda: []),
        )
        self.assertIn("active HCQ queue", restart_block_reason(manager))

    def test_restart_is_blocked_by_another_houdini(self):
        manager = SimpleNamespace(
            runner=SimpleNamespace(state="idle", active=False),
            updater=SimpleNamespace(other_runtime_instances=lambda: [22]),
        )
        self.assertIn("Another Houdini", restart_block_reason(manager))

    def test_restart_helper_launches_only_after_exit_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "python311" / "python.exe"
            python.parent.mkdir()
            python.write_bytes(b"")
            hip = root / "scene.hip"
            hip.write_bytes(b"hip")
            manager = SimpleNamespace(
                hou=_FakeHou(root, hip),
                runner=SimpleNamespace(state="idle", active=False),
                updater=SimpleNamespace(other_runtime_instances=lambda: []),
            )
            launched = []
            with self.assertRaises(SystemExit):
                restart_houdini(
                    manager,
                    popen=lambda command, **kwargs: launched.append(
                        (command, kwargs)
                    ),
                )
            self.assertEqual(len(launched), 1)
            self.assertIn(str(hip), launched[0][0])

    def test_cancelled_houdini_exit_does_not_launch_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "python311" / "python.exe"
            python.parent.mkdir()
            python.write_bytes(b"")
            hip = root / "scene.hip"
            hip.write_bytes(b"hip")
            manager = SimpleNamespace(
                hou=_FakeHou(root, hip, cancel=True),
                runner=SimpleNamespace(state="idle", active=False),
                updater=SimpleNamespace(other_runtime_instances=lambda: []),
            )
            launched = []
            self.assertFalse(
                restart_houdini(
                    manager,
                    popen=lambda *args, **kwargs: launched.append(
                        (args, kwargs)
                    ),
                )
            )
            self.assertEqual(launched, [])

    def test_restart_helper_runs_installer_before_houdini(self):
        installer_result = SimpleNamespace(returncode=0)
        with mock.patch.object(
            hcq_restart_helper,
            "wait_for_process",
            return_value=True,
        ), mock.patch.object(
            hcq_restart_helper.subprocess,
            "run",
            return_value=installer_result,
        ) as run, mock.patch.object(
            hcq_restart_helper.subprocess,
            "Popen",
        ) as popen:
            code = hcq_restart_helper.relaunch(
                wait_pid=10,
                executable="houdini.exe",
                hip_file="scene.hip",
                installer="HCQ-Setup.exe",
            )
        self.assertEqual(code, 0)
        run.assert_called_once()
        popen.assert_called_once_with(
            ["houdini.exe", "scene.hip"],
            close_fds=True,
        )


if __name__ == "__main__":
    unittest.main()
