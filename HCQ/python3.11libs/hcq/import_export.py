"""Safe JSON import, export, and path remapping."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .models import QueueTemplate, queue_library_document
from .storage import atomic_write_json
from .validation import parse_queue_document

PATH_FIELD_NAMES = {
    "hip_file",
    "output_path",
    "output_paths",
    "expected_outputs",
    "reference_path",
    "reference_paths",
}


def load_document(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("The JSON root must be an object.")
    return value


def import_queues(path: str | Path) -> list[QueueTemplate]:
    return parse_queue_document(load_document(path))


def export_queues(
    path: str | Path,
    queues: list[QueueTemplate],
    houdini_version: str = "21.0",
) -> None:
    atomic_write_json(path, queue_library_document(queues, houdini_version))


def remap_document_paths(value: dict[str, Any], original: str, replacement: str) -> dict[str, Any]:
    """Return a remapped copy while intentionally leaving node_path untouched."""
    if not original:
        raise ValueError("Original path cannot be empty.")
    document = copy.deepcopy(value)

    def visit(item: Any, key: str = "") -> Any:
        if isinstance(item, dict):
            return {child_key: visit(child_value, child_key) for child_key, child_value in item.items()}
        if isinstance(item, list):
            return [visit(child, key) for child in item]
        if isinstance(item, str) and key in PATH_FIELD_NAMES:
            return item.replace(original, replacement)
        return item

    return visit(document)


def missing_node_paths(queues: list[QueueTemplate], node_lookup: Any) -> list[tuple[str, str, str]]:
    missing: list[tuple[str, str, str]] = []
    for queue in queues:
        for job in queue.jobs:
            if job.enabled and node_lookup(job.node_path) is None:
                missing.append((queue.id, job.id, job.node_path))
    return missing


def replace_job_node(
    queues: list[QueueTemplate],
    queue_id: str,
    job_id: str,
    replacement: str | None,
    disable: bool = False,
    remove: bool = False,
) -> None:
    for queue in queues:
        if queue.id != queue_id:
            continue
        for index, job in enumerate(queue.jobs):
            if job.id != job_id:
                continue
            if remove:
                queue.jobs.pop(index)
            elif disable:
                job.enabled = False
            elif replacement:
                if not replacement.startswith("/"):
                    raise ValueError("Replacement node path must be absolute.")
                job.node_path = replacement
            queue.normalize_order()
            return
    raise KeyError(f"Job not found: {queue_id}/{job_id}")
