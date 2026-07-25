"""Adapter selection for HCQ's action allowlist."""

from __future__ import annotations

from typing import Any

from ..models import Job
from .base import ActionAdapter, AdapterResult
from .button import ButtonAdapter
from .filecache import FileCacheAdapter
from .generic import GenericAdapter
from .rop import RopAdapter
from .top import TopAdapter


ADAPTER_TYPES: dict[str, type[ActionAdapter]] = {
    "filecache_save_to_disk": FileCacheAdapter,
    "rop_render": RopAdapter,
    "top_cook": TopAdapter,
    "force_cook": GenericAdapter,
    "press_button": ButtonAdapter,
}


def resolve_adapter(action: str, node: Any, job: Job, hou_module: Any) -> ActionAdapter:
    """Return an explicit adapter or apply the documented auto-detect priority."""
    if action != "auto_detect":
        adapter_type = ADAPTER_TYPES.get(action)
        if adapter_type is None:
            raise ValueError(f"Unsupported action: {action}")
        return adapter_type(hou_module)

    for adapter_type in (FileCacheAdapter, RopAdapter, TopAdapter, GenericAdapter):
        adapter = adapter_type(hou_module)
        if adapter.can_handle(node, job):
            return adapter
    raise ValueError(f"No supported foreground action was detected for: {job.node_path}")


__all__ = [
    "ActionAdapter",
    "AdapterResult",
    "ButtonAdapter",
    "FileCacheAdapter",
    "GenericAdapter",
    "RopAdapter",
    "TopAdapter",
    "resolve_adapter",
]
