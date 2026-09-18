#!/usr/bin/env python3
"""SessionStart hook (Codex CLI): register the session so the broker creates a
Telegram topic.

Unlike Claude Code, Codex hands out no per-session socket/token to capture —
delivery back into the session is `codex queue --thread <sid> --message ...`
(see codex_inject.py), which only needs the session id. So this just records
who/where the session is.

Note: an interactive `codex` session doesn't create its thread — and doesn't
fire this hook — until the *first* prompt is submitted, unlike Claude Code
which fires SessionStart at launch. The topic shows up a beat later than it
would for a Claude session; that's expected, not a bug.
"""

from __future__ import annotations

import os

import _bridge_common as bc


def _clean(s: str) -> str:
    return "".join(ch for ch in s if ch.isprintable() and ch not in "\r\n")


def cwd_base(cwd: str) -> str:
    return _clean(os.path.basename(cwd.rstrip("/")) or "session")[:60]


def main() -> None:
    ev = bc.read_event()
    sid = ev.get("session_id") or ""
    cwd = ev.get("cwd") or os.getcwd()
    if not sid:
        bc.emit()

    bc.ensure_dirs()
    base = cwd_base(cwd)
    bc.write_json_atomic(
        bc.REGISTER / f"{sid}.json",
        {
            "session_id": sid,
            "kind": "codex",
            "label": f"{base}-{sid[:4]}"[:120],
            "base": base,
            "cwd": cwd,
            "source": ev.get("source"),
            "ts": bc.ts(),
        },
    )
    bc.emit()


if __name__ == "__main__":
    main()
