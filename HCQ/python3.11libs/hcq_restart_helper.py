"""Wait for Houdini to exit, optionally install HCQ, then relaunch Houdini."""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
from pathlib import Path


SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102


def wait_for_process(pid: int, timeout_ms: int = 120_000) -> bool:
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return True
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout_ms))
        return result == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def relaunch(
    *,
    wait_pid: int,
    executable: str,
    hip_file: str = "",
    installer: str = "",
    timeout_ms: int = 120_000,
) -> int:
    if not wait_for_process(wait_pid, timeout_ms):
        return 2
    if installer:
        result = subprocess.run(
            [
                installer,
                "/CURRENTUSER",
                "/SILENT",
                "/NORESTART",
                "/NOCLOSEAPPLICATIONS",
            ],
            check=False,
        )
        if result.returncode != 0:
            return int(result.returncode or 3)
    arguments = [executable]
    if hip_file:
        arguments.append(hip_file)
    subprocess.Popen(arguments, close_fds=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait-pid", type=int, required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--hip-file", default="")
    parser.add_argument("--installer", default="")
    parser.add_argument("--timeout-ms", type=int, default=120_000)
    arguments = parser.parse_args()
    executable = str(Path(arguments.executable).resolve())
    installer = (
        str(Path(arguments.installer).resolve()) if arguments.installer else ""
    )
    return relaunch(
        wait_pid=arguments.wait_pid,
        executable=executable,
        hip_file=arguments.hip_file,
        installer=installer,
        timeout_ms=arguments.timeout_ms,
    )


if __name__ == "__main__":
    raise SystemExit(main())
