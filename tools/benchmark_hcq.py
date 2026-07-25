"""Benchmark one node operation against the HCQ adapter inside Houdini."""

from __future__ import annotations

import json
import os
import threading
import time
import tracemalloc
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import hou

from hcq.adapters import resolve_adapter
from hcq.models import Job
from hcq.verification import expand_output_patterns


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_memory_bytes() -> int:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        process, ctypes.byref(counters), counters.cb
    ):
        return 0
    return int(counters.WorkingSetSize)


def measure(callback):
    stop = threading.Event()
    memory_samples = [process_memory_bytes()]

    def sample():
        while not stop.wait(0.1):
            memory_samples.append(process_memory_bytes())

    sampler = threading.Thread(target=sample, name="HCQ benchmark sampler", daemon=True)
    sampler.start()
    tracemalloc.start()
    cpu_started = time.process_time()
    started = time.perf_counter()
    try:
        callback()
    finally:
        duration = time.perf_counter() - started
        cpu_seconds = time.process_time() - cpu_started
        stop.set()
        sampler.join(timeout=1.0)
        memory_samples.append(process_memory_bytes())
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    logical_cpus = max(1, os.cpu_count() or 1)
    utilization = 100.0 * cpu_seconds / max(0.001, duration * logical_cpus)
    return {
        "elapsed_seconds": duration,
        "python_peak_bytes": peak,
        "process_peak_working_set_bytes": max(memory_samples),
        "process_cpu_seconds": cpu_seconds,
        "process_cpu_utilization_percent": utilization,
    }


def run(node_path: str, action: str, output_file: str) -> dict:
    node = hou.node(node_path)
    if node is None:
        raise ValueError(f"Node not found: {node_path}")
    job = Job(display_name=node.name(), node_path=node.path(), action=action)
    adapter = resolve_adapter(action, node, job, hou)
    manual = measure(lambda: adapter._execute_native(node, job))
    hcq_result = None

    def execute_hcq():
        nonlocal hcq_result
        hcq_result = adapter.execute(node, job, datetime.now().astimezone())

    hcq_measurement = measure(execute_hcq)
    patterns = adapter.expected_output_patterns(node, job)
    outputs = expand_output_patterns(patterns, hou.expandString)
    files = [Path(path) for path in outputs if Path(path).is_file()]
    result = {
        "houdini_version": hou.applicationVersionString(),
        "node_path": node_path,
        "action": action,
        "manual_equivalent": manual,
        "hcq": hcq_measurement,
        "overhead_percent": (
            100.0
            * (hcq_measurement["elapsed_seconds"] - manual["elapsed_seconds"])
            / max(0.001, manual["elapsed_seconds"])
        ),
        "result_file_count": len(files),
        "result_total_bytes": sum(path.stat().st_size for path in files),
        "warnings": list(getattr(hcq_result, "warnings", [])),
        "errors": list(getattr(hcq_result, "errors", [])),
    }
    Path(output_file).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


# Run from Houdini's Python Source Editor:
# print(run("/obj/geo1/filecache1", "filecache_save_to_disk", "D:/hcq-benchmark.json"))
