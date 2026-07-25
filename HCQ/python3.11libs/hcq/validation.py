"""Validation for public HCQ JSON documents and data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constants import (
    ALLOWED_ACTIONS,
    CPU_MODES,
    ERROR_BEHAVIORS,
    FRAME_RANGE_MODES,
    SCHEMA_QUEUE_TEMPLATE,
    SCHEMA_RUN_LIST,
    SCHEMA_VERSION,
    VERIFICATION_MODES,
)
from .models import Job, QueueTemplate


class ValidationError(ValueError):
    pass


@dataclass
class ValidationIssue:
    severity: str
    code: str
    message: str
    queue_id: str = ""
    job_id: str = ""


def validate_job(job: Job) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not job.id:
        issues.append(ValidationIssue("error", "missing_job_id", "Job ID is required."))
    if not job.node_path.startswith("/"):
        issues.append(
            ValidationIssue("error", "invalid_node_path", "Node path must be absolute.", job_id=job.id)
        )
    if job.action not in ALLOWED_ACTIONS:
        issues.append(
            ValidationIssue(
                "error", "invalid_action", f"Unsupported action: {job.action}", job_id=job.id
            )
        )
    if job.cpu.mode not in CPU_MODES:
        issues.append(
            ValidationIssue(
                "error", "invalid_cpu_mode", f"Unsupported CPU mode: {job.cpu.mode}", job_id=job.id
            )
        )
    if job.cpu.mode in {"threads", "reserve"} and (
        job.cpu.value is None or not isinstance(job.cpu.value, int) or job.cpu.value < 1
    ):
        issues.append(
            ValidationIssue(
                "error", "invalid_cpu_value", "CPU value must be a positive integer.", job_id=job.id
            )
        )
    if job.frame_range.mode not in FRAME_RANGE_MODES:
        issues.append(
            ValidationIssue(
                "error",
                "invalid_frame_mode",
                f"Unsupported frame range mode: {job.frame_range.mode}",
                job_id=job.id,
            )
        )
    if job.frame_range.mode == "custom":
        if job.frame_range.start is None or job.frame_range.end is None:
            issues.append(
                ValidationIssue(
                    "error", "missing_frame_range", "Custom frame range is incomplete.", job_id=job.id
                )
            )
        elif job.frame_range.end < job.frame_range.start or job.frame_range.step < 1:
            issues.append(
                ValidationIssue(
                    "error", "invalid_frame_range", "Custom frame range is invalid.", job_id=job.id
                )
            )
    if job.on_error not in ERROR_BEHAVIORS:
        issues.append(
            ValidationIssue(
                "error",
                "invalid_error_behavior",
                f"Unsupported error behavior: {job.on_error}",
                job_id=job.id,
            )
        )
    if job.retry_count < 0:
        issues.append(
            ValidationIssue(
                "error", "invalid_retry_count", "Retry count cannot be negative.", job_id=job.id
            )
        )
    if job.verification not in VERIFICATION_MODES:
        issues.append(
            ValidationIssue(
                "error",
                "invalid_verification",
                f"Unsupported verification mode: {job.verification}",
                job_id=job.id,
            )
        )
    if job.action == "press_button" and not job.button_parameter:
        issues.append(
            ValidationIssue(
                "error",
                "missing_button_parameter",
                "Button Parameter is required for Press Button jobs.",
                job_id=job.id,
            )
        )
    return issues


def validate_queue(queue: QueueTemplate) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not queue.id:
        issues.append(ValidationIssue("error", "missing_queue_id", "Queue ID is required."))
    if not queue.name.strip():
        issues.append(
            ValidationIssue("error", "missing_queue_name", "Queue name is required.", queue.id)
        )
    seen: set[str] = set()
    for job in queue.jobs:
        if job.id in seen:
            issues.append(
                ValidationIssue(
                    "error", "duplicate_job_id", f"Duplicate Job ID: {job.id}", queue.id, job.id
                )
            )
        seen.add(job.id)
        for issue in validate_job(job):
            issue.queue_id = queue.id
            issues.append(issue)
    return issues


def parse_queue_document(value: Any) -> list[QueueTemplate]:
    if not isinstance(value, dict):
        raise ValidationError("The JSON root must be an object.")
    schema = value.get("schema")
    if schema not in {SCHEMA_QUEUE_TEMPLATE, SCHEMA_RUN_LIST}:
        raise ValidationError(f"Unsupported schema: {schema!r}.")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"Unsupported schema version: {value.get('schema_version')!r}.")
    raw_queues = value.get("queues")
    if not isinstance(raw_queues, list):
        raise ValidationError("The queues field must be an array.")
    queues = [QueueTemplate.from_dict(item) for item in raw_queues]
    queue_ids: set[str] = set()
    job_ids: set[str] = set()
    identity_errors: list[str] = []
    for queue in queues:
        if queue.id in queue_ids:
            identity_errors.append(f"Duplicate Queue ID: {queue.id}")
        queue_ids.add(queue.id)
        for job in queue.jobs:
            if job.id in job_ids:
                identity_errors.append(f"Duplicate Job ID: {job.id}")
            job_ids.add(job.id)
    if identity_errors:
        raise ValidationError("\n".join(identity_errors))
    issues = [issue for queue in queues for issue in validate_queue(queue) if issue.severity == "error"]
    if issues:
        raise ValidationError("\n".join(issue.message for issue in issues))
    return queues
