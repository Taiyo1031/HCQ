"""Restricted Houdini button parameter adapter."""

from __future__ import annotations

from typing import Any

from ..models import Job
from .base import ActionAdapter, TemporaryNodeFrameRange


class ButtonAdapter(ActionAdapter):
    action = "press_button"

    def can_handle(self, node: Any, job: Job | None = None) -> bool:
        return node is not None and job is not None and self._button_parm(node, job) is not None

    def validate(self, node: Any, job: Job) -> list[str]:
        errors = super().validate(node, job)
        if not job.button_parameter:
            errors.append("Button Parameter is required.")
        elif node is not None and self._button_parm(node, job) is None:
            errors.append(
                f"Parameter is missing or is not a button: {job.button_parameter}"
            )
        return errors

    def _execute_native(self, node: Any, job: Job) -> Any:
        parm = self._button_parm(node, job)
        if parm is None:
            raise RuntimeError(
                f"Parameter is missing or is not a button: {job.button_parameter}"
            )
        with TemporaryNodeFrameRange(node, job):
            return parm.pressButton()

    def _button_parm(self, node: Any, job: Job) -> Any | None:
        try:
            parm = node.parm(job.button_parameter)
        except Exception:
            return None
        if parm is None or not callable(getattr(parm, "pressButton", None)):
            return None
        try:
            template_type = parm.parmTemplate().type()
            button_type = getattr(getattr(self.hou, "parmTemplateType", None), "Button", None)
            if button_type is not None and template_type != button_type:
                return None
            if button_type is None and str(template_type).lower().split(".")[-1] != "button":
                return None
        except Exception:
            # Lightweight HOM fakes can expose pressButton without the template API.
            pass
        return parm
