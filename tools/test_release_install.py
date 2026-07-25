"""Validate the built ZIP from a clean temporary Houdini preference layout."""

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


SOURCE_LIB = Path(__file__).resolve().parents[1] / "HCQ" / "python3.11libs"
if str(SOURCE_LIB) not in sys.path:
    sys.path.insert(0, str(SOURCE_LIB))

from hcq.constants import VERSION


def validate_release_contract(archive: Path) -> None:
    checksum_file = archive.with_name(f"{archive.name}.sha256")
    if not checksum_file.is_file():
        raise FileNotFoundError(checksum_file)
    fields = checksum_file.read_text(encoding="utf-8-sig").split()
    expected = fields[0].lower() if fields else ""
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise AssertionError("Release archive checksum mismatch.")

    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("HCQ/HCQ_MANIFEST.json"))
        if (
            manifest.get("schema") != "hcq.release-manifest"
            or manifest.get("schema_version") != 1
            or manifest.get("hcq_version") != VERSION
        ):
            raise AssertionError("Release manifest metadata is invalid.")
        declared = {item["path"]: item["sha256"] for item in manifest["files"]}
        actual = {
            name
            for name in source.namelist()
            if not name.endswith("/")
            and name not in {"HCQ/HCQ_MANIFEST.json", "INSTALL.txt"}
        }
        if set(declared) != actual:
            raise AssertionError("Release manifest file list is incomplete.")
        for name, expected_file_digest in declared.items():
            if hashlib.sha256(source.read(name)).hexdigest() != expected_file_digest:
                raise AssertionError(f"Release file checksum mismatch: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path(f"dist/HCQ-{VERSION}-windows.zip"),
    )
    parser.add_argument(
        "--houdini-root",
        type=Path,
        default=Path(r"C:\Program Files\Side Effects Software\Houdini 21.0.729"),
    )
    arguments = parser.parse_args()
    archive = arguments.archive.resolve()
    hython = arguments.houdini_root / "bin" / "hython.exe"
    if not archive.is_file():
        raise FileNotFoundError(archive)
    if not hython.is_file():
        raise FileNotFoundError(hython)
    validate_release_contract(archive)

    with tempfile.TemporaryDirectory(prefix="hcq-clean-install-") as temporary:
        install_root = Path(temporary)
        with zipfile.ZipFile(archive) as source:
            source.extractall(install_root)
        environment = dict(os.environ)
        environment["HOUDINI_USER_PREF_DIR"] = str(
            install_root / "preferences" / "houdini__HVER__"
        )
        environment["HOUDINI_PACKAGE_DIR"] = str(install_root / "packages")
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
            cwd=install_root,
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
        expected_root = (install_root / "HCQ").resolve()
        if expected_root not in module_path.parents:
            raise AssertionError(
                f"HCQ loaded from {module_path}, expected under {expected_root}."
            )
        if payload["version"] != VERSION:
            raise AssertionError(payload)
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
