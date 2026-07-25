"""Generic forced Houdini node cook adapter."""

from __future__ import annotations

from typing import Any

from ..models import Job
from .base import ActionAdapter, frame_range_for_job


class GenericAdapter(ActionAdapter):
    action = "force_cook"

    def can_handle(self, node: Any, job: Job | None = None) -> bool:
        return node is not None and callable(getattr(node, "cook", None))

    def validate(self, node: Any, job: Job) -> list[str]:
        errors = super().validate(node, job)
        if node is not None and not callable(getattr(node, "cook", None)):
            errors.append("Force Cook requires a cookable Houdini node.")
        return errors

    def _execute_native(self, node: Any, job: Job) -> Any:
        frame_range = frame_range_for_job(job, self.hou)
        if frame_range is None:
            return node.cook(force=True)
        try:
            return node.cook(force=True, frame_range=frame_range)
        except TypeError:
            # Some HOM node subclasses do not accept frame_range.
            return node.cook(force=True)
