"""Output verification shared by queue adapters."""

from __future__ import annotations

import glob
import os
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
) -> VerificationResult:
    result = VerificationResult()
    patterns = [item for item in patterns if item]
    if not patterns:
        return result
    paths = expand_output_patterns(patterns, expand_string)
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
