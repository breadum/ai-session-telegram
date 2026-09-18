"""Injecting into a Codex CLI session via `codex queue`."""

from __future__ import annotations

import json
import subprocess

import pytest

from claude_bridge_telegram import paths
from claude_bridge_telegram.codex_inject import CodexInjectError, inject_codex_message


def _ok(cmd, **kwargs):
    return subprocess.CompletedProcess(cmd, 0, stdout="Queued message x for thread y.\n", stderr="")


def test_inject_calls_codex_queue_with_thread_and_message(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _ok(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    inject_codex_message("sid-1", "run the tests")

    assert calls == [["codex", "queue", "--thread", "sid-1", "--message", "run the tests"]]


def test_inject_records_pending_before_calling_codex(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _ok)
    inject_codex_message("sid-2", "hello")

    items = json.loads(paths.pending_file("sid-2").read_text())
    assert items[0]["text"] == "hello"


def test_inject_records_pending_even_if_codex_call_then_fails(monkeypatch):
    def boom(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(CodexInjectError):
        inject_codex_message("sid-3", "hello")

    items = json.loads(paths.pending_file("sid-3").read_text())
    assert items[0]["text"] == "hello"


def test_inject_raises_on_nonzero_exit(monkeypatch):
    def fail(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no thread named sid-4")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(CodexInjectError, match="no thread named sid-4"):
        inject_codex_message("sid-4", "hi")


def test_inject_raises_when_codex_missing(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(CodexInjectError):
        inject_codex_message("sid-5", "hi")


def test_inject_raises_on_timeout(monkeypatch):
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 10))

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(CodexInjectError):
        inject_codex_message("sid-6", "hi")
