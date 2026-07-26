from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "HCQ" / "python3.11libs"))

from hcq.adapters import resolve_adapter
from hcq.adapters.button import ButtonAdapter
from hcq.adapters.filecache import FileCacheAdapter
from hcq.models import CpuSetting, Job, QueueTemplate, RunList
from hcq.preflight import PreflightChecker
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
    def __init__(self, value=None, callback=None):
        self.value = value
        self.callback = callback
        self.pressed = 0

    def eval(self):
        return self.value

    def set(self, value):
        self.value = value

    def pressButton(self):
        self.pressed += 1
        if self.callback is not None:
            return self.callback()
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

    def test_filecache_filemethod_selects_only_the_active_path(self):
        node = FakeNode(type_name="filecache::2.0")
        node.parms.update(
            {
                "filemethod": FakeParm(1),
                "file": FakeParm(""),
                "sopoutput": FakeParm("D:/wrong/cache.$F4.bgeo.sc"),
            }
        )
        job = Job(node_path=node.path(), action="filecache_save_to_disk")
        adapter = FileCacheAdapter(FakeHou({node.path(): node}))
        self.assertEqual(adapter.expected_output_patterns(node, job), [])

        node.parms["filemethod"].set(0)
        self.assertEqual(
            adapter.expected_output_patterns(node, job),
            ["D:/wrong/cache.$F4.bgeo.sc"],
        )

    def test_filecache_basic_requires_a_resolved_native_output(self):
        node = FakeNode(type_name="filecache::2.0")
        node.parms.update(
            {
                "execute": FakeParm(),
                "filemethod": FakeParm(1),
                "file": FakeParm(""),
                "sopoutput": FakeParm(""),
            }
        )
        job = Job(node_path=node.path(), action="filecache_save_to_disk")
        result = FileCacheAdapter(FakeHou({node.path(): node})).execute(
            node,
            job,
            datetime.now().astimezone(),
        )
        self.assertFalse(result.success)
        self.assertTrue(
            any("empty or unresolved" in error for error in result.errors)
        )

    def test_filecache_basic_fails_when_configured_output_is_not_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "missing.bgeo.sc"
            node = FakeNode(type_name="filecache::2.0")
            node.parms.update(
                {
                    "execute": FakeParm(),
                    "filemethod": FakeParm(1),
                    "file": FakeParm(str(output)),
                }
            )
            job = Job(node_path=node.path(), action="filecache_save_to_disk")
            result = FileCacheAdapter(FakeHou({node.path(): node})).execute(
                node,
                job,
                datetime.now().astimezone(),
            )
            self.assertFalse(result.success)
            self.assertTrue(
                any("does not exist" in error for error in result.errors)
            )

    def test_filecache_reacquires_output_after_native_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "created.bgeo.sc"
            node = FakeNode(type_name="filecache::2.0")
            file_parm = FakeParm("")

            def create_output():
                file_parm.set(str(output))
                output.write_bytes(b"cache")

            node.parms.update(
                {
                    "execute": FakeParm(callback=create_output),
                    "filemethod": FakeParm(1),
                    "file": file_parm,
                }
            )
            job = Job(node_path=node.path(), action="filecache_save_to_disk")
            result = FileCacheAdapter(FakeHou({node.path(): node})).execute(
                node,
                job,
                datetime.now().astimezone(),
            )
            self.assertTrue(result.success, result.errors)
            self.assertEqual(result.output_paths, [str(output)])

    def test_generic_basic_allows_no_output_patterns(self):
        node = FakeNode()
        job = Job(node_path=node.path(), action="force_cook", verification="basic")
        hou = FakeHou({node.path(): node})
        result = resolve_adapter(job.action, node, job, hou).execute(
            node,
            job,
            datetime.now().astimezone(),
        )
        self.assertTrue(result.success, result.errors)

    def test_filecache_preflight_output_warnings_are_nonblocking(self):
        with tempfile.TemporaryDirectory() as temporary:
            node = FakeNode(type_name="filecache::2.0")
            node.parms.update(
                {
                    "execute": FakeParm(),
                    "filemethod": FakeParm(1),
                    "file": FakeParm(""),
                }
            )
            hou = FakeHou({node.path(): node})
            job = Job(node_path=node.path(), action="filecache_save_to_disk")
            queue = QueueTemplate(
                name="Queue",
                hip_file="D:/Project/test.hip",
                jobs=[job],
            )
            run_list = RunList(
                queues=[queue],
                save_before_running="never",
                existing_output_behavior="overwrite",
            )
            checker = PreflightChecker(hou)

            empty_report = checker.check(run_list)
            empty_issue = next(
                issue
                for issue in empty_report.issues
                if issue.code == "unresolved_output_path"
            )
            self.assertTrue(empty_report.can_run)
            self.assertFalse(empty_issue.requires_decision)

            output = Path(temporary) / "new" / "cache.bgeo.sc"
            node.parms["file"].set(str(output))
            missing_parent_report = checker.check(run_list)
            missing_parent = next(
                issue
                for issue in missing_parent_report.issues
                if issue.code == "missing_output_directory"
            )
            self.assertTrue(missing_parent_report.can_run)
            self.assertFalse(missing_parent.requires_decision)
            self.assertEqual(
                Path(missing_parent.context["existing_ancestor"]),
                Path(temporary),
            )

            node.parms["file"].set(str(Path(temporary) / "cache.bgeo.sc"))
            missing_file_report = checker.check(run_list)
            self.assertTrue(missing_file_report.can_run)
            self.assertTrue(
                any(
                    issue.code == "output_not_created"
                    and not issue.requires_decision
                    for issue in missing_file_report.issues
                )
            )

    def test_preflight_warns_when_reserved_threads_exceed_capacity(self):
        node = FakeNode()
        hou = FakeHou({node.path(): node})
        job = Job(
            node_path=node.path(),
            action="force_cook",
            cpu=CpuSetting("reserve", 16),
        )
        queue = QueueTemplate(
            name="Queue",
            hip_file="D:/Project/test.hip",
            jobs=[job],
        )
        report = PreflightChecker(hou, available_threads=16).check(
            RunList(
                queues=[queue],
                save_before_running="never",
                existing_output_behavior="overwrite",
            )
        )
        warning = next(
            issue
            for issue in report.issues
            if issue.code == "cpu_reserve_clamped"
        )
        self.assertEqual(warning.severity, "warning")
        self.assertIn("one logical thread", warning.message)
        self.assertTrue(report.can_run)

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

    def test_runner_keeps_planned_filecache_path_after_verification_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "missing.bgeo.sc"
            node = FakeNode(type_name="filecache::2.0")
            node.parms.update(
                {
                    "execute": FakeParm(),
                    "filemethod": FakeParm(1),
                    "file": FakeParm(str(output)),
                }
            )
            hou = FakeHou({node.path(): node})
            job = Job(node_path=node.path(), action="filecache_save_to_disk")
            queue = QueueTemplate(
                name="Queue",
                hip_file="D:/Project/test.hip",
                jobs=[job],
            )
            runner = QueueRunner(hou, confirm_before_run=False)
            session = runner.start(
                RunList(
                    queues=[queue],
                    save_before_running="never",
                    existing_output_behavior="overwrite",
                )
            )
            self.assertEqual(session.state, "failed")
            self.assertIn(str(output), session.jobs[0].output_paths)

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
