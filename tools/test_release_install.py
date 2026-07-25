"""Validate the built ZIP from a clean temporary Houdini preference layout."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("dist/HCQ-1.0.0-windows.zip"),
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
        if payload["version"] != "1.0.0":
            raise AssertionError(payload)
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
