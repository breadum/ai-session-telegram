#!/usr/bin/env python3
"""Stop hook (Codex CLI): mirror the turn's final response to Telegram.

Codex's Stop payload carries the reply directly as `last_assistant_message` —
no transcript file to reopen and parse, unlike Claude Code's Stop hook.
"""

from __future__ import annotations

import _bridge_common as bc


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    if sid:
        bc.clear_busy(sid)  # the turn is done
    # Only act for sessions the broker has a topic for. A session that started
    # before `bridge install-hooks --agent codex` has no record here -> stay silent.
    if not sid or not bc.session_file(sid).exists():
        bc.emit()

    text = ev.get("last_assistant_message") or "(no text in final response)"
    bc.queue_outbox(sid, "assistant", text)
    bc.emit()


if __name__ == "__main__":
    main()
