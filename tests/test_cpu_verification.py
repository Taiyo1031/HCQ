from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.cpu import TemporaryThreadLimit, resolve_thread_limit
from hcq.models import CpuSetting
from hcq.verification import verify_outputs


class FakeHou:
    def __init__(self):
        self.value = 16

    def maxThreads(self):
        return self.value

    def setMaxThreads(self, value):
        self.value = value


class CpuVerificationTests(unittest.TestCase):
    def test_cpu_modes(self):
        self.assertIsNone(resolve_thread_limit(CpuSetting("current"), 16))
        self.assertEqual(resolve_thread_limit(CpuSetting("all"), 16), 0)
        self.assertEqual(resolve_thread_limit(CpuSetting("single"), 16), 1)
        self.assertEqual(resolve_thread_limit(CpuSetting("threads", 30), 16), 16)
        self.assertEqual(resolve_thread_limit(CpuSetting("reserve", 2), 16), 14)

    def test_thread_limit_restores_after_exception(self):
        hou = FakeHou()
        with self.assertRaises(RuntimeError):
            with TemporaryThreadLimit(hou, CpuSetting("threads", 4)):
                self.assertEqual(hou.value, 4)
                raise RuntimeError("failure")
        self.assertEqual(hou.value, 16)

    def test_output_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cache.bgeo.sc"
            path.write_bytes(b"cache")
            started = datetime.now().astimezone() - timedelta(seconds=1)
            result = verify_outputs([str(path)], started)
            self.assertTrue(result.success)
            self.assertEqual(result.output_paths, [str(path)])

    def test_empty_output_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "empty.bgeo.sc"
            path.write_bytes(b"")
            result = verify_outputs(
                [str(path)], datetime.now().astimezone() - timedelta(seconds=1)
            )
            self.assertFalse(result.success)

    def test_output_older_than_job_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "stale.bgeo.sc"
            path.write_bytes(b"stale")
            stale = (datetime.now().astimezone() - timedelta(seconds=10)).timestamp()
            os.utime(path, (stale, stale))
            result = verify_outputs([str(path)], datetime.now().astimezone())
            self.assertFalse(result.success)
            self.assertTrue(
                any("not updated by this job" in error for error in result.errors)
            )


if __name__ == "__main__":
    unittest.main()
