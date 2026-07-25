from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.models import Job, JobResult, QueueTemplate, RunSession
from hcq.recovery import RecoveryService
from hcq.storage import Storage
from hcq.utils import now_iso


class RecoveryTests(unittest.TestCase):
    def test_interrupted_session_can_restore_retry_and_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary) / "HCQ")
            job = Job(display_name="Cache", node_path="/obj/cache")
            queue = QueueTemplate(name="Queue", jobs=[job])
            session = RunSession(
                state="running",
                started_at=now_iso(),
                queues=[queue.to_dict()],
                jobs=[
                    JobResult(
                        job_id=job.id,
                        display_name=job.display_name,
                        node_path=job.node_path,
                        action=job.action,
                        state="running",
                    )
                ],
                current_job_id=job.id,
            )
            storage.save_active_session(session)
            recovery = RecoveryService(storage)
            records = recovery.discover()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].session.state, "interrupted")
            retry = recovery.build_retry_run_list(records[0])
            restart = recovery.build_restart_run_list(records[0])
            self.assertEqual(len(retry.queues[0].jobs), 1)
            self.assertEqual(retry.queues[0].jobs[0].id, job.id)
            self.assertEqual(restart.queues[0].name, "Queue")
            history_path = recovery.archive_interrupted(records[0])
            self.assertTrue(history_path.exists())
            self.assertEqual(storage.active_sessions(), [])

    def test_inspection_falls_back_to_snapshot_expected_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "cache.bgeo.sc"
            output.write_bytes(b"cache")
            storage = Storage(root / "HCQ")
            job = Job(
                display_name="Cache",
                node_path="/obj/cache",
                expected_outputs=[str(output)],
            )
            queue = QueueTemplate(name="Queue", jobs=[job])
            session = RunSession(
                state="running",
                started_at=now_iso(),
                queues=[queue.to_dict()],
                jobs=[
                    JobResult(
                        job_id=job.id,
                        display_name=job.display_name,
                        node_path=job.node_path,
                        action=job.action,
                        state="running",
                    )
                ],
                current_job_id=job.id,
            )
            inspections = RecoveryService(storage).inspect_outputs(session)
            self.assertEqual(len(inspections), 1)
            self.assertTrue(inspections[0].exists)


if __name__ == "__main__":
    unittest.main()
