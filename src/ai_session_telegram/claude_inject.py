"""Inject a message into a running Claude Code session.

Claude Code 2.x listens on a per-session Unix socket (its ``[uds-messaging]``
inbox) at ``$CLAUDE_CODE_MESSAGING_SOCKET`` — ``$XDG_RUNTIME_DIR/cc-socks/<pid>.sock``.
A client authenticates with ``$CLAUDE_CODE_MESSAGING_TOKEN`` and then writes
newline-delimited JSON frames. A ``user`` frame is routed into the session's
prompt queue whether the session is mid-turn or idle — which is exactly how the
bridge delivers a Telegram message to the session, with no blocking hook.

The session receives it as a *peer* message (same channel used between local
Claude sessions), not a first-person user prompt: it will not dismiss a native
tool-permission prompt. Sessions driven from Telegram should run with
``--dangerously-skip-permissions`` (or an equivalent trusted permission mode).
"""

from __future__ import annotations

import json
import logging
import socket

from . import paths

log = logging.getLogger("bridge.claude_inject")


class InjectError(Exception):
    """The session socket was missing, unreachable, or refused the frame."""


def inject_user_message(
    sid: str,
    sock_path: str,
    token: str,
    text: str,
    *,
    timeout: float = 3.0,
) -> None:
    """Send one ``user`` message to the session ``sid``, listening on ``sock_path``.

    Raises :class:`InjectError` if the socket is gone (session exited/restarted)
    or the write fails. Returns None on success. The server sends no reply on
    this connection, so success means "written and accepted without error".

    Records `text` as pending first (paths.queue_pending) so the echoed
    UserPromptSubmit — Claude Code wraps a peer-injected message before the
    hook sees it, so hooks/_bridge_common.py's consume_pending_injection
    matches on substring, not the exact original text — isn't mirrored back
    into the topic a second time, even if the socket write below then fails.
    """
    if not sock_path or not token:
        raise InjectError("missing socket path or token for this session")

    paths.queue_pending(sid, text)

    af_unix = getattr(socket, "AF_UNIX", None)
    if af_unix is None:
        # Confirmed missing on GitHub's windows-latest Python 3.12 build (no
        # AF_UNIX support compiled in), so this isn't just theoretical.
        raise InjectError(
            "this platform's socket module has no AF_UNIX — "
            "Claude Code message injection isn't available here"
        )

    auth = json.dumps({"type": "auth", "token": token})
    frame = json.dumps(
        {"type": "user", "message": {"role": "user", "content": text}}
    )

    s = socket.socket(af_unix, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        try:
            s.connect(sock_path)
            s.sendall(auth.encode() + b"\n")
            s.sendall(frame.encode() + b"\n")
        except OSError as e:
            raise InjectError(f"{sock_path}: {e}") from e

        # The message is already delivered at this point — both sendall()s
        # returned without error. Everything past here is best-effort
        # teardown: if the server closes its end the moment it's read the
        # frame, shutdown()/recv() could raise even though delivery already
        # succeeded, and treating that as InjectError would make the broker
        # re-queue and re-inject an already-delivered message. (The actual
        # duplicate-delivery bug this project hit turned out to be the
        # UserPromptSubmit peer-detection heuristic missing real peer
        # messages, not this — see queue_pending above/consume_pending_injection
        # — but this teardown boundary was still wrong on its own merits.)
        try:
            s.shutdown(socket.SHUT_WR)
            while s.recv(4096):
                pass
        except OSError as e:
            log.debug("post-send teardown on %s: %s (delivery still succeeded)", sock_path, e)
    finally:
        s.close()
