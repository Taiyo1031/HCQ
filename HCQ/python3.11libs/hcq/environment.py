"""Runtime environment checks for HCQ 1.0."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .constants import MIN_HOUDINI_VERSION


@dataclass(frozen=True)
class EnvironmentStatus:
    supported: bool
    message: str
    houdini_version: str = ""
    platform: str = ""
    ui_available: bool = False


def inspect_environment(hou_module: Any | None) -> EnvironmentStatus:
    if hou_module is None:
        return EnvironmentStatus(False, "The Houdini Object Model is not available.")
    version = tuple(int(value) for value in hou_module.applicationVersion()[:2])
    version_string = hou_module.applicationVersionString()
    platform = os.name
    ui_available = bool(hou_module.isUIAvailable())
    if platform != "nt":
        return EnvironmentStatus(
            False,
            "HCQ 1.0 supports Windows only.",
            version_string,
            platform,
            ui_available,
        )
    if version < MIN_HOUDINI_VERSION:
        return EnvironmentStatus(
            False,
            "HCQ requires Houdini 21.0 or later.",
            version_string,
            platform,
            ui_available,
        )
    if not ui_available:
        return EnvironmentStatus(
            False,
            "HCQ Queue Runner requires an interactive Houdini session.",
            version_string,
            platform,
            ui_available,
        )
    return EnvironmentStatus(True, "Supported", version_string, platform, ui_available)
