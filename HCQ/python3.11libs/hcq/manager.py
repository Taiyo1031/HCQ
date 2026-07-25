"""Application-level coordinator shared by every HCQ panel."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from .cook_monitor import CookMonitor
from .import_export import export_queues, import_queues
from .logging_utils import configure_logging
from .models import QueueTemplate, RunList
from .navigation import HoudiniNavigation
from .notifications import NotificationCenter
from .queue_runner import QueueRunner
from .recovery import RecoveryService
from .storage import Storage, atomic_write_json, default_storage_root
from .utils import new_id, now_iso
from .validation import parse_queue_document

Listener = Callable[[str], None]


class HCQManager:
    """Own persistent state and long-lived Houdini services."""

    def __init__(self, hou_module: Any) -> None:
        self.hou = hou_module
        version = str(hou_module.applicationVersionString())
        self.storage = Storage(default_storage_root(hou_module), version)
        self.logger = configure_logging(self.storage.paths.logs)
        self.settings = self.storage.load_settings()
        self.queues = self.storage.load_queues()
        self.run_list = RunList(
            save_before_running=str(self.settings.get("save_before_running", "always")),
            create_backup=bool(self.settings.get("create_backup_before_saving", False)),
            existing_output_behavior=str(
                self.settings.get("existing_output_behavior", "ask_each")
            ),
        )
        self.navigation = HoudiniNavigation(hou_module)
        self.notifications = NotificationCenter(
            hou_module=hou_module,
            merge_rapid=bool(self.settings.get("merge_rapid_notifications", True)),
            navigation=self.navigation,
        )
        self.monitor = CookMonitor(
            self.storage,
            self.settings,
            self.notifications,
            hou_module=hou_module,
        )
        self.runner = QueueRunner(
            hou_module,
            storage=self.storage,
            settings=self.settings,
            notifications=self.notifications,
            decision_handler=self._decision_handler,
            state_callback=self._runner_state_changed,
            monitor=self.monitor,
            confirm_before_run=False,
        )
        self.recovery = RecoveryService(self.storage)
        self._listeners: list[Listener] = []
        self._hip_callback_registered = False
        self._started = False
        self._monitor_unsubscribe = self.monitor.subscribe(self._monitor_changed)

    @property
    def history(self) -> list[dict[str, Any]]:
        return self.storage.history_documents()

    @property
    def interrupted_sessions(self) -> list[Any]:
        return self.recovery.discover(mark_interrupted=True)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            self.hou.hipFile.addEventCallback(self._hip_event)
            self._hip_callback_registered = True
        except Exception:
            self.logger.exception("Could not register the HIP event callback.")
        self.monitor.start()
        try:
            self.storage.prune_history(int(self.settings.get("history_retention_days", 90)))
        except Exception:
            self.logger.exception("Could not prune run history.")
        interrupted = self.recovery.discover(mark_interrupted=True)
        if interrupted:
            self.notifications.warning(
                "Interrupted Run Found",
                f"{len(interrupted)} interrupted HCQ run session(s) require attention.",
            )
        self.notify_changed("all")
        self.logger.info("HCQ %s started in Houdini %s.", "1.0.0", self.hou.applicationVersionString())

    def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        try:
            self._monitor_unsubscribe()
        except Exception:
            pass
        try:
            self.monitor.close()
        except Exception:
            self.logger.exception("Could not stop Cook Monitor.")
        if self._hip_callback_registered:
            try:
                self.hou.hipFile.removeEventCallback(self._hip_event)
            except Exception:
                pass
            self._hip_callback_registered = False
        try:
            self.notifications.clear()
        except Exception:
            pass

    def add_listener(self, callback: Listener) -> Callable[[], None]:
        if callback not in self._listeners:
            self._listeners.append(callback)

        def remove() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return remove

    def notify_changed(self, topic: str = "all") -> None:
        for callback in tuple(self._listeners):
            try:
                callback(topic)
            except Exception:
                self.logger.exception("HCQ UI listener failed.")

    def refresh_all(self) -> None:
        self.queues = self.storage.load_queues()
        self.settings.clear()
        self.settings.update(self.storage.load_settings())
        self.monitor.update_settings(self.settings)
        self.notify_changed("all")

    def save_settings(self) -> None:
        self.run_list.save_before_running = str(
            self.settings.get("save_before_running", "always")
        )
        self.run_list.create_backup = bool(
            self.settings.get("create_backup_before_saving", False)
        )
        self.run_list.existing_output_behavior = str(
            self.settings.get("existing_output_behavior", "ask_each")
        )
        self.storage.save_settings(self.settings)
        self.monitor.update_settings(self.settings)
        self.notify_changed("settings")

    def save_queues(self) -> None:
        self.storage.save_queues(self.queues)
        self.notify_changed("queues")

    def create_queue(self, name: str = "Untitled Queue") -> QueueTemplate:
        hip_file = ""
        try:
            if not self.hou.hipFile.isNewFile():
                hip_file = str(self.hou.hipFile.path())
        except Exception:
            pass
        queue = QueueTemplate(name=name, hip_file=hip_file)
        self.queues.append(queue)
        self.save_queues()
        return queue

    def update_queue(self, queue: QueueTemplate) -> QueueTemplate:
        queue.updated_at = now_iso()
        queue.normalize_order()
        for index, existing in enumerate(self.queues):
            if existing.id == queue.id:
                self.queues[index] = copy.deepcopy(queue)
                self.save_queues()
                return self.queues[index]
        self.queues.append(copy.deepcopy(queue))
        self.save_queues()
        return self.queues[-1]

    def duplicate_queue(self, queue_id: str) -> QueueTemplate:
        queue = self.queue_by_id(queue_id)
        duplicate = queue.duplicate()
        self.queues.append(duplicate)
        self.save_queues()
        return duplicate

    def delete_queue(self, queue_id: str) -> bool:
        original_length = len(self.queues)
        self.queues[:] = [queue for queue in self.queues if queue.id != queue_id]
        changed = len(self.queues) != original_length
        if changed:
            self.save_queues()
        return changed

    def queue_by_id(self, queue_id: str) -> QueueTemplate:
        for queue in self.queues:
            if queue.id == queue_id:
                return queue
        raise KeyError(f"Queue not found: {queue_id}")

    def add_to_run_list(self, queue_ids: list[str] | tuple[str, ...]) -> None:
        for queue_id in queue_ids:
            self.run_list.queues.append(copy.deepcopy(self.queue_by_id(queue_id)))
        self.notify_changed("run_list")

    def remove_run_queue(self, index: int) -> None:
        if 0 <= index < len(self.run_list.queues):
            self.run_list.queues.pop(index)
            self.notify_changed("run_list")

    def move_run_queue(self, index: int, delta: int) -> None:
        destination = index + delta
        if not (0 <= index < len(self.run_list.queues)):
            return
        if not (0 <= destination < len(self.run_list.queues)):
            return
        queue = self.run_list.queues.pop(index)
        self.run_list.queues.insert(destination, queue)
        self.notify_changed("run_list")

    def clear_run_list(self) -> None:
        self.run_list.queues.clear()
        self.notify_changed("run_list")

    def import_queue_file(self, path: str | Path) -> list[QueueTemplate]:
        return self._add_imported_queues(import_queues(path))

    def import_queue_document(
        self, document: dict[str, Any]
    ) -> list[QueueTemplate]:
        return self._add_imported_queues(parse_queue_document(document))

    def _add_imported_queues(
        self, imported: list[QueueTemplate]
    ) -> list[QueueTemplate]:
        existing_ids = {queue.id for queue in self.queues}
        existing_job_ids = {
            job.id for queue in self.queues for job in queue.jobs
        }
        for queue in imported:
            if queue.id in existing_ids:
                queue.id = new_id("queue")
            for job in queue.jobs:
                if job.id in existing_job_ids:
                    job.id = new_id("job")
                existing_job_ids.add(job.id)
            existing_ids.add(queue.id)
            self.queues.append(queue)
        self.save_queues()
        return imported

    def export_queue_file(self, path: str | Path, queue_ids: list[str]) -> None:
        selected = [copy.deepcopy(self.queue_by_id(queue_id)) for queue_id in queue_ids]
        export_queues(path, selected, str(self.hou.applicationVersionString()))

    def preflight_run(self) -> Any:
        lock = self.runner.execution_lock
        try:
            lock.acquire()
        except Exception as exc:
            from .preflight import PreflightIssue, PreflightReport

            return PreflightReport(
                [PreflightIssue("error", "execution_lock", str(exc))]
            )
        try:
            return self.runner.preflight(self.run_list)
        finally:
            lock.release()

    def start_run(self) -> Any:
        if not self.run_list.queues:
            raise ValueError("The Run List is empty.")
        self.run_list.save_before_running = str(
            self.settings.get("save_before_running", self.run_list.save_before_running)
        )
        self.run_list.create_backup = bool(
            self.settings.get(
                "create_backup_before_saving", self.run_list.create_backup
            )
        )
        self.run_list.existing_output_behavior = str(
            self.settings.get(
                "existing_output_behavior",
                self.run_list.existing_output_behavior,
            )
        )
        result = self.runner.start(self.run_list)
        self.notify_changed("run")
        return result

    def export_run_list_file(self, path: str | Path) -> None:
        atomic_write_json(path, self.run_list.to_document())

    export_run_list = export_run_list_file

    def restore_history(self, session_id: str) -> RunList:
        document = self._history_document(session_id)
        queues = [
            QueueTemplate.from_dict(value)
            for value in document.get("queues", [])
            if isinstance(value, dict)
        ]
        if not queues:
            self.notifications.warning(
                "History",
                "The selected history record has no queue snapshot.",
            )
            return None  # type: ignore[return-value]
        self.run_list = RunList(queues=queues)
        self.notify_changed("run_list")
        return self.run_list

    def run_history(self, session_id: str) -> Any:
        self.restore_history(session_id)
        return self._start_restored_history("Run this historical queue again?")

    def run_failed_jobs(self, session_id: str) -> Any:
        document = self._history_document(session_id)
        failed_ids = {
            str(result.get("job_id"))
            for result in document.get("jobs", [])
            if result.get("state") in {"failed", "cancelled", "unknown", "interrupted"}
        }
        queues: list[QueueTemplate] = []
        for value in document.get("queues", []):
            if not isinstance(value, dict):
                continue
            queue = QueueTemplate.from_dict(value)
            queue.jobs = [job for job in queue.jobs if job.id in failed_ids]
            queue.normalize_order()
            if queue.jobs:
                queues.append(queue)
        if not queues:
            self.notifications.warning(
                "History",
                "The selected history record has no failed jobs.",
            )
            return None
        self.run_list = RunList(queues=queues)
        self.notify_changed("run_list")
        return self._start_restored_history("Run all failed jobs in a new session?")

    def run_from_failed_job(self, session_id: str) -> Any:
        document = self._history_document(session_id)
        results = list(document.get("jobs", []))
        failed = next(
            (
                str(result.get("job_id"))
                for result in results
                if result.get("state") in {"failed", "cancelled", "unknown", "interrupted"}
            ),
            "",
        )
        if not failed:
            self.notifications.warning(
                "History",
                "The selected history record has no failed job.",
            )
            return None
        include = False
        queues: list[QueueTemplate] = []
        for value in document.get("queues", []):
            if not isinstance(value, dict):
                continue
            queue = QueueTemplate.from_dict(value)
            selected = []
            for job in queue.jobs:
                if job.id == failed:
                    include = True
                if include:
                    selected.append(job)
            queue.jobs = selected
            queue.normalize_order()
            if queue.jobs:
                queues.append(queue)
        self.run_list = RunList(queues=queues)
        self.notify_changed("run_list")
        return self._start_restored_history(
            "Run from the first failed job in a new session?"
        )

    def go_to_history_node(self, session_id: str) -> Any:
        document = self._history_document(session_id)
        jobs = list(document.get("jobs", []))
        target = next(
            (
                result
                for result in reversed(jobs)
                if result.get("state") in {"failed", "cancelled", "unknown"}
            ),
            jobs[-1] if jobs else None,
        )
        if not target:
            self.notifications.warning(
                "History",
                "The selected history record has no job.",
            )
            return None
        return self.navigation.go_to_node(str(target.get("node_path", "")))

    def export_history_result(self, session_id: str, path: str | Path) -> None:
        document = dict(self._history_document(session_id))
        document.pop("_path", None)
        atomic_write_json(path, document)

    export_result = export_history_result

    def _history_document(self, session_id: str) -> dict[str, Any]:
        for document in self.storage.history_documents():
            if str(document.get("session_id") or document.get("id")) == session_id:
                return document
        raise KeyError(f"History session not found: {session_id}")

    def _start_restored_history(self, message: str) -> Any:
        decision = self._choose(
            "Run History",
            message,
            ("run", "cancel"),
            ("Run Queue", "Cancel"),
            default=1,
        )
        if decision != "run":
            return self.run_list
        return self.start_run()

    def restore_recovery_retry(self, record: Any) -> RunList:
        self.run_list = self.recovery.build_retry_run_list(record)
        self.notify_changed("run_list")
        return self.run_list

    def restore_recovery_restart(self, record: Any) -> RunList:
        self.run_list = self.recovery.build_restart_run_list(record)
        self.notify_changed("run_list")
        return self.run_list

    def mark_recovery_job_complete(self, record: Any) -> Any:
        result = self.recovery.mark_current_job_complete(record)
        self.notify_changed("history")
        return result

    def archive_recovery(self, record: Any) -> Any:
        result = self.recovery.archive_interrupted(record)
        self.notify_changed("history")
        return result

    def _runner_state_changed(self, *_args: Any, **_kwargs: Any) -> None:
        self.notify_changed("run")

    def _monitor_changed(self, *_args: Any, **_kwargs: Any) -> None:
        self.notify_changed("monitor")

    def _hip_event(self, event_type: Any, **kwargs: Any) -> None:
        try:
            if event_type in {
                self.hou.hipFileEventType.BeforeClear,
                self.hou.hipFileEventType.BeforeLoad,
            }:
                self.monitor.suspend()
            elif event_type in {
                self.hou.hipFileEventType.AfterClear,
                self.hou.hipFileEventType.AfterLoad,
            }:
                self.monitor.set_current_hip(str(self.hou.hipFile.path()))
                self.monitor.resume(refresh_baselines=True)
                self.notify_changed("hip")
            elif event_type == self.hou.hipFileEventType.AfterSave:
                new_path = str(kwargs.get("new_hip_file") or self.hou.hipFile.path())
                self.monitor.handle_hip_saved(new_path)
                self.notify_changed("hip")
        except Exception:
            self.logger.exception("HCQ HIP event handling failed.")

    def _decision_handler(self, kind: str, payload: dict[str, Any]) -> Any:
        """Use Houdini-native modal decisions only when execution requires one."""
        if kind == "save_hip_as":
            try:
                return self.hou.ui.selectFile(
                    title="Save HIP Before Running",
                    file_type=self.hou.fileType.Hip,
                    chooser_mode=self.hou.fileChooserMode.Write,
                    collapse_sequences=True,
                )
            except Exception:
                return None

        if kind == "job_error":
            result = payload.get("result")
            message = "\n".join(getattr(result, "errors", [])) or "The job failed."
            return self._choose(
                "Job Failed",
                message,
                ("retry", "skip", "stop"),
                ("Retry Job", "Skip Job", "Stop Queue"),
                default=2,
            )
        if kind == "save_hip":
            return self._choose(
                "Save Before Running",
                "Save the current HIP file before running?",
                ("save", "dont_save", "cancel"),
                ("Save and Run", "Run Without Saving", "Cancel"),
                default=2,
            )
        if kind == "confirm_run":
            run_list = payload.get("run_list")
            queue_count = len(getattr(run_list, "queues", []))
            job_count = sum(len(queue.jobs) for queue in getattr(run_list, "queues", []))
            return self._choose(
                "Run Queue",
                f"Queues: {queue_count}\nJobs: {job_count}\n\n"
                "Houdini may be unavailable while foreground jobs are running.",
                ("run", "cancel"),
                ("Run Queue", "Cancel"),
                default=1,
            )
        if kind == "preflight_issue":
            issue = payload.get("issue")
            choices = tuple(payload.get("choices") or ("stop",))
            labels = tuple(choice.replace("_", " ").title() for choice in choices)
            return self._choose(
                "Preflight Decision",
                str(getattr(issue, "message", "A preflight decision is required.")),
                choices,
                labels,
                default=max(0, len(choices) - 1),
            )
        return None

    def _choose(
        self,
        title: str,
        message: str,
        values: tuple[Any, ...],
        labels: tuple[str, ...],
        default: int = 0,
    ) -> Any:
        try:
            index = self.hou.ui.displayMessage(
                message,
                title=title,
                buttons=labels,
                default_choice=default,
                close_choice=default,
            )
            return values[index]
        except Exception:
            return values[default]
