"""Small cross-process lock shared by the updater and startup bootstrap."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import BinaryIO


class UpdateLockError(RuntimeError):
    pass


class UpdateFileLock:
    _guard = threading.Lock()
    _owned_paths: set[str] = set()

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._stream: BinaryIO | None = None
        self._key = os.path.normcase(str(self.path.resolve()))

    def acquire(self) -> None:
        with self._guard:
            if self._key in self._owned_paths:
                raise UpdateLockError("Another HCQ update operation is active.")
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
                    raise UpdateLockError(
                        "HCQ automatic updates are supported on Windows only."
                    )
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except (OSError, UpdateLockError) as error:
                stream.close()
                raise UpdateLockError(
                    "Another HCQ update operation is active."
                ) from error
            self._stream = stream
            self._owned_paths.add(self._key)

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
                self._owned_paths.discard(self._key)

    def __enter__(self) -> "UpdateFileLock":
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
