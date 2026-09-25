#!/usr/bin/env python3
"""UserPromptSubmit hook (Codex CLI): mirror the user's prompt into the topic.

Together with the Stop hook (which mirrors Codex's reply) this puts the whole
back-and-forth in Telegram. Fast and non-blocking — just drops a file.

Codex has no Claude-style peer-message wrapper: a message the broker injected
via `codex queue` arrives here looking exactly like something the user typed
(same event, no origin field, no preamble text). So instead of pattern-matching
a wrapper, `consume_pending_injection` checks the marker codex_inject.py left
right before calling `codex queue` — if it matches, this is our own echo, skip
the mirror but still mark the turn busy.
"""

from __future__ import annotations

import _bridge_common as bc


def _looks_like_agent_handoff(prompt: str) -> bool:
    """Recognize Codex's AI-generated agent handoff prompts.

    Codex exposes these through UserPromptSubmit using the same payload shape
    as a human prompt.  There is no origin field to use, so keep the rule
    deliberately narrow: an explicit "you are ... agent" instruction is an
    AI handoff, not an ordinary user message.
    """
    folded = prompt.casefold().lstrip()
    if folded.startswith("🐮 저장소 "):
        return True
    starts_as_role = folded.startswith(("당신은 ", "you are "))
    return starts_as_role and ("agent" in folded or "에이전트" in folded)


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    prompt = (ev.get("prompt") or "").strip()
    if not sid or not prompt:
        bc.emit()
    # act if the session is registered, or registration is still pending
    # (SessionStart fired, broker hasn't made the topic yet)
    if bc.session_file(sid).exists() or (bc.REGISTER / f"{sid}.json").exists():
        bc.mark_busy(sid)  # a turn is now running; Stop clears it
        if not bc.consume_pending_injection(sid, prompt):
            role = "assistant" if _looks_like_agent_handoff(prompt) else "user"
            bc.queue_outbox(sid, role, prompt)
    bc.emit()


if __name__ == "__main__":
    main()
