#!/usr/bin/env python3
"""Mirror agent task prompts as assistant messages at the dispatch event."""

from __future__ import annotations

import _bridge_common as bc


def main() -> None:
    ev = bc.read_event()
    if ev.get("tool_name") not in {"Agent", "Task", "spawn_agent"}:
        bc.emit()
        return
    sid = ev.get("session_id")
    tool_input = ev.get("tool_input")
    if not isinstance(sid, str) or not isinstance(tool_input, dict):
        bc.emit()
        return
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        prompt = tool_input.get("message")
    if not isinstance(prompt, str):
        prompt = ""
    prompt = prompt.strip()
    if not prompt or not (
        bc.session_file(sid).exists() or (bc.REGISTER / f"{sid}.json").exists()
    ):
        bc.emit()
        return

    bc.queue_pending(sid, prompt, match="exact")
    bc.queue_outbox(sid, "assistant", prompt)
    bc.emit()


if __name__ == "__main__":
    main()
