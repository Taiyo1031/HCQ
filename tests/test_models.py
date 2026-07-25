from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.models import CpuSetting, FrameRange, Job, QueueTemplate, RunList, RunSession


class ModelTests(unittest.TestCase):
    def test_queue_round_trip_and_order(self):
        queue = QueueTemplate(
            name="Cache",
            jobs=[
                Job(order=9, display_name="A", node_path="/obj/a"),
                Job(order=2, display_name="B", node_path="/obj/b"),
            ],
        )
        restored = QueueTemplate.from_dict(queue.to_dict())
        self.assertEqual([job.order for job in restored.jobs], [1, 2])
        self.assertEqual(restored.name, "Cache")

    def test_duplicate_gets_new_ids(self):
        original = QueueTemplate(jobs=[Job(node_path="/obj/a")])
        duplicate = original.duplicate()
        self.assertNotEqual(original.id, duplicate.id)
        self.assertNotEqual(original.jobs[0].id, duplicate.jobs[0].id)

    def test_run_list_snapshot_is_independent(self):
        run_list = RunList(queues=[QueueTemplate(name="Original")])
        snapshot = run_list.snapshot()
        snapshot.queues[0].name = "Changed"
        self.assertEqual(run_list.queues[0].name, "Original")

    def test_public_schema_names(self):
        run_list = RunList()
        self.assertEqual(run_list.to_document()["schema"], "hcq.run-list")
        session = RunSession()
        self.assertEqual(session.to_document()["schema"], "hcq.run-status")
        self.assertEqual(session.to_document(completed=True)["schema"], "hcq.run-result")
        self.assertIn("duration_seconds", session.to_document())

    def test_frame_and_cpu_serialization(self):
        job = Job(
            node_path="/obj/a",
            frame_range=FrameRange("custom", 1, 10, 2),
            cpu=CpuSetting("threads", 8),
        )
        restored = Job.from_dict(job.to_dict())
        self.assertEqual(restored.frame_range.end, 10)
        self.assertEqual(restored.cpu.value, 8)


if __name__ == "__main__":
    unittest.main()
