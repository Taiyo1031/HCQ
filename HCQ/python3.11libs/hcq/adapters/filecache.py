"""Standard File Cache foreground Save to Disk adapter."""

from __future__ import annotations

from typing import Any

from ..models import Job
from .base import (
    ActionAdapter,
    TemporaryNodeFrameRange,
    frame_range_for_job,
    node_category_name,
    node_type_name,
    parameter_output_patterns,
)
from ..utils import frame_values


class FileCacheAdapter(ActionAdapter):
    action = "filecache_save_to_disk"

    def can_handle(self, node: Any, job: Job | None = None) -> bool:
        category = node_category_name(node).lower()
        type_name = node_type_name(node).lower()
        return category == "sop" and (
            type_name == "filecache"
            or type_name.startswith("filecache::")
            or type_name.endswith("::filecache")
        )

    def validate(self, node: Any, job: Job) -> list[str]:
        errors = super().validate(node, job)
        if node is not None and not self.can_handle(node, job):
            errors.append("File Cache Save to Disk requires a standard File Cache SOP.")
        if node is not None and self._execute_parm(node) is None:
            errors.append("The File Cache node has no foreground execute button.")
        return errors

    def _execute_native(self, node: Any, job: Job) -> Any:
        parm = self._execute_parm(node)
        if parm is None:
            raise RuntimeError("The File Cache foreground execute button is unavailable.")
        with TemporaryNodeFrameRange(node, job):
            return parm.pressButton()

    def expected_output_patterns(self, node: Any, job: Job) -> list[str]:
        try:
            constructed_path = int(node.parm("filemethod").eval()) == 0
        except Exception:
            constructed_path = False
        if constructed_path:
            return parameter_output_patterns(node, ("sopoutput",))
        return parameter_output_patterns(node, ("file",))

    def requires_output(self, node: Any, job: Job) -> bool:
        return True

    def missing_output_message(self, node: Any, job: Job) -> str:
        return "The File Cache output path is empty or unresolved."

    def _verification_patterns(
        self, node: Any, job: Job, patterns: list[str]
    ) -> list[str]:
        try:
            constructed_path = int(node.parm("filemethod").eval()) == 0
            output_parm = node.parm("sopoutput")
        except Exception:
            constructed_path = False
            output_parm = None
        if not constructed_path or output_parm is None:
            return super()._verification_patterns(node, job, patterns)
        frame_range = frame_range_for_job(job, self.hou) or self._node_frame_range(node)
        if frame_range is None:
            return patterns
        start, end, step = (int(value) for value in frame_range)
        try:
            return [
                str(output_parm.evalAsStringAtFrame(frame))
                for frame in frame_values(start, end, step)
            ]
        except Exception:
            return patterns

    @staticmethod
    def _execute_parm(node: Any) -> Any | None:
        # Never use the background execution buttons (executebackground, execute_bg).
        for name in ("execute", "save"):
            try:
                parm = node.parm(name)
            except Exception:
                parm = None
            if parm is not None:
                return parm
        return None
