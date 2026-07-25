"""Interrupted run discovery and user-directed recovery operations."""

from __future__ import annotations

import copy
import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import JobResult, QueueTemplate, RunList, RunSession
from .storage import atomic_write_json, read_json
from .utils import now_iso


INTERRUPTIBLE_STATES = {
    "preparing",
    "running",
    "pause_requested",
    "paused",
    "cancel_requested",
}


@dataclass(frozen=True)
class OutputInspection:
    path: str
    exists: bool
    is_file: bool
    size_bytes: int | None = None
    modified_at: float | None = None


@dataclass
class RecoveryRecord:
    session: RunSession
    original_state: str
    interrupted_job: JobResult | None
    active_path: Path
    output_inspections: list[OutputInspection] = field(default_factory=list)

    @property
    def session_id(self) -> str:
        return self.session.id


class RecoveryService:
    """Creates new recovery run lists without overwriting original history."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage

    @property
    def pending(self) -> RunSession | None:
        return self.pending_session()

    def pending_session(self) -> RunSession | None:
        records = self.discover()
        return records[0].session if records else None

    get_pending_session = pending_session
    load_interrupted = pending_session
    detect_interrupted = pending_session

    def discover(self, mark_interrupted: bool = True) -> list[RecoveryRecord]:
        records: list[RecoveryRecord] = []
        for session, active_path in self._active_sessions_with_paths():
            if (
                session.state not in INTERRUPTIBLE_STATES
                and session.state not in {"interrupted", "unknown", "idle"}
            ):
                continue
            original_state = session.state
            job = self._interrupted_job(session)
            if mark_interrupted and session.state != "interrupted":
                self._preserve_recovery_copy(session, original_state)
                session.state = "interrupted"
                session.updated_at = now_iso()
                session.message = (
                    "The previous HCQ session ended before completion. "
                    "Output must be inspected before retrying or marking work complete."
                )
                self.storage.save_active_session(session)
            record = RecoveryRecord(
                session=session,
                original_state=original_state,
                interrupted_job=job,
                active_path=active_path,
            )
            record.output_inspections = self.inspect_outputs(record)
            records.append(record)
        return records

    def inspect_outputs(
        self,
        record_or_session: RecoveryRecord | RunSession,
    ) -> list[OutputInspection]:
        session = (
            record_or_session.session
            if isinstance(record_or_session, RecoveryRecord)
            else record_or_session
        )
        job = self._interrupted_job(session)
        if job is None:
            return []
        patterns = list(job.output_paths)
        if not patterns:
            for queue in self._snapshot_queues(session):
                matching = next(
                    (item for item in queue.jobs if item.id == job.job_id),
                    None,
                )
                if matching is not None:
                    patterns = list(matching.expected_outputs)
                    break
        result: list[OutputInspection] = []
        hip_directory = (
            str(Path(session.hip_file).parent) if session.hip_file else ""
        )
        for pattern in patterns:
            expanded = os.path.expandvars(os.path.expanduser(pattern))
            if hip_directory:
                expanded = expanded.replace("$HIP", hip_directory)
            expanded = re.sub(r"\$F\d*|<F\d*>", "*", expanded)
            matches = glob.glob(expanded) if glob.has_magic(expanded) else [expanded]
            if not matches:
                matches = [expanded]
            for match in matches:
                path = Path(match)
                try:
                    stat = path.stat()
                    result.append(
                        OutputInspection(
                            path=str(path),
                            exists=True,
                            is_file=path.is_file(),
                            size_bytes=stat.st_size if path.is_file() else None,
                            modified_at=stat.st_mtime,
                        )
                    )
                except OSError:
                    result.append(
                        OutputInspection(path=str(path), exists=False, is_file=False)
                    )
        return result

    inspect_output = inspect_outputs

    def build_retry_run_list(
        self,
        record_or_session: RecoveryRecord | RunSession,
    ) -> RunList:
        """Build a new one-job Run List for the interrupted job."""
        session = self._session(record_or_session)
        interrupted = self._interrupted_job(session)
        if interrupted is None:
            raise ValueError("The interrupted session has no recoverable current job.")
        queues = self._snapshot_queues(session)
        for queue in queues:
            matching = [job for job in queue.jobs if job.id == interrupted.job_id]
            if matching:
                queue.jobs = [copy.deepcopy(matching[0])]
                queue.normalize_order()
                return RunList(queues=[queue])
        raise ValueError("The interrupted job is not present in the stored queue snapshot.")

    retry_job = build_retry_run_list
    retry_interrupted_job = build_retry_run_list

    def build_restart_run_list(
        self,
        record_or_session: RecoveryRecord | RunSession,
    ) -> RunList:
        """Build a complete new Run List from the immutable session snapshot."""
        session = self._session(record_or_session)
        queues = self._snapshot_queues(session)
        if not queues:
            raise ValueError("The interrupted session has no queue snapshot.")
        return RunList(queues=queues)

    restart_queue = build_restart_run_list
    restart_interrupted_queue = build_restart_run_list

    def mark_current_job_complete(
        self,
        record_or_session: RecoveryRecord | RunSession,
    ) -> RunSession:
        """Record the user's manual decision while retaining interrupted state."""
        session = copy.deepcopy(self._session(record_or_session))
        job = self._interrupted_job(session)
        if job is None:
            raise ValueError("The interrupted session has no current job.")
        job.state = "completed"
        job.ended_at = now_iso()
        session.current_job_id = None
        session.state = "interrupted"
        session.updated_at = now_iso()
        session.message = (
            "The interrupted job was marked complete manually. "
            "The session remains interrupted until it is archived."
        )
        self.storage.save_active_session(session)
        return session

    mark_complete = mark_current_job_complete
    mark_job_complete = mark_current_job_complete

    def archive_interrupted(
        self,
        record_or_session: RecoveryRecord | RunSession,
    ) -> Path:
        """Move an interrupted session to immutable history."""
        session = copy.deepcopy(self._session(record_or_session))
        session.state = "interrupted"
        session.current_job_id = None
        session.updated_at = now_iso()
        session.ended_at = session.ended_at or session.updated_at
        if not session.message:
            session.message = "Archived as an interrupted HCQ session."
        return self.storage.complete_session(session)

    def invalid_recovery_files(self) -> list[Path]:
        """Return corrupt status documents quarantined by :class:`Storage`."""
        return sorted(self.storage.paths.recovery.glob("*.invalid-*"))

    def _snapshot_queues(self, session: RunSession) -> list[QueueTemplate]:
        queues: list[QueueTemplate] = []
        for value in session.queues:
            if not isinstance(value, dict):
                continue
            # A runner may store either the queue dictionary directly or a
            # small wrapper containing the immutable queue snapshot.
            candidate = value.get("queue") if isinstance(value.get("queue"), dict) else value
            queues.append(QueueTemplate.from_dict(copy.deepcopy(candidate)))
        return queues

    def _active_sessions_with_paths(self) -> list[tuple[RunSession, Path]]:
        sessions: list[tuple[RunSession, Path]] = []
        for path in sorted(self.storage.paths.active_runs.glob("session-*.json")):
            try:
                value = read_json(path, {})
                if not isinstance(value, dict):
                    raise TypeError("Run status must be a JSON object.")
                if not value.get("session_id") and not value.get("id"):
                    value["session_id"] = path.stem
                sessions.append((RunSession.from_dict(value), path))
            except (OSError, ValueError, TypeError):
                quarantine = getattr(self.storage, "_quarantine", None)
                if callable(quarantine):
                    quarantine(path)
        return sessions

    @staticmethod
    def _session(record_or_session: RecoveryRecord | RunSession) -> RunSession:
        return (
            record_or_session.session
            if isinstance(record_or_session, RecoveryRecord)
            else record_or_session
        )

    @staticmethod
    def _interrupted_job(session: RunSession) -> JobResult | None:
        if session.current_job_id:
            match = next(
                (job for job in session.jobs if job.job_id == session.current_job_id),
                None,
            )
            if match is not None:
                return match
        return next(
            (
                job
                for job in reversed(session.jobs)
                if job.state in {"running", "preparing", "validating", "unknown"}
            ),
            None,
        )

    def _preserve_recovery_copy(self, session: RunSession, original_state: str) -> Path:
        destination = self.storage.paths.recovery / f"{session.id}.interrupted.json"
        if not destination.exists():
            document = session.to_document(completed=False)
            document["detected_original_state"] = original_state
            document["detected_at"] = now_iso()
            atomic_write_json(destination, document)
        return destination
