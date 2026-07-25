"""Sequential foreground queue execution in the current Houdini session."""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime
from typing import Any, Callable

from .adapters import ActionAdapter, resolve_adapter
from .cpu import TemporaryThreadLimit
from .execution_lock import ExecutionLock, ExecutionLockError
from .models import Job, JobResult, QueueTemplate, RunList, RunSession
from .preflight import PreflightChecker, PreflightIssue, PreflightReport
from .utils import deduplicated, now_iso


DecisionHandler = Callable[[str, dict[str, Any]], Any]
StateCallback = Callable[[RunSession], None]
EventPump = Callable[[], None]


class QueueRunError(RuntimeError):
    pass


class _InProcessLock:
    _guard = threading.Lock()
    _owned = False

    def acquire(self) -> None:
        with self._guard:
            if self.__class__._owned:
                raise ExecutionLockError("Another HCQ run session is active.")
            self.__class__._owned = True

    def release(self) -> None:
        with self._guard:
            self.__class__._owned = False


class QueueRunner:
    """Own one sequential Run Session and expose cooperative pause/cancel controls."""

    def __init__(
        self,
        hou_module: Any | None = None,
        storage: Any | None = None,
        settings: dict[str, Any] | None = None,
        notifications: Any | None = None,
        decision_handler: DecisionHandler | None = None,
        state_callback: StateCallback | None = None,
        *,
        execution_lock: Any | None = None,
        monitor: Any | None = None,
        notifier: Any | None = None,
        event_pump: EventPump | None = None,
        preflight_checker: PreflightChecker | None = None,
        confirm_before_run: bool = False,
    ) -> None:
        if hou_module is None:
            try:
                import hou as hou_module  # type: ignore[no-redef]
            except ImportError as exc:
                raise RuntimeError("QueueRunner requires Houdini or an injected HOM facade.") from exc
        self.hou = hou_module
        self.storage = storage
        self.settings = settings or {}
        if execution_lock is not None:
            self.execution_lock = execution_lock
        elif storage is not None:
            self.execution_lock = ExecutionLock(storage.paths.lock_file)
        else:
            self.execution_lock = _InProcessLock()
        self.monitor = monitor
        self.notifier = notifications if notifications is not None else notifier
        self.decision_handler = decision_handler
        self.state_callback = state_callback
        self.event_pump = event_pump or self._default_event_pump
        self.preflight_checker = preflight_checker or PreflightChecker(self.hou)
        self.confirm_before_run = confirm_before_run

        self.session: RunSession | None = None
        self._running = False
        self._pause_requested = False
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._cancel_requested = False
        self._current_adapter: ActionAdapter | None = None
        self._current_node: Any | None = None
        self._preflight_decisions: dict[tuple[str, str, str, str], Any] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active(self) -> bool:
        """Compatibility alias used by the manager and panel state binding."""
        return self._running

    @property
    def state(self) -> str:
        return self.session.state if self.session is not None else "idle"

    @property
    def pause_requested(self) -> bool:
        return self._pause_requested

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    def request_pause(self) -> None:
        if not self._running:
            return
        self._pause_requested = True
        self._resume_event.clear()
        if self.session is not None:
            self.session.state = "pause_requested"
            self.session.message = "Pause requested after the current job."
            self._persist_status()

    def resume(self) -> None:
        self._pause_requested = False
        self._resume_event.set()
        if self.session is not None and self._running:
            self.session.state = "running"
            self.session.message = ""
            self._persist_status()

    def request_cancel(self) -> bool:
        if not self._running:
            return False
        self._cancel_requested = True
        self._resume_event.set()
        requested = False
        if self._current_adapter is not None and self._current_node is not None:
            try:
                requested = self._current_adapter.request_cancel(self._current_node)
            except Exception:
                requested = False
        if self.session is not None:
            self.session.state = "cancel_requested"
            self.session.message = (
                "Native cancellation requested."
                if requested
                else "Cancellation requested. Use Houdini's Esc key during a blocking cook."
            )
            self._persist_status()
        return requested

    def preflight(self, run_list: RunList) -> PreflightReport:
        """Run a read-only preflight without acquiring or changing run state."""
        return self.preflight_checker.check(run_list.snapshot(), execution_lock_held=True)

    def start(self, run_list: RunList) -> RunSession:
        """Manager-facing name for synchronous foreground queue execution."""
        return self.run(run_list)

    def run(self, run_list: RunList) -> RunSession:
        if self._running:
            raise QueueRunError("This QueueRunner already has an active Run Session.")
        snapshot = run_list.snapshot()
        snapshot.save_before_running = str(
            self.settings.get("save_before_running", snapshot.save_before_running)
        )
        snapshot.create_backup = bool(
            self.settings.get("create_backup_before_saving", snapshot.create_backup)
        )
        snapshot.existing_output_behavior = str(
            self.settings.get(
                "existing_output_behavior",
                snapshot.existing_output_behavior,
            )
        )
        self.session = self._new_session(snapshot)
        self._running = True
        self._pause_requested = False
        self._cancel_requested = False
        self._preflight_decisions.clear()
        self._resume_event.set()
        lock_acquired = False
        monitor_suspended = False
        try:
            self.execution_lock.acquire()
            lock_acquired = True
            self._set_session_state("preparing")

            report = self.preflight_checker.check(snapshot, execution_lock_held=True)
            skipped_jobs = self._resolve_preflight(report)
            if report.errors:
                raise QueueRunError(self._format_preflight_errors(report))
            self._save_hip(snapshot)

            # Saving can change $HIP-dependent paths, so validate once more.
            saved_report = self.preflight_checker.check(snapshot, execution_lock_held=True)
            skipped_jobs.update(self._resolve_preflight(saved_report, path_recheck=True))
            if saved_report.errors:
                raise QueueRunError(self._format_preflight_errors(saved_report))
            if self.confirm_before_run:
                decision = self._decide(
                    "confirm_run",
                    {
                        "session": self.session,
                        "run_list": snapshot,
                        "preflight": saved_report,
                    },
                    "cancel",
                )
                if decision not in {"run", "continue", True}:
                    raise QueueRunError("Run confirmation was cancelled.")

            self._suspend_monitor()
            monitor_suspended = True
            self._set_session_state("running")
            self._execute_queues(snapshot, skipped_jobs)
            if self._cancel_requested:
                self._set_session_state("cancelled", "The queue was cancelled.", terminal=True)
            elif self.session.state != "failed":
                self._set_session_state("completed", "The queue completed.", terminal=True)
        except ExecutionLockError as exc:
            self._set_session_state("failed", str(exc), terminal=True)
        except QueueRunError as exc:
            self._set_session_state("failed", str(exc), terminal=True)
        except BaseException as exc:
            self._set_session_state(
                "failed",
                f"Unhandled queue error: {str(exc) or exc.__class__.__name__}",
                terminal=True,
            )
        finally:
            self._current_adapter = None
            self._current_node = None
            if self.session is not None:
                try:
                    self._archive_terminal_session()
                except BaseException as exc:
                    self.session.state = "failed"
                    self.session.message = (
                        "The queue finished, but History could not be finalized: "
                        f"{str(exc) or exc.__class__.__name__}"
                    )
                    try:
                        self._persist_status()
                    except BaseException:
                        pass
            if monitor_suspended:
                self._resume_monitor()
            if lock_acquired:
                self.execution_lock.release()
            self._running = False
            self._resume_event.set()
            if self.session is not None:
                self._notify_queue()
        return self.session

    def _new_session(self, run_list: RunList) -> RunSession:
        try:
            hip_file = "" if self.hou.hipFile.isNewFile() else str(self.hou.hipFile.path())
        except Exception:
            hip_file = ""
        try:
            version = str(self.hou.applicationVersionString())
        except Exception:
            try:
                version = ".".join(str(value) for value in self.hou.applicationVersion())
            except Exception:
                version = ""
        session = RunSession(
            state="idle",
            hip_file=hip_file,
            houdini_version=version,
            started_at=now_iso(),
            # Store the immutable execution snapshot for recovery and history re-runs.
            queues=[queue.to_dict() for queue in run_list.queues],
        )
        for queue in run_list.queues:
            for job in sorted(queue.jobs, key=lambda item: item.order):
                session.jobs.append(
                    JobResult(
                        job_id=job.id,
                        display_name=job.display_name,
                        node_path=job.node_path,
                        action=job.action,
                        state="waiting" if job.enabled else "skipped",
                    )
                )
        return session

    def _execute_queues(self, run_list: RunList, skipped_jobs: set[str]) -> None:
        assert self.session is not None
        results = iter(self.session.jobs)
        for queue in run_list.queues:
            for job in sorted(queue.jobs, key=lambda item: item.order):
                result = next(results)
                if not job.enabled or job.id in skipped_jobs:
                    result.state = "skipped"
                    result.ended_at = now_iso()
                    self._persist_status()
                    continue
                if self._cancel_requested:
                    return
                self._wait_if_paused()
                if self._cancel_requested:
                    return
                should_continue = self._execute_job(queue, job, result)
                self.event_pump()
                if not should_continue:
                    return

    def _execute_job(
        self, queue: QueueTemplate, job: Job, result: JobResult
    ) -> bool:
        assert self.session is not None
        node = self.hou.node(job.node_path)
        if node is None:
            result.state = "failed"
            result.errors = [f"Node does not exist: {job.node_path}"]
            return self._handle_failed_job(job, result)
        try:
            adapter = resolve_adapter(job.action, node, job, self.hou)
        except ValueError as exc:
            result.state = "failed"
            result.errors = [str(exc)]
            return self._handle_failed_job(job, result)

        result.action = adapter.action
        try:
            result.output_paths = list(adapter.planned_output_paths(node, job))
        except BaseException:
            result.output_paths = list(job.expected_outputs)
        setting = copy.deepcopy(queue.cpu if job.cpu.mode == "inherit" else job.cpu)
        result.cpu_mode = setting.mode
        self._current_adapter = adapter
        self._current_node = node
        total_started = time.monotonic()
        result.started_at = now_iso()
        self.session.current_job_id = job.id
        attempt = 0
        retry_limit = max(0, int(job.retry_count))
        while True:
            attempt += 1
            result.attempts = attempt
            result.state = "running"
            result.errors.clear()
            result.warnings.clear()
            self._persist_status()
            if self._cancel_requested:
                result.state = "cancelled"
                break
            started_at = datetime.now().astimezone()
            try:
                with TemporaryThreadLimit(self.hou, setting) as applied:
                    result.cpu_value = (
                        int(self.hou.maxThreads()) if applied is None else int(applied)
                    )
                    adapter_result = adapter.execute(node, job, started_at)
            except BaseException as exc:
                adapter_result = None
                result.errors = [str(exc) or exc.__class__.__name__]
            if adapter_result is not None:
                result.errors = list(adapter_result.errors)
                result.warnings = list(adapter_result.warnings)
                try:
                    post_run_paths = list(adapter.planned_output_paths(node, job))
                except BaseException:
                    post_run_paths = []
                result.output_paths = deduplicated(
                    [
                        *result.output_paths,
                        *post_run_paths,
                        *adapter_result.output_paths,
                    ]
                )
                if adapter_result.cancelled:
                    result.state = "cancelled"
                    self._cancel_requested = True
                elif adapter_result.success:
                    result.state = (
                        "completed_with_warning" if result.warnings else "completed"
                    )
                else:
                    result.state = "failed"
            else:
                result.state = "failed"

            if result.state in {"completed", "completed_with_warning", "cancelled"}:
                break
            if attempt <= retry_limit:
                continue
            decision = self._failure_decision(job, result)
            if decision == "retry":
                continue
            if decision == "skip":
                result.state = "skipped"
            break

        result.ended_at = now_iso()
        result.duration_seconds = round(time.monotonic() - total_started, 3)
        self.session.current_job_id = None
        self._persist_status()
        self._notify_job(job, result)
        self._current_adapter = None
        self._current_node = None
        if result.state == "cancelled":
            return False
        if result.state == "failed":
            self._set_session_state(
                "failed",
                f'Job failed: "{job.display_name}"',
                terminal=True,
            )
            return False
        return True

    def _handle_failed_job(self, job: Job, result: JobResult) -> bool:
        assert self.session is not None
        result.started_at = result.started_at or now_iso()
        result.ended_at = now_iso()
        result.attempts = max(1, result.attempts)
        decision = self._failure_decision(job, result)
        if decision == "skip":
            result.state = "skipped"
            self._persist_status()
            return True
        self._set_session_state("failed", f'Job failed: "{job.display_name}"', terminal=True)
        return False

    def _failure_decision(self, job: Job, result: JobResult) -> str:
        if job.on_error == "skip_continue":
            return "skip"
        if job.on_error == "wait_for_user":
            decision = self._decide(
                "job_error",
                {
                    "session": self.session,
                    "job": job,
                    "result": result,
                    "choices": ("retry", "skip", "stop"),
                },
                "stop",
            )
            return str(decision) if decision in {"retry", "skip", "stop"} else "stop"
        return "stop"

    def _resolve_preflight(
        self, report: PreflightReport, *, path_recheck: bool = False
    ) -> set[str]:
        skipped_jobs: set[str] = set()
        for issue in report.decisions:
            context_key = str(
                issue.context.get("path")
                or issue.context.get("pattern")
                or issue.context.get("expected")
                or ""
            )
            key = (issue.code, issue.queue_id, issue.job_id, context_key)
            if key in self._preflight_decisions:
                decision = self._preflight_decisions[key]
            else:
                default = issue.choices[-1] if issue.choices else "stop"
                decision = self._decide(
                    "preflight_issue",
                    {
                        "session": self.session,
                        "issue": issue,
                        "path_recheck": path_recheck,
                        "choices": issue.choices,
                    },
                    default,
                )
                self._preflight_decisions[key] = decision
            if decision in {"stop", "cancel", False, None}:
                report.issues.append(
                    PreflightIssue(
                        "error",
                        "preflight_cancelled",
                        f"Preflight stopped: {issue.message}",
                        issue.queue_id,
                        issue.job_id,
                    )
                )
            elif decision == "skip" and issue.job_id:
                skipped_jobs.add(issue.job_id)
        return skipped_jobs

    def _save_hip(self, run_list: RunList) -> None:
        behavior = run_list.save_before_running
        if behavior == "never":
            return
        if behavior == "ask":
            decision = self._decide(
                "save_hip",
                {
                    "session": self.session,
                    "choices": ("save", "dont_save", "cancel"),
                },
                "cancel",
            )
            if decision == "dont_save":
                return
            if decision != "save":
                raise QueueRunError("HIP save was cancelled.")

        try:
            is_new = bool(self.hou.hipFile.isNewFile())
        except Exception:
            is_new = False
        if is_new:
            destination = self._decide(
                "save_hip_as",
                {"session": self.session, "choices": ("path", "cancel")},
                None,
            )
            if not isinstance(destination, str) or not destination:
                raise QueueRunError("A new HIP file must be saved before running.")
            try:
                self.hou.hipFile.save(file_name=destination)
            except Exception as exc:
                raise QueueRunError(f"Could not save the HIP file: {exc}") from exc
        else:
            try:
                if run_list.create_backup:
                    self.hou.hipFile.saveAndBackup()
                else:
                    self.hou.hipFile.save()
            except Exception as exc:
                raise QueueRunError(f"Could not save the HIP file: {exc}") from exc
        try:
            assert self.session is not None
            self.session.hip_file = str(self.hou.hipFile.path())
            self._persist_status()
        except Exception:
            pass

    def _wait_if_paused(self) -> None:
        if not self._pause_requested:
            return
        self._set_session_state("paused", "Paused after the current job.")
        while self._pause_requested and not self._cancel_requested:
            self.event_pump()
            self._resume_event.wait(0.05)
        if not self._cancel_requested:
            self._set_session_state("running")

    def _set_session_state(
        self, state: str, message: str = "", *, terminal: bool = False
    ) -> None:
        if self.session is None:
            return
        self.session.state = state
        self.session.message = message
        if terminal:
            self.session.ended_at = now_iso()
            if self.session.started_at:
                try:
                    started = datetime.fromisoformat(self.session.started_at)
                    ended = datetime.fromisoformat(self.session.ended_at)
                    self.session.duration_seconds = round(
                        max(0.0, (ended - started).total_seconds()), 3
                    )
                except (TypeError, ValueError):
                    self.session.duration_seconds = round(
                        sum(result.duration_seconds or 0.0 for result in self.session.jobs),
                        3,
                    )
            self.session.current_job_id = None
        self._persist_status()

    def _persist_status(self) -> None:
        if self.session is None:
            return
        self.session.updated_at = now_iso()
        if self.storage is not None:
            self.storage.save_active_session(self.session)
        if self.state_callback is not None:
            self.state_callback(self.session)
        self.event_pump()

    def _archive_terminal_session(self) -> None:
        if self.session is None or self.storage is None:
            return
        if self.session.state in {"completed", "failed", "cancelled"}:
            self.storage.complete_session(self.session)
        else:
            self.storage.save_active_session(self.session)

    def _suspend_monitor(self) -> None:
        if self.monitor is None:
            return
        method = getattr(self.monitor, "suspend_for_queue", None)
        if callable(method):
            method()
            return
        method = getattr(self.monitor, "suspend", None)
        if callable(method):
            method()

    def _resume_monitor(self) -> None:
        if self.monitor is None:
            return
        method = getattr(self.monitor, "resume_after_queue", None)
        if callable(method):
            method()
            return
        resume = getattr(self.monitor, "resume", None)
        if callable(resume):
            try:
                resume(refresh_baselines=True)
            except TypeError:
                refresh = getattr(self.monitor, "refresh_baselines", None)
                if callable(refresh):
                    refresh()
                resume()

    def _notify_job(self, job: Job, result: JobResult) -> None:
        if self.notifier is None:
            return
        should_notify = (
            result.state in {"completed", "completed_with_warning"} and job.notify_on_complete
        ) or (result.state in {"failed", "cancelled"} and job.notify_on_failure)
        if not should_notify:
            return
        method = getattr(self.notifier, "job_finished", None)
        if callable(method):
            method(job, result)
            return
        if result.state == "completed":
            method = getattr(self.notifier, "completed", None)
            title = "Job Complete"
            message = f"{job.display_name} completed."
        elif result.state == "completed_with_warning":
            method = getattr(self.notifier, "warning", None)
            title = "Job Completed with Warnings"
            message = f"{job.display_name} completed with warnings."
        elif result.state == "cancelled":
            method = getattr(self.notifier, "warning", None)
            title = "Job Cancelled"
            message = f"{job.display_name} was cancelled."
        else:
            method = getattr(self.notifier, "error", None)
            title = "Job Failed"
            message = f"{job.display_name} failed."
        if callable(method):
            method(
                title,
                message,
                node_path=job.node_path,
                duration_seconds=result.duration_seconds,
            )

    def _notify_queue(self) -> None:
        if self.notifier is None or self.session is None:
            return
        if not bool(self.settings.get("notify_queue_complete", True)):
            return
        method = getattr(self.notifier, "queue_finished", None)
        if callable(method):
            method(self.session)
            return
        if self.session.state == "completed":
            method = getattr(self.notifier, "completed", None)
            title = "Queue Complete"
            message = "All enabled queue jobs completed."
        elif self.session.state == "cancelled":
            method = getattr(self.notifier, "warning", None)
            title = "Queue Cancelled"
            message = "The queue was cancelled."
        else:
            method = getattr(self.notifier, "error", None)
            title = "Queue Failed"
            message = self.session.message or "The queue stopped after a failure."
        if callable(method):
            method(title, message)

    def _decide(self, kind: str, payload: dict[str, Any], default: Any) -> Any:
        if self.decision_handler is None:
            return default
        try:
            return self.decision_handler(kind, payload)
        except Exception:
            return default

    def _default_event_pump(self) -> None:
        try:
            from PySide6 import QtCore

            QtCore.QCoreApplication.processEvents()
        except Exception:
            pass

    @staticmethod
    def _format_preflight_errors(report: PreflightReport) -> str:
        messages = [issue.message for issue in report.errors]
        return "Preflight failed: " + "; ".join(dict.fromkeys(messages))


__all__ = ["QueueRunError", "QueueRunner"]
