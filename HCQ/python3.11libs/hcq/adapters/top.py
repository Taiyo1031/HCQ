"""Blocking TOP/PDG cook adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import Job
from .base import ActionAdapter, AdapterResult, node_category_name


class TopAdapter(ActionAdapter):
    action = "top_cook"

    def can_handle(self, node: Any, job: Job | None = None) -> bool:
        return node_category_name(node).lower() in {"top", "task"} or callable(
            getattr(node, "cookWorkItems", None)
        )

    def validate(self, node: Any, job: Job) -> list[str]:
        errors = super().validate(node, job)
        if node is not None and not callable(getattr(node, "cookWorkItems", None)):
            errors.append("TOP Cook requires a node that supports cookWorkItems().")
        return errors

    def _execute_native(self, node: Any, job: Job) -> Any:
        return node.cookWorkItems(block=True)

    def execute(self, node: Any, job: Job, started_at: datetime) -> AdapterResult:
        result = super().execute(node, job, started_at)
        try:
            pdg_node = node.getPDGNode()
        except Exception:
            pdg_node = None
        if pdg_node is not None:
            has_errors = self._value(pdg_node, "hasErrors", False)
            cook_error = self._value(pdg_node, "cookError", "")
            cook_warning = self._value(pdg_node, "cookWarning", "")
            if cook_warning:
                warning = str(cook_warning)
                if warning not in result.warnings:
                    result.warnings.append(warning)
            if has_errors or cook_error:
                error = str(cook_error or "The TOP/PDG cook reported failed work items.")
                if error not in result.errors:
                    result.errors.append(error)
                result.success = False
        return result

    def request_cancel(self, node: Any) -> bool:
        cancel = getattr(node, "cancelCook", None)
        if not callable(cancel):
            return False
        try:
            cancel()
        except TypeError:
            cancel(True)
        return True

    @staticmethod
    def _value(value: Any, attribute: str, default: Any) -> Any:
        try:
            result = getattr(value, attribute)
            return result() if callable(result) else result
        except Exception:
            return default
