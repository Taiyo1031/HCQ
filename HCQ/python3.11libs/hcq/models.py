"""Serializable data models used by HCQ."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

from .constants import (
    SCHEMA_QUEUE_TEMPLATE,
    SCHEMA_RUN_LIST,
    SCHEMA_RUN_RESULT,
    SCHEMA_RUN_STATUS,
    SCHEMA_VERSION,
    VERSION,
)
from .utils import new_id, new_session_id, now_iso


@dataclass
class CpuSetting:
    mode: str = "current"
    value: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None, default: str = "current") -> "CpuSetting":
        value = value or {}
        return cls(mode=str(value.get("mode", default)), value=value.get("value"))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"mode": self.mode}
        if self.value is not None:
            result["value"] = int(self.value)
        return result


@dataclass
class FrameRange:
    mode: str = "node"
    start: int | None = None
    end: int | None = None
    step: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "FrameRange":
        value = value or {}
        return cls(
            mode=str(value.get("mode", "node")),
            start=value.get("start"),
            end=value.get("end"),
            step=int(value.get("step", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"mode": self.mode}
        if self.mode == "custom":
            result.update({"start": self.start, "end": self.end, "step": self.step})
        return result


@dataclass
class Job:
    id: str = field(default_factory=lambda: new_id("job"))
    order: int = 1
    enabled: bool = True
    display_name: str = "Untitled Job"
    node_path: str = ""
    node_type: str = ""
    action: str = "auto_detect"
    frame_range: FrameRange = field(default_factory=FrameRange)
    cpu: CpuSetting = field(default_factory=lambda: CpuSetting("inherit"))
    on_error: str = "stop_queue"
    retry_count: int = 0
    verification: str = "basic"
    notify_on_complete: bool = True
    notify_on_failure: bool = True
    button_parameter: str = ""
    hip_file_mode: str = "queue"
    hip_file: str = ""
    expected_outputs: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Job":
        return cls(
            id=str(value.get("id") or new_id("job")),
            order=int(value.get("order", 1)),
            enabled=bool(value.get("enabled", True)),
            display_name=str(value.get("display_name", "Untitled Job")),
            node_path=str(value.get("node_path", "")),
            node_type=str(value.get("node_type", "")),
            action=str(value.get("action", "auto_detect")),
            frame_range=FrameRange.from_dict(value.get("frame_range")),
            cpu=CpuSetting.from_dict(value.get("cpu"), "inherit"),
            on_error=str(value.get("on_error", "stop_queue")),
            retry_count=int(value.get("retry_count", 0)),
            verification=str(value.get("verification", "basic")),
            notify_on_complete=bool(value.get("notify_on_complete", True)),
            notify_on_failure=bool(value.get("notify_on_failure", True)),
            button_parameter=str(value.get("button_parameter", "")),
            hip_file_mode=str(value.get("hip_file_mode", "queue")),
            hip_file=str(value.get("hip_file", "")),
            expected_outputs=[str(item) for item in value.get("expected_outputs", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["frame_range"] = self.frame_range.to_dict()
        result["cpu"] = self.cpu.to_dict()
        if not self.button_parameter:
            result.pop("button_parameter")
        if self.hip_file_mode == "queue":
            result.pop("hip_file_mode")
            result.pop("hip_file")
        if not self.expected_outputs:
            result.pop("expected_outputs")
        return result


@dataclass
class QueueTemplate:
    id: str = field(default_factory=lambda: new_id("queue"))
    name: str = "Untitled Queue"
    description: str = ""
    group: str = ""
    favorite: bool = False
    hip_file: str = ""
    cpu: CpuSetting = field(default_factory=CpuSetting)
    jobs: list[Job] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QueueTemplate":
        queue = cls(
            id=str(value.get("id") or new_id("queue")),
            name=str(value.get("name", "Untitled Queue")),
            description=str(value.get("description", "")),
            group=str(value.get("group", "")),
            favorite=bool(value.get("favorite", False)),
            hip_file=str(value.get("hip_file", "")),
            cpu=CpuSetting.from_dict(value.get("cpu")),
            jobs=[Job.from_dict(item) for item in value.get("jobs", [])],
            created_at=str(value.get("created_at", now_iso())),
            updated_at=str(value.get("updated_at", now_iso())),
        )
        queue.normalize_order()
        return queue

    def normalize_order(self) -> None:
        for index, job in enumerate(self.jobs, 1):
            job.order = index

    def duplicate(self) -> "QueueTemplate":
        result = copy.deepcopy(self)
        result.id = new_id("queue")
        result.name = f"{self.name} Copy"
        result.created_at = now_iso()
        result.updated_at = result.created_at
        for job in result.jobs:
            job.id = new_id("job")
        return result

    def to_dict(self) -> dict[str, Any]:
        self.normalize_order()
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "group": self.group,
            "favorite": self.favorite,
            "hip_file": self.hip_file,
            "cpu": self.cpu.to_dict(),
            "jobs": [job.to_dict() for job in self.jobs],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class RunList:
    queues: list[QueueTemplate] = field(default_factory=list)
    save_before_running: str = "always"
    create_backup: bool = False
    existing_output_behavior: str = "ask_each"
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunList":
        return cls(
            queues=[QueueTemplate.from_dict(item) for item in value.get("queues", [])],
            save_before_running=str(value.get("save_before_running", "always")),
            create_backup=bool(value.get("create_backup", False)),
            existing_output_behavior=str(value.get("existing_output_behavior", "ask_each")),
            created_at=str(value.get("created_at", now_iso())),
        )

    def snapshot(self) -> "RunList":
        return copy.deepcopy(self)

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_RUN_LIST,
            "schema_version": SCHEMA_VERSION,
            "hcq_version": VERSION,
            "created_at": self.created_at,
            "save_before_running": self.save_before_running,
            "create_backup": self.create_backup,
            "existing_output_behavior": self.existing_output_behavior,
            "queues": [queue.to_dict() for queue in self.queues],
        }


@dataclass
class JobResult:
    job_id: str
    display_name: str
    node_path: str
    action: str
    state: str = "waiting"
    started_at: str | None = None
    ended_at: str | None = None
    duration_seconds: float | None = None
    cpu_mode: str = "current"
    cpu_value: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunSession:
    id: str = field(default_factory=new_session_id)
    state: str = "idle"
    hip_file: str = ""
    houdini_version: str = ""
    started_at: str | None = None
    updated_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    duration_seconds: float | None = None
    queues: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[JobResult] = field(default_factory=list)
    current_job_id: str | None = None
    message: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunSession":
        return cls(
            id=str(value.get("session_id") or value.get("id") or new_session_id()),
            state=str(value.get("state", "unknown")),
            hip_file=str(value.get("hip_file", "")),
            houdini_version=str(value.get("houdini_version", "")),
            started_at=value.get("started_at"),
            updated_at=str(value.get("updated_at", now_iso())),
            ended_at=value.get("ended_at"),
            duration_seconds=value.get("duration_seconds"),
            queues=list(value.get("queues", [])),
            jobs=[JobResult(**item) for item in value.get("jobs", [])],
            current_job_id=value.get("current_job_id"),
            message=str(value.get("message", "")),
        )

    def to_document(self, completed: bool = False) -> dict[str, Any]:
        completed_jobs = sum(
            result.state in {"completed", "completed_with_warning", "skipped"} for result in self.jobs
        )
        document = {
            "schema": SCHEMA_RUN_RESULT if completed else SCHEMA_RUN_STATUS,
            "schema_version": SCHEMA_VERSION,
            "hcq_version": VERSION,
            "session_id": self.id,
            "state": self.state,
            "hip_file": self.hip_file,
            "houdini_version": self.houdini_version,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "progress": {"completed_jobs": completed_jobs, "total_jobs": len(self.jobs)},
            "current_job_id": self.current_job_id,
            "message": self.message,
            "queues": self.queues,
            "jobs": [result.to_dict() for result in self.jobs],
        }
        return document


def queue_library_document(queues: list[QueueTemplate], houdini_version: str = "21.0") -> dict[str, Any]:
    return {
        "schema": SCHEMA_QUEUE_TEMPLATE,
        "schema_version": SCHEMA_VERSION,
        "hcq_version": VERSION,
        "houdini_min_version": "21.0",
        "created_with_houdini": houdini_version,
        "queues": [queue.to_dict() for queue in queues],
    }
