#!/usr/bin/env python3
"""PermissionRequest hook (Codex CLI): mirror "the session wants your
attention" to the topic — the closest Codex equivalent of Claude Code's
Notification hook.

Codex has no idle-nudge event to filter out here (there's no "waiting for
your input" notification the way Claude Code has) — PermissionRequest only
fires when the model actually wants approval for something, so every payload
here is worth forwarding.

The exact payload shape wasn't nailed down against Codex's own source, so this
reads defensively across the field names a permission/approval prompt is
plausibly carried under and drops the event if none of them have text.
"""

from __future__ import annotations

import _bridge_common as bc

_TEXT_FIELDS = ("message", "reason", "description", "command", "title")


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    if not sid or not bc.session_file(sid).exists():
        bc.emit()

    msg = ""
    for k in _TEXT_FIELDS:
        v = ev.get(k)
        if isinstance(v, str) and v.strip():
            msg = v.strip()
            break
    if not msg:
        bc.emit()

    bc.queue_outbox(sid, "event", msg)
    bc.emit()


if __name__ == "__main__":
    main()
