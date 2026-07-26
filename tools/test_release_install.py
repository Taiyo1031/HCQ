"""Validate HCQ release assets and clean-load both ZIP distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_LIB = ROOT / "HCQ" / "python3.11libs"
if str(SOURCE_LIB) not in sys.path:
    sys.path.insert(0, str(SOURCE_LIB))

from hcq.constants import VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_checksum(path: Path) -> None:
    checksum = path.with_name(f"{path.name}.sha256")
    if not checksum.is_file():
        raise FileNotFoundError(checksum)
    fields = checksum.read_text(encoding="utf-8-sig").split()
    if not fields or fields[0].lower() != _sha256(path):
        raise AssertionError(f"Release checksum mismatch: {path.name}")
    if len(fields) > 1 and fields[-1].lstrip("*") != path.name:
        raise AssertionError(f"Checksum filename mismatch: {path.name}")


def validate_zip(path: Path, *, package_archive: bool) -> None:
    validate_checksum(path)
    with zipfile.ZipFile(path) as source:
        names = {
            name for name in source.namelist() if not name.endswith("/")
        }
        if any(
            Path(name).is_absolute()
            or "\\" in name
            or ".." in Path(name).parts
            for name in names
        ):
            raise AssertionError(f"Unsafe path in {path.name}")
        if "HCQ/HCQ_MANIFEST.json" not in names:
            raise AssertionError("Release manifest is missing.")
        if package_archive:
            if "hcq.json" not in names or "packages/hcq.json" in names:
                raise AssertionError("Package Archive layout is invalid.")
        elif "packages/hcq.json" not in names:
            raise AssertionError("Legacy package JSON is missing.")
        manifest = json.loads(source.read("HCQ/HCQ_MANIFEST.json"))
        if (
            manifest.get("schema") != "hcq.release-manifest"
            or manifest.get("schema_version") != 1
            or manifest.get("hcq_version") != VERSION
        ):
            raise AssertionError("Release manifest metadata is invalid.")
        declared = {
            item["path"]: item["sha256"] for item in manifest["files"]
        }
        expected = names - {"HCQ/HCQ_MANIFEST.json"}
        expected.discard("INSTALL.txt")
        expected.discard("hcq.json")
        if set(declared) != expected:
            raise AssertionError("Release manifest file list is incomplete.")
        for name, expected_digest in declared.items():
            if hashlib.sha256(source.read(name)).hexdigest() != expected_digest:
                raise AssertionError(f"Release file checksum mismatch: {name}")


def clean_load_zip(
    archive: Path,
    houdini_root: Path,
    *,
    package_archive: bool,
) -> dict[str, str]:
    hython = houdini_root / "bin" / "hython.exe"
    if not hython.is_file():
        raise FileNotFoundError(hython)
    with tempfile.TemporaryDirectory(prefix="hcq-clean-install-") as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(archive) as source:
            source.extractall(root)
        preference = root / "preferences" / "houdini21.0"
        preference.mkdir(parents=True)
        environment = dict(os.environ)
        environment["HOUDINI_USER_PREF_DIR"] = str(preference)
        environment["HOUDINI_PACKAGE_DIR"] = str(
            root if package_archive else root / "packages"
        )
        check = (
            "import json, pathlib, hcq, hou; "
            "print(json.dumps({"
            "'module': str(pathlib.Path(hcq.__file__).resolve()), "
            "'version': hcq.__version__, "
            "'houdini': hou.applicationVersionString()"
            "}))"
        )
        result = subprocess.run(
            [str(hython), "-c", check],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        module_path = Path(payload["module"])
        expected_root = (root / "HCQ").resolve()
        if expected_root not in module_path.parents:
            raise AssertionError(
                f"HCQ loaded from {module_path}, expected under {expected_root}."
            )
        if payload["version"] != VERSION:
            raise AssertionError(payload)
        return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument(
        "--houdini-root",
        type=Path,
        default=Path(
            r"C:\Program Files\Side Effects Software\Houdini 21.0.729"
        ),
    )
    parser.add_argument("--skip-houdini", action="store_true")
    arguments = parser.parse_args()
    dist = (ROOT / arguments.dist).resolve()
    legacy = dist / f"HCQ-{VERSION}-windows.zip"
    package = dist / f"HCQ-{VERSION}-houdini-package.zip"
    setup = dist / f"HCQ-Setup-{VERSION}.exe"
    for path in (legacy, package):
        if not path.is_file():
            raise FileNotFoundError(path)
    validate_zip(legacy, package_archive=False)
    validate_zip(package, package_archive=True)
    if setup.is_file():
        validate_checksum(setup)
        if setup.read_bytes()[:2] != b"MZ":
            raise AssertionError("The Windows installer is not a PE file.")
    results = []
    if not arguments.skip_houdini:
        results = [
            clean_load_zip(
                legacy,
                arguments.houdini_root,
                package_archive=False,
            ),
            clean_load_zip(
                package,
                arguments.houdini_root,
                package_archive=True,
            ),
        ]
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
