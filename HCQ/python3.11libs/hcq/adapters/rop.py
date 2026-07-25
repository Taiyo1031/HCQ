"""Foreground ROP render adapter."""

from __future__ import annotations

from typing import Any

from ..constants import OUTPUT_PARAMETER_NAMES
from ..models import Job
from .base import (
    ActionAdapter,
    frame_range_for_job,
    node_category_name,
    parameter_output_patterns,
)


class RopAdapter(ActionAdapter):
    action = "rop_render"

    def can_handle(self, node: Any, job: Job | None = None) -> bool:
        rop_type = getattr(self.hou, "RopNode", None)
        if rop_type is not None:
            try:
                if isinstance(node, rop_type):
                    return True
            except TypeError:
                pass
        return node_category_name(node).lower() in {"driver", "rop"} and callable(
            getattr(node, "render", None)
        )

    def validate(self, node: Any, job: Job) -> list[str]:
        errors = super().validate(node, job)
        if node is not None and not self.can_handle(node, job):
            errors.append("ROP Render requires a renderable ROP node.")
        return errors

    def _execute_native(self, node: Any, job: Job) -> Any:
        frame_range = frame_range_for_job(job, self.hou)
        if frame_range is None:
            return node.render()
        return node.render(frame_range=frame_range)

    def expected_output_patterns(self, node: Any, job: Job) -> list[str]:
        return parameter_output_patterns(node, OUTPUT_PARAMETER_NAMES)
