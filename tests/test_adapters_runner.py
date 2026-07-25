from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.adapters import resolve_adapter
from hcq.adapters.button import ButtonAdapter
from hcq.adapters.filecache import FileCacheAdapter
from hcq.models import CpuSetting, Job, QueueTemplate, RunList
from hcq.queue_runner import QueueRunner


class FakeCategory:
    def __init__(self, name="Sop"):
        self._name = name

    def name(self):
        return self._name


class FakeType:
    def __init__(self, name="null", category="Sop"):
        self._name = name
        self._category = FakeCategory(category)

    def name(self):
        return self._name

    def nameWithCategory(self):
        return f"{self._category.name()}/{self._name}"

    def category(self):
        return self._category

    def definition(self):
        return None


class FakeParm:
    def __init__(self, value=None):
        self.value = value
        self.pressed = 0

    def eval(self):
        return self.value

    def set(self, value):
        self.value = value

    def pressButton(self):
        self.pressed += 1
        return None

    def unexpandedString(self):
        return str(self.value or "")


class FakeNode:
    def __init__(self, path="/obj/geo1/null1", type_name="null", category="Sop"):
        self._path = path
        self._type = FakeType(type_name, category)
        self.parms = {}
        self.cook_calls = 0
        self.failures_remaining = 0

    def path(self):
        return self._path

    def type(self):
        return self._type

    def parm(self, name):
        return self.parms.get(name)

    def isBypassed(self):
        return False

    def errors(self):
        return ()

    def warnings(self):
        return ()

    def cook(self, force=False, frame_range=()):
        self.cook_calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("Cook failed")
        return None


class FakeHipFile:
    def isNewFile(self):
        return False

    def path(self):
        return "D:/Project/test.hip"

    def hasUnsavedChanges(self):
        return False


class FakeHou:
    class OperationInterrupted(Exception):
        pass

    RopNode = type("RopNode", (), {})

    def __init__(self, nodes):
        self.nodes = nodes
        self.hipFile = FakeHipFile()
        self.threads = 16

    def applicationVersion(self):
        return (21, 0, 729)

    def applicationVersionString(self):
        return "21.0.729"

    def isUIAvailable(self):
        return True

    def node(self, path):
        return self.nodes.get(path)

    def expandString(self, value):
        return value

    def maxThreads(self):
        return self.threads

    def setMaxThreads(self, value):
        self.threads = value


class AdapterRunnerTests(unittest.TestCase):
    def test_filecache_uses_foreground_execute(self):
        node = FakeNode(type_name="filecache::2.0")
        node.parms["execute"] = FakeParm()
        node.parms["cookoutputnode"] = FakeParm()
        job = Job(node_path=node.path(), action="filecache_save_to_disk", verification="none")
        hou = FakeHou({node.path(): node})
        adapter = resolve_adapter(job.action, node, job, hou)
        self.assertIsInstance(adapter, FileCacheAdapter)
        result = adapter.execute(
            node,
            job,
            __import__("datetime").datetime.now().astimezone(),
        )
        self.assertTrue(result.success)
        self.assertEqual(node.parms["execute"].pressed, 1)
        self.assertEqual(node.parms["cookoutputnode"].pressed, 0)

    def test_button_adapter_rejects_missing_parameter(self):
        node = FakeNode()
        job = Job(node_path=node.path(), action="press_button", button_parameter="run")
        adapter = ButtonAdapter(FakeHou({node.path(): node}))
        self.assertTrue(adapter.validate(node, job))

    def test_runner_retries_and_restores_threads(self):
        node = FakeNode()
        node.failures_remaining = 1
        hou = FakeHou({node.path(): node})
        job = Job(
            node_path=node.path(),
            action="force_cook",
            retry_count=1,
            verification="none",
            cpu=CpuSetting("threads", 4),
        )
        queue = QueueTemplate(
            name="Queue",
            hip_file="D:/Project/test.hip",
            cpu=CpuSetting("current"),
            jobs=[job],
        )
        runner = QueueRunner(hou, confirm_before_run=False)
        session = runner.start(RunList(queues=[queue], save_before_running="never"))
        self.assertEqual(session.state, "completed")
        self.assertEqual(session.jobs[0].attempts, 2)
        self.assertEqual(node.cook_calls, 2)
        self.assertEqual(hou.threads, 16)
        self.assertEqual(session.queues[0]["jobs"][0]["id"], job.id)

    def test_runner_stops_on_failure(self):
        node = FakeNode()
        node.failures_remaining = 5
        hou = FakeHou({node.path(): node})
        job = Job(
            node_path=node.path(),
            action="force_cook",
            retry_count=0,
            verification="none",
        )
        queue = QueueTemplate(
            name="Queue", hip_file="D:/Project/test.hip", jobs=[job]
        )
        runner = QueueRunner(hou, confirm_before_run=False)
        session = runner.start(RunList(queues=[queue], save_before_running="never"))
        self.assertEqual(session.state, "failed")
        self.assertEqual(session.jobs[0].state, "failed")

    def test_cancel_from_running_status_does_not_start_cook(self):
        node = FakeNode()
        hou = FakeHou({node.path(): node})
        job = Job(
            node_path=node.path(),
            action="force_cook",
            verification="none",
        )
        queue = QueueTemplate(
            name="Queue", hip_file="D:/Project/test.hip", jobs=[job]
        )
        runner = None

        def state_changed(session):
            if (
                runner is not None
                and session.current_job_id == job.id
                and session.jobs[0].state == "running"
                and not runner.cancel_requested
            ):
                runner.request_cancel()

        runner = QueueRunner(
            hou,
            confirm_before_run=False,
            state_callback=state_changed,
        )
        session = runner.start(
            RunList(queues=[queue], save_before_running="never")
        )
        self.assertEqual(node.cook_calls, 0)
        self.assertEqual(session.state, "cancelled")
        self.assertEqual(session.jobs[0].state, "cancelled")


if __name__ == "__main__":
    unittest.main()
