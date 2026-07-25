"""Common contracts and helpers for foreground Houdini job adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from ..models import Job
from ..utils import deduplicated, expand_frame_pattern, frame_values
from ..verification import verify_outputs


@dataclass
class AdapterResult:
    """Normalized outcome returned by every execution adapter."""

    action: str
    success: bool = True
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)


def node_category_name(node: Any) -> str:
    try:
        return str(node.type().category().name())
    except Exception:
        return ""


def node_type_name(node: Any) -> str:
    try:
        return str(node.type().name())
    except Exception:
        return ""


def node_messages(node: Any, attribute: str) -> list[str]:
    try:
        value = getattr(node, attribute)()
    except Exception:
        return []
    if isinstance(value, str):
        return [value] if value else []
    try:
        return [str(item) for item in value if str(item)]
    except TypeError:
        return []


def is_operation_interrupted(exc: BaseException, hou_module: Any) -> bool:
    operation_interrupted = getattr(hou_module, "OperationInterrupted", None)
    if operation_interrupted is not None and isinstance(exc, operation_interrupted):
        return True
    return exc.__class__.__name__ in {"OperationInterrupted", "KeyboardInterrupt"}


def frame_range_for_job(job: Job, hou_module: Any) -> tuple[float, float, float] | None:
    frame_range = job.frame_range
    if frame_range.mode == "custom":
        if frame_range.start is None or frame_range.end is None:
            return None
        return (float(frame_range.start), float(frame_range.end), float(frame_range.step))
    if frame_range.mode == "playback":
        try:
            start, end = hou_module.playbar.playbackRange()
        except Exception:
            try:
                start, end = hou_module.playbar.frameRange()
            except Exception:
                return None
        return (float(start), float(end), float(frame_range.step))
    return None


class TemporaryNodeFrameRange:
    """Temporarily apply a custom range to standard Houdini frame parameters."""

    def __init__(self, node: Any, job: Job) -> None:
        self.node = node
        self.job = job
        self._values: list[tuple[Any, Any]] = []

    def __enter__(self) -> "TemporaryNodeFrameRange":
        frame_range = self.job.frame_range
        if frame_range.mode != "custom":
            return self
        values = {
            "trange": 1,
            "f1": frame_range.start,
            "f2": frame_range.end,
            "f3": frame_range.step,
        }
        for name, new_value in values.items():
            try:
                parm = self.node.parm(name)
            except Exception:
                parm = None
            if parm is None or new_value is None:
                continue
            try:
                old_value = parm.eval()
                parm.set(new_value)
            except Exception:
                continue
            self._values.append((parm, old_value))
        return self

    def __exit__(self, *_args: object) -> None:
        for parm, old_value in reversed(self._values):
            try:
                parm.set(old_value)
            except Exception:
                pass
        self._values.clear()


class ActionAdapter:
    """Base class for a single native foreground Houdini action."""

    action = ""

    def __init__(self, hou_module: Any) -> None:
        self.hou = hou_module
        self._active_node: Any | None = None

    def can_handle(self, node: Any, job: Job | None = None) -> bool:
        return node is not None

    def validate(self, node: Any, job: Job) -> list[str]:
        if node is None:
            return [f"Node does not exist: {job.node_path}"]
        return []

    def execute(self, node: Any, job: Job, started_at: datetime) -> AdapterResult:
        result = AdapterResult(action=self.action)
        before_errors = node_messages(node, "errors")
        before_warnings = node_messages(node, "warnings")
        self._active_node = node
        try:
            native_result = self._execute_native(node, job)
            if native_result is False:
                result.success = False
                result.errors.append("The Houdini operation reported failure.")
        except BaseException as exc:
            result.success = False
            if is_operation_interrupted(exc, self.hou):
                result.cancelled = True
                result.errors.append("The Houdini operation was cancelled.")
            else:
                result.errors.append(str(exc) or exc.__class__.__name__)
        finally:
            self._active_node = None

        after_errors = node_messages(node, "errors")
        after_warnings = node_messages(node, "warnings")
        result.errors.extend(message for message in after_errors if message not in before_errors)
        result.warnings.extend(message for message in after_warnings if message not in before_warnings)

        patterns = deduplicated(
            [*job.expected_outputs, *self.expected_output_patterns(node, job)]
        )
        if job.verification == "basic" and not result.cancelled:
            verification_patterns = self._verification_patterns(node, job, patterns)
            verification = verify_outputs(
                verification_patterns,
                started_at,
                self._expand_pattern,
            )
            result.output_paths.extend(verification.output_paths)
            result.warnings.extend(verification.warnings)
            result.errors.extend(verification.errors)
            result.success = result.success and verification.success

        result.errors = deduplicated(result.errors)
        result.warnings = deduplicated(result.warnings)
        result.output_paths = deduplicated(result.output_paths)
        if result.errors:
            result.success = False
        return result

    def _execute_native(self, node: Any, job: Job) -> Any:
        raise NotImplementedError

    def request_cancel(self, node: Any) -> bool:
        """Request native cancellation when an adapter exposes a suitable API."""
        return False

    def expected_output_patterns(self, node: Any, job: Job) -> list[str]:
        # Generic and custom actions have no reliable standard output contract.
        return []

    def planned_output_paths(self, node: Any, job: Job) -> list[str]:
        """Resolve expected paths before cooking so recovery can inspect them."""
        patterns = deduplicated(
            [*job.expected_outputs, *self.expected_output_patterns(node, job)]
        )
        patterns = self._verification_patterns(node, job, patterns)
        return deduplicated(self._expand_pattern(pattern) for pattern in patterns)

    def _expand_pattern(self, value: str) -> str:
        # Preserve frame tokens so verification can glob the full output sequence.
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
            pass
        for token, marker in tokens.items():
            protected = protected.replace(marker, token)
        return protected

    def _verification_patterns(
        self, node: Any, job: Job, patterns: list[str]
    ) -> list[str]:
        if not any("$F" in pattern or "<F" in pattern for pattern in patterns):
            return patterns
        frame_range = frame_range_for_job(job, self.hou)
        if frame_range is None:
            frame_range = self._node_frame_range(node)
        if frame_range is None:
            return patterns
        start, end, step = (int(value) for value in frame_range)
        return deduplicated(
            expand_frame_pattern(pattern, frame)
            for pattern in patterns
            for frame in frame_values(start, end, step)
        )

    def _node_frame_range(self, node: Any) -> tuple[float, float, float] | None:
        try:
            trange = node.parm("trange")
            if trange is not None and int(trange.eval()) != 0:
                return (
                    float(node.parm("f1").eval()),
                    float(node.parm("f2").eval()),
                    float(node.parm("f3").eval()),
                )
        except Exception:
            pass
        try:
            frame = float(self.hou.frame())
            return (frame, frame, 1.0)
        except Exception:
            return None


def parameter_output_patterns(node: Any, names: Iterable[str]) -> list[str]:
    patterns: list[str] = []
    for name in names:
        try:
            parm = node.parm(name)
        except Exception:
            parm = None
        if parm is None:
            continue
        try:
            value = parm.unexpandedString()
        except Exception:
            try:
                value = parm.evalAsString()
            except Exception:
                continue
        if value:
            patterns.append(str(value))
    return deduplicated(patterns)
