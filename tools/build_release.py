"""Build the versioned Windows distribution archive for HCQ."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


SOURCE_LIB = Path(__file__).resolve().parents[1] / "HCQ" / "python3.11libs"
if str(SOURCE_LIB) not in sys.path:
    sys.path.insert(0, str(SOURCE_LIB))

from hcq.constants import VERSION


MANIFEST_NAME = "HCQ_MANIFEST.json"
RESERVED_DATA_PATHS = (
    "HCQ/settings.json",
    "HCQ/monitor_registry.json",
    "HCQ/queues",
    "HCQ/runs",
    "HCQ/logs",
    "HCQ/recovery",
    "HCQ/updates",
)


def validate_package(package_file: Path) -> None:
    with package_file.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if value.get("hpath") != "$HCQ_ROOT":
        raise ValueError("Package JSON does not point to $HCQ_ROOT.")


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


def write_manifest(stage: Path) -> Path:
    manifest = stage / "HCQ" / MANIFEST_NAME
    files = []
    for path in release_files(stage):
        if path == manifest:
            continue
        relative = path.relative_to(stage).as_posix()
        if relative == "INSTALL.txt":
            continue
        if any(
            relative == reserved or relative.startswith(f"{reserved}/")
            for reserved in RESERVED_DATA_PATHS
        ):
            raise ValueError(
                f"Release source contains reserved HCQ user data: {relative}"
            )
        files.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
            }
        )
    with manifest.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            {
                "schema": "hcq.release-manifest",
                "schema_version": 1,
                "hcq_version": VERSION,
                "files": files,
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")
    return manifest


def build(root: Path, output_directory: Path) -> Path:
    plugin = root / "HCQ"
    package = root / "packages" / "hcq.json"
    install = root / "INSTALL.txt"
    readme = root / "README.md"
    documentation = root / "docs"
    if (
        not plugin.is_dir()
        or not package.is_file()
        or not install.is_file()
        or not readme.is_file()
        or not documentation.is_dir()
    ):
        raise FileNotFoundError("The HCQ source layout is incomplete.")
    validate_package(package)
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"HCQ-{VERSION}-windows.zip"
    with tempfile.TemporaryDirectory(prefix="hcq-release-") as temporary:
        stage = Path(temporary)
        shutil.copytree(plugin, stage / "HCQ")
        shutil.copy2(readme, stage / "HCQ" / "README.md")
        shutil.copytree(documentation, stage / "HCQ" / "docs")
        (stage / "packages").mkdir()
        shutil.copy2(package, stage / "packages" / "hcq.json")
        shutil.copy2(install, stage / "INSTALL.txt")
        write_manifest(stage)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in release_files(stage):
                archive.write(path, path.relative_to(stage).as_posix())
    checksum = destination.with_name(f"{destination.name}.sha256")
    checksum.write_text(
        f"{sha256_file(destination)}  {destination.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("dist"))
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = build(root, (root / arguments.output).resolve())
    try:
        print(destination)
    except UnicodeEncodeError:
        # Some embedded Windows runtimes force a legacy stdout codec even
        # when the checkout path contains non-ASCII characters.
        print(destination.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
