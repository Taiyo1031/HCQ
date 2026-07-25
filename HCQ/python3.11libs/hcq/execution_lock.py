"""Cross-process run lock for Windows Houdini sessions."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import BinaryIO


class ExecutionLockError(RuntimeError):
    pass


class ExecutionLock:
    _guard = threading.Lock()
    _owned = False

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._stream: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        return self._stream is not None

    def acquire(self) -> None:
        with self._guard:
            if ExecutionLock._owned:
                raise ExecutionLockError("Another HCQ run session is active in this process.")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            stream = self.path.open("a+b")
            stream.seek(0)
            if stream.read(1) == b"":
                stream.seek(0)
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name != "nt":
                    raise ExecutionLockError("HCQ 1.0 supports Windows only.")
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except (OSError, ExecutionLockError) as exc:
                stream.close()
                raise ExecutionLockError("Another HCQ run session is active.") from exc
            self._stream = stream
            ExecutionLock._owned = True

    def release(self) -> None:
        with self._guard:
            if self._stream is None:
                return
            try:
                import msvcrt

                self._stream.seek(0)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self._stream.close()
                self._stream = None
                ExecutionLock._owned = False

    def __enter__(self) -> "ExecutionLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
