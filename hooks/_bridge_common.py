"""Shared helpers for the bridge hooks.

STDLIB ONLY. These scripts run from ~/.claude/settings.json with the system
Python (python3, or `py -3` on Windows — see hookinstall._command_for) on
every SessionStart / UserPromptSubmit / Stop / SessionEnd / Notification, so
they must start fast and never import the project package or third-party
libs.

Every hook is non-blocking: it writes a small file under paths.ROOT and exits.
The broker does everything else (topics, Telegram, injecting commands back into
the session over its [uds-messaging] socket).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# --------------------------------------------------------------------------
# paths (mirror of ai_session_telegram.paths, kept standalone on purpose)
# --------------------------------------------------------------------------

def root() -> Path:
    env = os.environ.get("AI_TG_BRIDGE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".ai-session-telegram"


ROOT = root()
REGISTER = ROOT / "register"
SESSIONS = ROOT / "sessions"
OUTBOX = ROOT / "outbox"
END = ROOT / "end"
BUSY = ROOT / "busy"          # <sid> present = a turn is in progress
PENDING = ROOT / "pending"    # <sid>.json = texts the broker just queued into Codex


def ensure_dirs() -> None:
    for d in (REGISTER, SESSIONS, OUTBOX, END, BUSY, PENDING):
        d.mkdir(parents=True, exist_ok=True)


def session_file(sid: str) -> Path:
    return SESSIONS / f"{sid}.json"


def mark_busy(sid: str) -> None:
    """A turn just started for this session."""
    BUSY.mkdir(parents=True, exist_ok=True)
    (BUSY / sid).write_text(ts())


def clear_busy(sid: str) -> None:
    """The turn finished (or the session ended)."""
    (BUSY / sid).unlink(missing_ok=True)


def queue_outbox(sid: str, role: str, text: str, *, ai_title: str = "") -> None:
    """Drop a message for the broker to deliver to this session's topic.
    role: "user" | "assistant" | "note". Filenames sort chronologically.
    ai_title, when set, carries Claude Code's own session title so the broker
    can name the topic without an LLM call of its own."""
    d = OUTBOX / sid
    d.mkdir(parents=True, exist_ok=True)
    name = f"{ts()}-{secrets.token_hex(2)}.json"
    item: dict = {"role": role, "text": text}
    if ai_title:
        item["ai_title"] = ai_title
    (d / name).write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# codex pending-injection tracking
#
# Codex CLI has no Claude-style "peer message" wrapper: a message the broker
# queues via `codex queue` arrives at UserPromptSubmit looking exactly like
# something the user typed. So codex_user_prompt_submit.py can't pattern-match
# a preamble like user_prompt_submit.py does for Claude; instead the broker
# (codex_inject.py) records the exact text it just queued here, and this
# consumes a matching entry so it isn't mirrored twice.
# --------------------------------------------------------------------------

_PENDING_TTL_S = 60  # keep in sync with codex_inject.py's writer


def consume_pending_injection(sid: str, prompt: str) -> bool:
    """True and removes the entry if `prompt` matches a message the broker just
    queued into this Codex session; stale entries are pruned along the way."""
    f = PENDING / f"{sid}.json"
    if not f.exists():
        return False
    with open(f, "a+", encoding="utf-8") as fh:
        if os.name == "nt":
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            items = json.loads(fh.read() or "[]")
        except json.JSONDecodeError:
            items = []
        now = time.time()
        items = [it for it in items if now - it.get("ts", 0) < _PENDING_TTL_S]
        found = False
        for i, it in enumerate(items):
            if it.get("text") == prompt:
                items.pop(i)
                found = True
                break
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(items, ensure_ascii=False))
    return found


# --------------------------------------------------------------------------
# hook io
# --------------------------------------------------------------------------

def read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def emit(obj: dict | None = None) -> None:
    """Print the hook's JSON result and exit 0."""
    sys.stdout.write(json.dumps(obj or {}, ensure_ascii=False))
    sys.stdout.flush()
    raise SystemExit(0)


# --------------------------------------------------------------------------
# transcript
# --------------------------------------------------------------------------

def last_assistant_text(transcript_path: str) -> str:
    """Join the text blocks of the final assistant message in the transcript."""
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return "(transcript unavailable)"

    best: list[str] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        content = msg.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    texts.append(blk.get("text", ""))
        texts = [t for t in texts if t.strip()]
        if texts:
            best = texts  # keep overwriting -> ends on the last one
    return "\n\n".join(best) if best else "(no text in final response)"


def last_ai_title(transcript_path: str) -> str:
    """Claude Code's own most-recent session title, or "" if none yet.

    Claude Code writes `{"type":"ai-title","aiTitle":"..."}` lines into the
    transcript once it has named the conversation. We forward the latest so the
    broker can title the Telegram topic with it."""
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return ""
    title = ""
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or '"ai-title"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "ai-title" and obj.get("aiTitle"):
            title = str(obj["aiTitle"])
    return title


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def ts() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}"


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
