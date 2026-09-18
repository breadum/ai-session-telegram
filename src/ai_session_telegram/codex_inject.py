"""Inject a message into a running Codex CLI session via `codex queue`.

Unlike Claude Code 2.x, Codex sessions don't hand out a per-session socket:
every session registers with one shared local app-server daemon, and
``codex queue --thread <session-id> --message <text>`` talks to that daemon
directly. So there's no socket/token to capture at SessionStart — the session
id alone is enough, and this is just a subprocess call.

Confirmed live (see the design discussion, not just docs): queuing into an
idle interactive session starts a new turn immediately, with no keypress.

One real difference from Claude's uds-messaging socket: the queued message
arrives at `UserPromptSubmit` completely indistinguishable from something the
user typed (no wrapper, no origin field). So before calling `codex queue` this
also drops a marker under paths.PENDING that codex_user_prompt_submit.py
consumes to skip re-mirroring its own echo — see _bridge_common.py's
`consume_pending_injection` for the reader half of this.
"""

from __future__ import annotations

import json
import subprocess
import time

from . import paths
from ._procutil import locked

_PENDING_TTL_S = 60  # keep in sync with hooks/_bridge_common.py's reader


class CodexInjectError(Exception):
    """`codex queue` failed, timed out, or the CLI isn't on PATH."""


def _queue_pending(sid: str, text: str) -> None:
    f = paths.pending_file(sid)
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a+") as fh, locked(fh):
        fh.seek(0)
        try:
            items = json.loads(fh.read() or "[]")
        except json.JSONDecodeError:
            items = []
        now = time.time()
        items = [it for it in items if now - it.get("ts", 0) < _PENDING_TTL_S]
        items.append({"text": text, "ts": now})
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(items, ensure_ascii=False))


def inject_codex_message(sid: str, text: str, *, timeout: float = 10.0) -> None:
    """Queue one message for the Codex session `sid`.

    Raises :class:`CodexInjectError` if the `codex` binary is missing, the
    call times out, or the daemon rejects it (e.g. unknown thread). Records
    the text as pending first so the echoed UserPromptSubmit isn't mirrored
    a second time, even if the subprocess call itself then fails.
    """
    _queue_pending(sid, text)
    try:
        proc = subprocess.run(
            ["codex", "queue", "--thread", sid, "--message", text],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise CodexInjectError("codex CLI not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise CodexInjectError(f"codex queue timed out after {timeout}s") from e
    if proc.returncode != 0:
        raise CodexInjectError(
            (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        )
