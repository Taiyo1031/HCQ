"""Build the versioned Windows distribution archive for HCQ."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


VERSION = "1.0.0"


def validate_package(package_file: Path) -> None:
    with package_file.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if value.get("hpath") != "$HCQ_ROOT":
        raise ValueError("Package JSON does not point to $HCQ_ROOT.")


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
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    archive.write(path, path.relative_to(stage).as_posix())
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
