"""Read-only preflight inspection for an HCQ run list."""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import resolve_adapter
from .cpu import resolve_thread_limit
from .models import Job, QueueTemplate, RunList
from .utils import normalized_path
from .validation import validate_job
from .verification import output_path_is_resolved


@dataclass
class PreflightIssue:
    severity: str
    code: str
    message: str
    queue_id: str = ""
    job_id: str = ""
    choices: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_decision(self) -> bool:
        return bool(self.choices)

    @property
    def check(self) -> str:
        return self.code.replace("_", " ").title()


@dataclass
class PreflightReport:
    issues: list[PreflightIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def decisions(self) -> list[PreflightIssue]:
        return [issue for issue in self.issues if issue.requires_decision]

    @property
    def can_run(self) -> bool:
        return not self.errors

    def __iter__(self):
        return iter(self.issues)

    def __len__(self) -> int:
        return len(self.issues)


class PreflightChecker:
    """Inspect Houdini state, nodes, ranges, CPU settings, and output targets."""

    def __init__(
        self,
        hou_module: Any,
        *,
        available_threads: int | None = None,
        minimum_free_bytes: int = 1024 * 1024,
    ) -> None:
        self.hou = hou_module
        self.available_threads = available_threads or (os.cpu_count() or 1)
        self.minimum_free_bytes = minimum_free_bytes

    def check(self, run_list: RunList, *, execution_lock_held: bool = True) -> PreflightReport:
        report = PreflightReport()
        self._check_environment(report)
        if not execution_lock_held:
            report.issues.append(
                PreflightIssue(
                    "error",
                    "execution_lock",
                    "The HCQ execution lock is not held.",
                )
            )

        current_hip = self._current_hip()
        output_owners: dict[str, tuple[str, str]] = {}
        for queue in run_list.queues:
            self._check_queue_hip(queue, current_hip, report)
            for job in sorted(queue.jobs, key=lambda item: item.order):
                if not job.enabled:
                    continue
                self._check_job(
                    queue,
                    job,
                    run_list,
                    current_hip,
                    output_owners,
                    report,
                )
        return report

    def _check_environment(self, report: PreflightReport) -> None:
        try:
            version = tuple(int(value) for value in self.hou.applicationVersion()[:2])
        except Exception:
            version = (0, 0)
        if version < (21, 0):
            report.issues.append(
                PreflightIssue("error", "houdini_version", "HCQ requires Houdini 21.0 or later.")
            )
        try:
            ui_available = bool(self.hou.isUIAvailable())
        except Exception:
            ui_available = True
        if not ui_available:
            report.issues.append(
                PreflightIssue(
                    "error",
                    "ui_unavailable",
                    "HCQ Queue Runner requires an interactive Houdini session.",
                )
            )
        if os.name != "nt":
            report.issues.append(
                PreflightIssue("error", "unsupported_platform", "HCQ supports Windows only.")
            )

    def _check_queue_hip(
        self, queue: QueueTemplate, current_hip: str, report: PreflightReport
    ) -> None:
        if not queue.hip_file:
            return
        expected = self._expand(queue.hip_file)
        if current_hip and normalized_path(expected) != normalized_path(current_hip):
            report.issues.append(
                PreflightIssue(
                    "warning",
                    "hip_mismatch",
                    f'Queue "{queue.name}" targets a different HIP file: {expected}',
                    queue_id=queue.id,
                    choices=("continue", "stop"),
                    context={"expected": expected, "actual": current_hip},
                )
            )

    def _check_job(
        self,
        queue: QueueTemplate,
        job: Job,
        run_list: RunList,
        current_hip: str,
        output_owners: dict[str, tuple[str, str]],
        report: PreflightReport,
    ) -> None:
        for issue in validate_job(job):
            report.issues.append(
                PreflightIssue(
                    issue.severity,
                    issue.code,
                    issue.message,
                    queue_id=queue.id,
                    job_id=job.id,
                )
            )
        node = self._node(job.node_path)
        if node is None:
            report.issues.append(
                PreflightIssue(
                    "error",
                    "missing_node",
                    f"Node does not exist: {job.node_path}",
                    queue_id=queue.id,
                    job_id=job.id,
                )
            )
            return

        self._check_job_hip(queue, job, current_hip, report)
        self._check_node_type(queue, job, node, report)
        self._check_bypass(queue, job, node, report)
        self._check_cpu(queue, job, report)
        self._check_custom_hda(queue, job, node, report)
        try:
            adapter = resolve_adapter(job.action, node, job, self.hou)
        except ValueError as exc:
            report.issues.append(
                PreflightIssue("error", "adapter", str(exc), queue.id, job.id)
            )
            return
        for message in adapter.validate(node, job):
            report.issues.append(
                PreflightIssue("error", "adapter_validation", message, queue.id, job.id)
            )
        adapter_patterns = list(
            dict.fromkeys(adapter.expected_output_patterns(node, job))
        )
        patterns = list(dict.fromkeys([*job.expected_outputs, *adapter_patterns]))
        self._check_outputs(
            queue,
            job,
            run_list,
            patterns,
            output_owners,
            report,
            output_required=adapter.requires_output(node, job),
            required_patterns=adapter_patterns,
        )

    def _check_job_hip(
        self,
        queue: QueueTemplate,
        job: Job,
        current_hip: str,
        report: PreflightReport,
    ) -> None:
        expected = ""
        if job.hip_file_mode == "specific":
            expected = job.hip_file
        if expected:
            expected = self._expand(expected)
            if current_hip and normalized_path(expected) != normalized_path(current_hip):
                report.issues.append(
                    PreflightIssue(
                        "warning",
                        "job_hip_mismatch",
                        f'Job "{job.display_name}" targets a different HIP file: {expected}',
                        queue.id,
                        job.id,
                        ("continue", "skip", "stop"),
                        {"expected": expected, "actual": current_hip},
                    )
                )

    def _check_node_type(
        self,
        queue: QueueTemplate,
        job: Job,
        node: Any,
        report: PreflightReport,
    ) -> None:
        if not job.node_type:
            return
        try:
            actual = str(node.type().nameWithCategory())
        except Exception:
            try:
                actual = str(node.type().name())
            except Exception:
                return
        if actual not in {job.node_type, job.node_type.split("/")[-1]}:
            report.issues.append(
                PreflightIssue(
                    "warning",
                    "node_type_mismatch",
                    f"Node type changed from {job.node_type} to {actual}.",
                    queue.id,
                    job.id,
                )
            )

    def _check_bypass(
        self,
        queue: QueueTemplate,
        job: Job,
        node: Any,
        report: PreflightReport,
    ) -> None:
        try:
            bypassed = bool(node.isBypassed())
        except Exception:
            bypassed = False
        if bypassed:
            report.issues.append(
                PreflightIssue(
                    "warning",
                    "node_bypassed",
                    f"Node is bypassed: {job.node_path}",
                    queue.id,
                    job.id,
                    ("continue", "skip", "stop"),
                )
            )

    def _check_cpu(
        self, queue: QueueTemplate, job: Job, report: PreflightReport
    ) -> None:
        setting = queue.cpu if job.cpu.mode == "inherit" else job.cpu
        try:
            resolve_thread_limit(setting, self.available_threads)
        except ValueError as exc:
            report.issues.append(
                PreflightIssue("error", "cpu", str(exc), queue.id, job.id)
            )
            return
        if setting.mode == "threads" and setting.value and setting.value > self.available_threads:
            report.issues.append(
                PreflightIssue(
                    "warning",
                    "cpu_clamped",
                    (
                        f"Requested {setting.value} threads, but only "
                        f"{self.available_threads} are available."
                    ),
                    queue.id,
                    job.id,
                )
            )
        if (
            setting.mode == "reserve"
            and setting.value
            and setting.value >= self.available_threads
        ):
            report.issues.append(
                PreflightIssue(
                    "warning",
                    "cpu_reserve_clamped",
                    (
                        f"Requested leaving {setting.value} logical threads free, "
                        f"but only {self.available_threads} are available. HCQ "
                        "will keep one logical thread available to Houdini."
                    ),
                    queue.id,
                    job.id,
                )
            )

    def _check_custom_hda(
        self,
        queue: QueueTemplate,
        job: Job,
        node: Any,
        report: PreflightReport,
    ) -> None:
        try:
            definition = node.type().definition()
            library_path = str(definition.libraryFilePath()) if definition else ""
        except Exception:
            return
        if not library_path:
            return
        hfs = self._expand("$HFS")
        if hfs and normalized_path(library_path).startswith(normalized_path(hfs)):
            return
        report.issues.append(
            PreflightIssue(
                "warning",
                "custom_hda",
                f"Custom HDA actions may not run unattended: {job.node_path}",
                queue.id,
                job.id,
            )
        )

    def _check_outputs(
        self,
        queue: QueueTemplate,
        job: Job,
        run_list: RunList,
        patterns: list[str],
        output_owners: dict[str, tuple[str, str]],
        report: PreflightReport,
        *,
        output_required: bool = False,
        required_patterns: list[str] | None = None,
    ) -> None:
        required_patterns = patterns if required_patterns is None else required_patterns
        if output_required and not any(
            str(pattern).strip() for pattern in required_patterns
        ):
            report.issues.append(
                PreflightIssue(
                    "warning",
                    "unresolved_output_path",
                    "The File Cache output path is empty or unresolved.",
                    queue.id,
                    job.id,
                )
            )
            if not any(str(pattern).strip() for pattern in patterns):
                return

        for pattern in patterns:
            expanded = self._expand(pattern)
            if not output_path_is_resolved(expanded):
                report.issues.append(
                    PreflightIssue(
                        "warning",
                        "unresolved_output_path",
                        f"Output path is empty or unresolved: {pattern}",
                        queue.id,
                        job.id,
                    )
                )
                continue
            owner_key = os.path.normcase(expanded)
            if owner_key in output_owners:
                previous_queue, previous_job = output_owners[owner_key]
                report.issues.append(
                    PreflightIssue(
                        "error",
                        "duplicate_output",
                        f"Multiple jobs target the same output pattern: {expanded}",
                        queue.id,
                        job.id,
                        context={
                            "previous_queue_id": previous_queue,
                            "previous_job_id": previous_job,
                            "path": expanded,
                        },
                    )
                )
            else:
                output_owners[owner_key] = (queue.id, job.id)

            filesystem_path = self._representative_path(expanded)
            parent = filesystem_path.parent
            existing_parent = parent
            while not existing_parent.exists() and existing_parent != existing_parent.parent:
                existing_parent = existing_parent.parent
            if not parent.exists():
                report.issues.append(
                    PreflightIssue(
                        "warning",
                        "missing_output_directory",
                        f"Output directory does not exist: {parent}",
                        queue.id,
                        job.id,
                        context={
                            "path": str(parent),
                            "existing_ancestor": (
                                str(existing_parent) if existing_parent.exists() else ""
                            ),
                        },
                    )
                )
            if existing_parent.exists() and not os.access(existing_parent, os.W_OK):
                report.issues.append(
                    PreflightIssue(
                        "error",
                        "output_not_writable",
                        f"Output location is not writable: {existing_parent}",
                        queue.id,
                        job.id,
                    )
                )
            try:
                free = shutil.disk_usage(existing_parent).free
            except OSError:
                free = self.minimum_free_bytes
            if free < self.minimum_free_bytes:
                report.issues.append(
                    PreflightIssue(
                        "error",
                        "insufficient_disk_space",
                        f"Output location has insufficient free space: {existing_parent}",
                        queue.id,
                        job.id,
                    )
                )

            matches = glob.glob(self._glob_pattern(expanded))
            if not matches and not any(token in expanded for token in ("*", "?", "[")):
                matches = [expanded] if Path(expanded).exists() else []
            if not matches and parent.exists():
                report.issues.append(
                    PreflightIssue(
                        "warning",
                        "output_not_created",
                        f"Output does not exist yet: {expanded}",
                        queue.id,
                        job.id,
                        context={"path": expanded},
                    )
                )
            if matches:
                behavior = run_list.existing_output_behavior
                choices: tuple[str, ...] = ()
                severity = "warning"
                if behavior == "ask_each":
                    choices = ("overwrite", "skip", "stop")
                elif behavior == "stop":
                    severity = "error"
                elif behavior == "skip":
                    choices = ("skip",)
                report.issues.append(
                    PreflightIssue(
                        severity,
                        "existing_output",
                        f"Existing output was found for: {expanded}",
                        queue.id,
                        job.id,
                        choices,
                        {"pattern": expanded, "matches": matches[:20], "behavior": behavior},
                    )
                )

    def _current_hip(self) -> str:
        try:
            if self.hou.hipFile.isNewFile():
                return ""
        except Exception:
            pass
        try:
            return str(self.hou.hipFile.path())
        except Exception:
            return ""

    def _node(self, path: str) -> Any | None:
        try:
            return self.hou.node(path)
        except Exception:
            return None

    def _expand(self, value: str) -> str:
        tokens = {
            "$F4": "__HCQ_F4__",
            "$F3": "__HCQ_F3__",
            "$F2": "__HCQ_F2__",
            "$F": "__HCQ_F__",
            "<F4>": "__HCQ_AF4__",
            "<F3>": "__HCQ_AF3__",
            "<F2>": "__HCQ_AF2__",
            "<F>": "__HCQ_AF__",
        }
        protected = value
        for token, marker in tokens.items():
            protected = protected.replace(token, marker)
        try:
            protected = str(self.hou.expandString(protected))
        except Exception:
            protected = os.path.expandvars(protected)
        for token, marker in tokens.items():
            protected = protected.replace(marker, token)
        return protected

    @staticmethod
    def _glob_pattern(value: str) -> str:
        result = value
        for token in ("$F4", "$F3", "$F2", "$F", "<F4>", "<F3>", "<F2>", "<F>"):
            result = result.replace(token, "*")
        return result

    @classmethod
    def _representative_path(cls, value: str) -> Path:
        representative = cls._glob_pattern(value).replace("*", "1").replace("?", "1")
        return Path(representative)
