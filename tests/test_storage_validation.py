from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.import_export import remap_document_paths
from hcq.models import Job, QueueTemplate, queue_library_document
from hcq.storage import Storage, atomic_write_json
from hcq.validation import ValidationError, parse_queue_document, validate_job


class StorageValidationTests(unittest.TestCase):
    def test_atomic_json_is_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "value.json"
            atomic_write_json(path, {"value": "✓"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["value"], "✓")

    def test_storage_queue_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary) / "HCQ", "21.0.729")
            queue = QueueTemplate(name="Queue", jobs=[Job(node_path="/obj/a")])
            storage.save_queues([queue])
            self.assertEqual(storage.load_queues()[0].name, "Queue")

    def test_rejects_arbitrary_action(self):
        document = queue_library_document(
            [QueueTemplate(jobs=[Job(node_path="/obj/a", action="python")])]
        )
        with self.assertRaises(ValidationError):
            parse_queue_document(document)

    def test_rejects_duplicate_job_ids_across_queues(self):
        first = Job(id="job-same", node_path="/obj/a")
        second = Job(id="job-same", node_path="/obj/b")
        document = queue_library_document(
            [
                QueueTemplate(id="queue-a", jobs=[first]),
                QueueTemplate(id="queue-b", jobs=[second]),
            ]
        )
        with self.assertRaises(ValidationError):
            parse_queue_document(document)

    def test_invalid_frame_range(self):
        issues = validate_job(
            Job(node_path="/obj/a", frame_range=__import__("hcq.models", fromlist=["FrameRange"]).FrameRange("custom", 10, 1, 1))
        )
        self.assertIn("invalid_frame_range", {issue.code for issue in issues})

    def test_path_remap_does_not_touch_node_paths(self):
        value = {
            "hip_file": "D:/Project/a.hip",
            "node_path": "D:/Project/not-a-houdini-path",
            "expected_outputs": ["D:/Project/cache/a.bgeo.sc"],
        }
        result = remap_document_paths(value, "D:/Project", "E:/Moved")
        self.assertEqual(result["hip_file"], "E:/Moved/a.hip")
        self.assertEqual(result["node_path"], value["node_path"])
        self.assertEqual(result["expected_outputs"][0], "E:/Moved/cache/a.bgeo.sc")


if __name__ == "__main__":
    unittest.main()
