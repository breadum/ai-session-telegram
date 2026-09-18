"""The shared cross-platform primitives (is_alive, locked) that broker.py,
cli.py, and codex_inject.py all import instead of branching os.name themselves.
"""

from __future__ import annotations

import fcntl
import os
import platform

from ai_session_telegram import _procutil


def test_is_alive_true_for_current_process():
    assert _procutil.is_alive(os.getpid()) is True


def test_is_alive_false_for_a_pid_that_does_not_exist():
    # PIDs wrap around well below this on every real system.
    assert _procutil.is_alive(2**30) is False


def test_is_alive_windows_branch_uses_tasklist(monkeypatch):
    monkeypatch.setattr(_procutil.os, "name", "nt")

    class _Result:
        stdout = "python.exe   4242 Console  1   12,345 K"

    monkeypatch.setattr(_procutil.subprocess, "run", lambda *a, **k: _Result())
    assert _procutil.is_alive(4242) is True

    class _EmptyResult:
        stdout = "INFO: No tasks matching the given criteria.\n"

    monkeypatch.setattr(_procutil.subprocess, "run", lambda *a, **k: _EmptyResult())
    assert _procutil.is_alive(4242) is False


def test_locked_takes_and_releases_an_exclusive_flock(tmp_path, monkeypatch):
    if platform.system() == "Windows":
        return  # fcntl doesn't exist there; the nt branch is covered separately
    calls = []
    real_flock = fcntl.flock

    def spying_flock(fh, op):
        calls.append(op)
        return real_flock(fh, op)

    monkeypatch.setattr(_procutil.fcntl, "flock", spying_flock)

    with open(tmp_path / "lock", "w") as fh, _procutil.locked(fh):
        assert calls == [fcntl.LOCK_EX]
    assert calls == [fcntl.LOCK_EX, fcntl.LOCK_UN]


def test_locked_releases_even_if_the_block_raises(tmp_path):
    with open(tmp_path / "lock", "w") as fh:
        try:
            with _procutil.locked(fh):
                raise ValueError("boom")
        except ValueError:
            pass
        # a second lock attempt on a fresh handle must not hang/fail if the
        # first one was released.
        with open(tmp_path / "lock", "w") as fh2, _procutil.locked(fh2):
            pass
