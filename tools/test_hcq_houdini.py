"""Houdini 21 integration smoke tests for HCQ.

This script creates only temporary nodes and cache files in a fresh hython
process. It does not save a HIP file.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import hou

from hcq.adapters import (
    ButtonAdapter,
    FileCacheAdapter,
    GenericAdapter,
    RopAdapter,
    TopAdapter,
    resolve_adapter,
)
from hcq.cook_monitor import CookMonitor
from hcq.cpu import TemporaryThreadLimit
from hcq.models import CpuSetting, Job
from hcq.storage import Storage


class SilentNotifications:
    def __init__(self):
        self.items = []

    def completed(self, *args, **kwargs):
        self.items.append(("completed", args, kwargs))

    def warning(self, *args, **kwargs):
        self.items.append(("warning", args, kwargs))

    def error(self, *args, **kwargs):
        self.items.append(("error", args, kwargs))

    def info(self, *args, **kwargs):
        self.items.append(("info", args, kwargs))


def execute_adapter(adapter, node, job):
    result = adapter.execute(node, job, datetime.now().astimezone())
    if not result.success:
        raise AssertionError(f"{adapter.__class__.__name__} failed: {result.errors}")
    return result


def main() -> dict:
    if tuple(hou.applicationVersion()[:2]) < (21, 0):
        raise AssertionError("Houdini 21.0 or later is required.")

    summary = {
        "houdini_version": hou.applicationVersionString(),
        "python_panel_runtime": "PySide6",
        "checks": [],
    }
    with tempfile.TemporaryDirectory(prefix="hcq-houdini-") as temporary:
        temporary_path = Path(temporary)
        storage = Storage(temporary_path / "HCQ", hou.applicationVersionString())

        obj = hou.node("/obj")
        geo = obj.createNode("geo", "hcq_integration_geo")
        for child in geo.children():
            child.destroy()
        box = geo.createNode("box", "source_box")
        null = geo.createNode("null", "generic_cook")
        null.setInput(0, box)

        generic_job = Job(
            display_name="Generic Cook",
            node_path=null.path(),
            action="force_cook",
            verification="none",
        )
        generic = resolve_adapter(generic_job.action, null, generic_job, hou)
        assert isinstance(generic, GenericAdapter)
        execute_adapter(generic, null, generic_job)
        summary["checks"].append("generic_force_cook")

        filecache = geo.createNode("filecache", "foreground_filecache")
        filecache.setInput(0, box)
        filecache.parm("cachedir").set(temporary_path.as_posix())
        filecache.parm("cachename").set("filecache.$F4.bgeo.sc")
        if filecache.parm("trange") is not None:
            filecache.parm("trange").set(0)
        filecache_job = Job(
            display_name="File Cache",
            node_path=filecache.path(),
            action="filecache_save_to_disk",
            verification="basic",
        )
        filecache_adapter = resolve_adapter(
            filecache_job.action, filecache, filecache_job, hou
        )
        assert isinstance(filecache_adapter, FileCacheAdapter)
        filecache_result = execute_adapter(filecache_adapter, filecache, filecache_job)
        if not filecache_result.output_paths:
            raise AssertionError("File Cache produced no verified output.")
        summary["checks"].append("filecache_foreground_save")

        button_job = Job(
            display_name="Reload Cache",
            node_path=filecache.path(),
            action="press_button",
            button_parameter="reload",
            verification="none",
        )
        button_adapter = resolve_adapter(button_job.action, filecache, button_job, hou)
        assert isinstance(button_adapter, ButtonAdapter)
        execute_adapter(button_adapter, filecache, button_job)
        summary["checks"].append("button_parameter")

        out = hou.node("/out")
        rop = out.createNode("geometry", "hcq_geometry_rop")
        rop.parm("soppath").set(box.path())
        rop_output = (temporary_path / "rop.$F4.bgeo.sc").as_posix()
        rop.parm("sopoutput").set(rop_output)
        if rop.parm("trange") is not None:
            rop.parm("trange").set(0)
        rop_job = Job(
            display_name="Geometry ROP",
            node_path=rop.path(),
            action="rop_render",
            verification="basic",
        )
        rop_adapter = resolve_adapter(rop_job.action, rop, rop_job, hou)
        assert isinstance(rop_adapter, RopAdapter)
        rop_result = execute_adapter(rop_adapter, rop, rop_job)
        if not rop_result.output_paths:
            raise AssertionError("ROP produced no verified output.")
        summary["checks"].append("rop_render")

        topnet = obj.createNode("topnet", "hcq_topnet")
        top_node = topnet.createNode("null", "hcq_top_null")
        top_job = Job(
            display_name="TOP Cook",
            node_path=top_node.path(),
            action="top_cook",
            verification="none",
        )
        top_adapter = resolve_adapter(top_job.action, top_node, top_job, hou)
        assert isinstance(top_adapter, TopAdapter)
        execute_adapter(top_adapter, top_node, top_job)
        summary["checks"].append("top_cook")

        previous_threads = hou.maxThreads()
        with TemporaryThreadLimit(hou, CpuSetting("threads", 1)):
            if hou.maxThreads() != 1:
                raise AssertionError("Temporary CPU limit was not applied.")
        if hou.maxThreads() != previous_threads:
            raise AssertionError("Temporary CPU limit was not restored.")
        summary["checks"].append("cpu_restore")

        notifications = SilentNotifications()
        monitor_settings = {
            "monitor_enabled": True,
            "minimum_cook_duration_seconds": 0,
            "suppress_monitor_during_playback": False,
            "merge_rapid_notifications": True,
        }
        monitor = CookMonitor(
            storage,
            monitor_settings,
            notifications,
            hou_module=hou,
        )
        registration = monitor.add_node(null)
        old_path = registration.node_path
        null.setName("generic_cook_renamed")
        if registration.node_path == old_path:
            raise AssertionError("Monitor did not update a renamed node path.")
        monitor.poll_once()
        null.cook(force=True)
        monitor.poll_once()
        monitor.close()
        summary["checks"].append("monitor_registry_and_rename")

        summary["storage_root_created"] = storage.paths.root.exists()
        summary["filecache_outputs"] = len(filecache_result.output_paths)
        summary["rop_outputs"] = len(rop_result.output_paths)

    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
