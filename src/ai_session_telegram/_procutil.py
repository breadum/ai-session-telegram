"""Cross-platform process-liveness check and exclusive file locking.

broker.py, cli.py, and codex_inject.py all need both; centralized here so the
os.name branch exists in exactly one place instead of being repeated at every
call site. hooks/_bridge_common.py can't use this — hooks must stay
standalone stdlib and never import the project package (see CLAUDE.md) — so
it keeps its own small inline branch for the one lock it needs.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from typing import IO

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def is_alive(pid: int) -> bool:
    if os.name == "nt":
        # os.kill on Windows ignores the signal value and calls TerminateProcess
        # outright — there is no signal-0 probe, so shell out to tasklist instead.
        result = subprocess.run(
            ["tasklist", "/nh", "/fi", f"PID eq {pid}"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def locked(fh: IO):
    """Exclusive-lock an already-open file handle for the block's duration.

    Works on a handle opened in text or binary mode, since locking operates
    on the underlying fd either way. Windows allows locking a byte range
    beyond the current end of file, so this doesn't need special-casing for
    a freshly created/empty file.
    """
    if os.name == "nt":
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(fh, fcntl.LOCK_EX)
    try:
        yield
    finally:
        if os.name == "nt":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh, fcntl.LOCK_UN)
