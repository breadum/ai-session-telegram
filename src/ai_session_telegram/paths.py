"""Runtime directory layout for the bridge.

All mutable state lives under ~/.ai-session-telegram (override with AI_TG_BRIDGE_HOME),
kept separate from the code checkout so the daemon and hooks share one location.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ._procutil import locked


def _root() -> Path:
    env = os.environ.get("AI_TG_BRIDGE_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".ai-session-telegram"


ROOT = _root()

STATE = ROOT / "state"
OFFSET_FILE = STATE / "offset"
PID_FILE = STATE / "broker.pid"
LOG_FILE = STATE / "broker.log"
STOP_FLAG = STATE / "stop"        # touched by `bridge stop` on Windows, where a
                                   # signal can't ask the broker to shut down gracefully

REGISTER = ROOT / "register"      # session_start drops <sid>.json here
SESSIONS = ROOT / "sessions"      # broker writes <sid>.json (label, thread_id, socket, ...)
THREADS = ROOT / "threads"        # <thread_id> -> file whose content is the sid
INBOX = ROOT / "inbox"            # <sid>.jsonl : commands that failed to inject, awaiting retry
OUTBOX = ROOT / "outbox"          # <sid>/<ts>.json : queued outbound messages
END = ROOT / "end"                # session_end drops <sid>.json here
BUSY = ROOT / "busy"              # <sid> present : a turn is in progress
PENDING = ROOT / "pending"        # <sid>.json : known prompts already mirrored to Telegram,
                                   # awaiting their UserPromptSubmit echo

ALL_DIRS = [STATE, REGISTER, SESSIONS, THREADS, INBOX, OUTBOX, END, BUSY, PENDING]


def ensure_dirs() -> None:
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


def inbox_file(sid: str) -> Path:
    return INBOX / f"{sid}.jsonl"


def outbox_dir(sid: str) -> Path:
    return OUTBOX / sid


def session_file(sid: str) -> Path:
    return SESSIONS / f"{sid}.json"


def thread_file(thread_id: int | str) -> Path:
    return THREADS / str(thread_id)


def busy_file(sid: str) -> Path:
    return BUSY / sid


def pending_file(sid: str) -> Path:
    return PENDING / f"{sid}.json"


_PENDING_TTL_S = 60  # keep in sync with hooks/_bridge_common.py's reader


def queue_pending(sid: str, text: str, *, match: str = "substring") -> None:
    """Record `text` as a known prompt so its UserPromptSubmit echo is not
    mirrored into the topic again. The default substring match handles Claude
    wrappers; use exact matching for Codex and agent dispatch prompts.
    """
    f = pending_file(sid)
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a+", encoding="utf-8") as fh, locked(fh):
        fh.seek(0)
        try:
            items = json.loads(fh.read() or "[]")
        except json.JSONDecodeError:
            items = []
        now = time.time()
        items = [it for it in items if now - it.get("ts", 0) < _PENDING_TTL_S]
        items.append({"text": text, "ts": now, "match": match})
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(items, ensure_ascii=False))
