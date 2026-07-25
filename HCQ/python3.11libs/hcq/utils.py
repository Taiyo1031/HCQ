"""Small dependency-free helpers."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def new_session_id() -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"session-{stamp}-{uuid.uuid4().hex[:8]}"


def normalized_path(value: str) -> str:
    if not value:
        return ""
    return os.path.normcase(os.path.abspath(os.path.expandvars(value)))


def normalized_hip_key(value: str, is_new_file: bool = False) -> str:
    if not value or is_new_file or Path(value).name.lower().startswith("untitled"):
        return "__untitled__"
    return normalized_path(value)


def deduplicated(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def expand_frame_pattern(pattern: str, frame: int) -> str:
    """Expand common Houdini frame tokens without evaluating arbitrary code."""
    match = re.search(r"\$F(\d*)", pattern)
    if match:
        width = int(match.group(1) or "1")
        pattern = pattern[: match.start()] + str(frame).zfill(width) + pattern[match.end() :]
    match = re.search(r"<F(\d*)>", pattern)
    if match:
        width = int(match.group(1) or "1")
        pattern = pattern[: match.start()] + str(frame).zfill(width) + pattern[match.end() :]
    return pattern


def frame_values(start: int, end: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("Frame step must be greater than zero.")
    if end < start:
        raise ValueError("Frame end must be greater than or equal to start.")
    return list(range(start, end + 1, step))
