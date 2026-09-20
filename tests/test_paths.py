"""Runtime directory layout: env override, ensure_dirs, path helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ai_session_telegram import paths


def test_root_env_override(monkeypatch):
    monkeypatch.setenv("AI_TG_BRIDGE_HOME", "/tmp/somewhere-else")
    assert paths._root() == Path("/tmp/somewhere-else")


def test_root_default_when_unset(monkeypatch):
    monkeypatch.delenv("AI_TG_BRIDGE_HOME", raising=False)
    assert paths._root() == Path.home() / ".ai-session-telegram"


def test_root_expands_user(monkeypatch):
    monkeypatch.setenv("AI_TG_BRIDGE_HOME", "~/somewhere-else")
    assert paths._root() == Path.home() / "somewhere-else"


def test_ensure_dirs_creates_everything(bridge_home):
    for d in paths.ALL_DIRS:
        assert d.is_dir()


def test_helper_paths_are_relative_to_root():
    assert paths.inbox_file("abc") == paths.INBOX / "abc.jsonl"
    assert paths.outbox_dir("abc") == paths.OUTBOX / "abc"
    assert paths.session_file("abc") == paths.SESSIONS / "abc.json"
    assert paths.thread_file(42) == paths.THREADS / "42"
    assert paths.thread_file("42") == paths.THREADS / "42"
    assert paths.busy_file("abc") == paths.BUSY / "abc"
    assert paths.pending_file("abc") == paths.PENDING / "abc.json"


def test_queue_pending_appends_and_prunes_stale(bridge_home):
    paths.queue_pending("sid1", "one")
    paths.queue_pending("sid1", "two")

    items = json.loads(paths.pending_file("sid1").read_text(encoding="utf-8"))
    assert [it["text"] for it in items] == ["one", "two"]

    # a stale entry from a previous run gets pruned on the next write
    stale = {"text": "old", "ts": time.time() - 999}
    fresh = json.loads(paths.pending_file("sid1").read_text(encoding="utf-8"))
    paths.pending_file("sid1").write_text(
        json.dumps([stale, *fresh]), encoding="utf-8"
    )
    paths.queue_pending("sid1", "three")
    items = json.loads(paths.pending_file("sid1").read_text(encoding="utf-8"))
    assert [it["text"] for it in items] == ["one", "two", "three"]
