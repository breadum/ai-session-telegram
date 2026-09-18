"""Merge (and unmerge) the bridge's hook entries into an agent's hook config.

Driven by `bridge install-hooks` / `bridge uninstall-hooks` (optionally with
`--agent codex` / `--agent all`). Existing hook entries — ours or anyone
else's — are left untouched; ours are identified by the absolute path of the
hooks/ directory in this checkout. A timestamped backup of the settings file
is written before any change.

Claude Code and Codex CLI both keep hooks as `{"hooks": {EventName: [{"hooks":
[{"type": "command", "command": ..., "timeout": ...}]}]}}` — Claude's live
under a `hooks` key inside the much larger `~/.claude/settings.json`, Codex's
is a dedicated `~/.codex/hooks.json` — so one pair of install/uninstall
functions covers both; only the target path and the event->script map differ.

Codex additionally gates each hook behind a one-time trust prompt (or
`--dangerously-bypass-hook-trust` per invocation) keyed by a content hash this
installer doesn't attempt to pre-compute — see the printed note after install.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
CODEX_SETTINGS = Path.home() / ".codex" / "hooks.json"

# event name -> (hook script filename, hook timeout in seconds or None for default)
# Every hook is non-blocking: it drops a file under paths.ROOT and exits, so the
# default timeout is plenty.
CLAUDE_HOOKS = {
    "SessionStart": ("session_start.py", None),
    "UserPromptSubmit": ("user_prompt_submit.py", None),
    "Stop": ("stop.py", None),
    "SessionEnd": ("session_end.py", None),
    "Notification": ("notification.py", None),
}

CODEX_HOOKS = {
    "SessionStart": ("codex_session_start.py", None),
    "UserPromptSubmit": ("codex_user_prompt_submit.py", None),
    "Stop": ("codex_stop.py", None),
    "SessionEnd": ("codex_session_end.py", None),
    "PermissionRequest": ("codex_permission_request.py", None),
}


def _hooks_dir() -> Path:
    # src/claude_bridge_telegram/hookinstall.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2] / "hooks"


def _command_for(script: str) -> str:
    # hooks are stdlib-only: run with the system python3, not the project venv,
    # so they start fast and don't depend on uv being on PATH.
    return f"python3 {_hooks_dir() / script}"


def _load(settings: Path) -> dict:
    if settings.exists():
        return json.loads(settings.read_text())
    return {}


def _backup(settings: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = settings.with_name(f"{settings.name}.bak-{stamp}")
    shutil.copy2(settings, dst)
    return dst


def _is_ours(entry: dict) -> bool:
    hd = str(_hooks_dir())
    for h in entry.get("hooks", []):
        if hd in h.get("command", ""):
            return True
    return False


def _install(settings: Path, hook_map: dict[str, tuple[str, int | None]]) -> None:
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{}\n")
    print(f"backup: {_backup(settings)}")
    data = _load(settings)
    hooks = data.setdefault("hooks", {})

    for event, (script, timeout) in hook_map.items():
        groups = hooks.setdefault(event, [])
        groups[:] = [g for g in groups if not _is_ours(g)]  # drop stale versions
        hook_entry: dict = {"type": "command", "command": _command_for(script)}
        if timeout is not None:
            hook_entry["timeout"] = timeout
        groups.append({"hooks": [hook_entry]})
        print(f"  + {event}: {_command_for(script)}"
              + (f"  (timeout {timeout}s)" if timeout else ""))

    settings.write_text(json.dumps(data, indent=2) + "\n")


def _uninstall(settings: Path, hook_map: dict[str, tuple[str, int | None]]) -> None:
    if not settings.exists():
        print(f"no {settings}")
        return
    print(f"backup: {_backup(settings)}")
    data = _load(settings)
    hooks = data.get("hooks", {})
    removed = 0
    for event in hook_map:
        groups = hooks.get(event, [])
        before = len(groups)
        groups[:] = [g for g in groups if not _is_ours(g)]
        removed += before - len(groups)
        if not groups:
            hooks.pop(event, None)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    print(f"removed {removed} hook group(s) from {settings}.")


def install() -> None:
    """Install the Claude Code hooks (~/.claude/settings.json)."""
    _install(CLAUDE_SETTINGS, CLAUDE_HOOKS)
    print("done. New Claude Code sessions will use the bridge.")


def uninstall() -> None:
    _uninstall(CLAUDE_SETTINGS, CLAUDE_HOOKS)


def install_codex() -> None:
    """Install the Codex CLI hooks (~/.codex/hooks.json)."""
    _install(CODEX_SETTINGS, CODEX_HOOKS)
    print(
        "done. New Codex sessions will use the bridge, once you trust these hooks:\n"
        "  Codex gates freshly-added hooks behind a one-time trust prompt. Either\n"
        "  approve them interactively on next launch, or start the session with\n"
        "  `codex --dangerously-bypass-hook-trust` to skip that prompt."
    )


def uninstall_codex() -> None:
    _uninstall(CODEX_SETTINGS, CODEX_HOOKS)
