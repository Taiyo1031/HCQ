"""Build HCQ's Windows installer, Package Archive, and legacy update ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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


MANIFEST_NAME = "HCQ_MANIFEST.json"
INSTALLATION_NAME = "HCQ_INSTALLATION.json"
RESERVED_DATA_PATHS = (
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


def release_files(stage: Path) -> list[Path]:
    return [
        path
        for path in sorted(stage.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    ]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_checksum(path: Path) -> Path:
    checksum = path.with_name(f"{path.name}.sha256")
    checksum.write_text(
        f"{sha256_file(path)}  {path.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return checksum


def _validate_package(path: Path, expected_hpath: str) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("hpath") != expected_hpath:
        raise ValueError(f"Unexpected HCQ package hpath: {path}")
    enable = str(value.get("enable", ""))
    if "houdini_version < '22.0'" not in enable or "windows" not in enable:
        raise ValueError(f"HCQ package compatibility is incomplete: {path}")


def _copy_plugin(stage: Path, mode: str) -> None:
    source = ROOT / "HCQ"
    if not source.is_dir():
        raise FileNotFoundError(source)
    plugin = stage / "HCQ"
    shutil.copytree(source, plugin)
    shutil.copy2(ROOT / "README.md", plugin / "README.md")
    shutil.copytree(ROOT / "docs", plugin / "docs")
    install_tools = plugin / "install_tools"
    install_tools.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "tools" / "hcq_installer_helper.py",
        install_tools / "hcq_installer_helper.py",
    )
    shutil.copy2(
        ROOT / "installer" / "hcq-install.json",
        install_tools / "hcq-install.json",
    )
    _write_json(
        plugin / INSTALLATION_NAME,
        {
            "schema": "hcq.installation",
            "schema_version": 1,
            "hcq_version": VERSION,
            "install_mode": mode,
        },
    )


def _write_manifest(stage: Path, *, include_packages: bool) -> Path:
    manifest = stage / "HCQ" / MANIFEST_NAME
    files: list[dict[str, str]] = []
    for path in release_files(stage):
        if path == manifest:
            continue
        relative = path.relative_to(stage).as_posix()
        if relative in {"INSTALL.txt", "hcq.json"}:
            continue
        if not include_packages and not relative.startswith("HCQ/"):
            continue
        if any(
            relative == reserved or relative.startswith(f"{reserved}/")
            for reserved in RESERVED_DATA_PATHS
        ):
            raise ValueError(
                f"Release source contains reserved HCQ user data: {relative}"
            )
        files.append({"path": relative, "sha256": sha256_file(path)})
    _write_json(
        manifest,
        {
            "schema": "hcq.release-manifest",
            "schema_version": 1,
            "hcq_version": VERSION,
            "files": files,
        },
    )
    return manifest


def _write_zip(stage: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(
        destination,
        "w",
        zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in release_files(stage):
            archive.write(path, path.relative_to(stage).as_posix())
    _write_checksum(destination)
    return destination


def build_legacy_archive(output_directory: Path) -> Path:
    package = ROOT / "packages" / "hcq.json"
    _validate_package(package, "$HCQ_ROOT")
    with tempfile.TemporaryDirectory(prefix="hcq-legacy-") as temporary:
        stage = Path(temporary)
        _copy_plugin(stage, "legacy")
        (stage / "packages").mkdir()
        shutil.copy2(package, stage / "packages" / "hcq.json")
        shutil.copy2(ROOT / "INSTALL.txt", stage / "INSTALL.txt")
        _write_manifest(stage, include_packages=True)
        return _write_zip(
            stage,
            output_directory / f"HCQ-{VERSION}-windows.zip",
        )


def build_package_archive(output_directory: Path) -> Path:
    package = ROOT / "installer" / "hcq-package-archive.json"
    _validate_package(package, "$HCQ_ROOT")
    with tempfile.TemporaryDirectory(prefix="hcq-package-") as temporary:
        stage = Path(temporary)
        _copy_plugin(stage, "package_archive")
        shutil.copy2(package, stage / "hcq.json")
        _write_manifest(stage, include_packages=False)
        return _write_zip(
            stage,
            output_directory / f"HCQ-{VERSION}-houdini-package.zip",
        )


def _find_iscc(explicit: str | Path | None) -> Path | None:
    if explicit:
        candidate = Path(explicit).resolve()
        return candidate if candidate.is_file() else None
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return Path(found).resolve()
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(
            Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe"
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_installer(
    output_directory: Path,
    *,
    iscc: str | Path | None = None,
    sign_command: str = "",
) -> Path:
    compiler = _find_iscc(iscc)
    if compiler is None:
        raise FileNotFoundError(
            "Inno Setup compiler ISCC.exe was not found. "
            "Use --iscc or --skip-installer."
        )
    package = ROOT / "installer" / "hcq-install.json"
    _validate_package(package, "$HCQ_ROOT")
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hcq-installer-") as temporary:
        wrapper = Path(temporary) / "wrapper"
        _copy_plugin(wrapper, "inno")
        _write_manifest(wrapper, include_packages=False)
        payload = Path(temporary) / "payload"
        shutil.copytree(wrapper / "HCQ", payload)
        command = [
            str(compiler),
            f"/DVersion={VERSION}",
            f"/DPayloadDir={payload}",
            f"/DOutputDir={output_directory.resolve()}",
        ]
        if sign_command:
            command.extend(
                [
                    "/DSignToolName=hcq",
                    f"/Shcq={sign_command}",
                ]
            )
        command.append(str(ROOT / "installer" / "hcq.iss"))
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    destination = output_directory / f"HCQ-Setup-{VERSION}.exe"
    if not destination.is_file():
        raise FileNotFoundError(destination)
    _write_checksum(destination)
    return destination


def build(
    root: Path,
    output_directory: Path,
    *,
    iscc: str | Path | None = None,
    skip_installer: bool = False,
    sign_command: str = "",
) -> list[Path]:
    if root.resolve() != ROOT.resolve():
        raise ValueError("HCQ releases must be built from the repository root.")
    output_directory.mkdir(parents=True, exist_ok=True)
    artifacts = [
        build_legacy_archive(output_directory),
        build_package_archive(output_directory),
    ]
    if not skip_installer:
        artifacts.append(
            build_installer(
                output_directory,
                iscc=iscc,
                sign_command=sign_command,
            )
        )
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--iscc", type=Path)
    parser.add_argument("--skip-installer", action="store_true")
    parser.add_argument(
        "--sign-command",
        default="",
        help="Inno Setup SignTool command; omitted for unsigned builds.",
    )
    arguments = parser.parse_args()
    destinations = build(
        ROOT,
        (ROOT / arguments.output).resolve(),
        iscc=arguments.iscc,
        skip_installer=arguments.skip_installer,
        sign_command=arguments.sign_command,
    )
    for destination in destinations:
        try:
            print(destination)
        except UnicodeEncodeError:
            print(destination.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
