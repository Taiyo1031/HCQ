"""Output verification shared by queue adapters."""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


@dataclass
class VerificationResult:
    success: bool = True
    output_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_FRAME_TOKEN = re.compile(r"(?:\$F\d*(?![A-Za-z0-9_])|<F\d*>)")
_UNRESOLVED_VARIABLE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*")


def output_path_is_resolved(value: str) -> bool:
    """Return whether an expanded disk path has no unresolved Houdini variables."""
    candidate = str(value).strip()
    if not candidate:
        return False
    candidate = _FRAME_TOKEN.sub("", candidate)
    return "`" not in candidate and _UNRESOLVED_VARIABLE.search(candidate) is None


def expand_output_patterns(
    patterns: Iterable[str], expand_string: Callable[[str], str] | None = None
) -> list[str]:
    expanded: list[str] = []
    for pattern in patterns:
        value = expand_string(pattern) if expand_string else os.path.expandvars(pattern)
        value = value.replace("$F4", "*").replace("$F3", "*").replace("$F2", "*").replace("$F", "*")
        value = value.replace("<F4>", "*").replace("<F3>", "*").replace("<F2>", "*").replace("<F>", "*")
        matches = glob.glob(value)
        if matches:
            expanded.extend(matches)
        elif not any(token in value for token in ("*", "?", "[")):
            expanded.append(value)
    return list(dict.fromkeys(expanded))


def verify_outputs(
    patterns: Iterable[str],
    started_at: datetime,
    expand_string: Callable[[str], str] | None = None,
    *,
    require_patterns: bool = False,
    missing_patterns_message: str = "No output path could be resolved.",
) -> VerificationResult:
    result = VerificationResult()
    patterns = [item for item in patterns if item]
    if not patterns:
        if require_patterns:
            result.success = False
            result.errors.append(missing_patterns_message)
        return result

    resolved_patterns: list[str] = []
    for pattern in patterns:
        expanded = expand_string(pattern) if expand_string else os.path.expandvars(pattern)
        if not output_path_is_resolved(expanded):
            result.success = False
            result.errors.append(f"Output path is empty or unresolved: {pattern}")
            continue
        resolved_patterns.append(pattern)
    if not resolved_patterns:
        if require_patterns and not result.errors:
            result.success = False
            result.errors.append(missing_patterns_message)
        return result

    paths = expand_output_patterns(resolved_patterns, expand_string)
    if not paths:
        result.success = False
        result.errors.append("No output files matched the expected output patterns.")
        return result
    started_timestamp = started_at.timestamp()
    for value in paths:
        path = Path(value)
        if not path.exists():
            result.success = False
            result.errors.append(f"Expected output does not exist: {value}")
            continue
        if path.is_file():
            if path.stat().st_size <= 0:
                result.success = False
                result.errors.append(f"Output file is empty: {value}")
            if path.stat().st_mtime + 1.0 < started_timestamp:
                result.success = False
                result.errors.append(f"Output was not updated by this job: {value}")
            result.output_paths.append(str(path))
    return result
