"""Temporary Houdini CPU thread limits."""

from __future__ import annotations

import os
from typing import Any

from .models import CpuSetting


def resolve_thread_limit(setting: CpuSetting, available: int | None = None) -> int | None:
    available = max(1, available or (os.cpu_count() or 1))
    if setting.mode in {"current", "inherit"}:
        return None
    if setting.mode == "all":
        return 0
    if setting.mode == "single":
        return 1
    if setting.mode == "threads":
        if setting.value is None or setting.value < 1:
            raise ValueError("Maximum Threads must be a positive integer.")
        return min(setting.value, available)
    if setting.mode == "reserve":
        if setting.value is None or setting.value < 1:
            raise ValueError("Reserve Threads must be a positive integer.")
        return max(1, available - setting.value)
    raise ValueError(f"Unsupported CPU mode: {setting.mode}")


class TemporaryThreadLimit:
    def __init__(self, hou_module: Any, setting: CpuSetting) -> None:
        self.hou = hou_module
        self.setting = setting
        self.previous: int | None = None
        self.applied: int | None = None

    def __enter__(self) -> int | None:
        self.previous = int(self.hou.maxThreads())
        self.applied = resolve_thread_limit(self.setting)
        if self.applied is not None:
            self.hou.setMaxThreads(self.applied)
        return self.applied

    def __exit__(self, *_args: object) -> None:
        if self.previous is not None:
            self.hou.setMaxThreads(self.previous)
