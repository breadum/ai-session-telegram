# CLAUDE.md — working rules for this repo

Guidance for anyone (human, Claude Code, or Codex) changing `ai-session-telegram`.
Read this before editing. It records the invariants that are easy to break.

## What this is

A bridge between Claude Code (and Codex CLI) sessions and a Telegram forum
group: one **topic per session**, prompts + responses mirrored out, and
Telegram messages injected back into the running session. No web service, no
database — a single broker daemon plus a handful of stdlib hooks per agent,
talking through files.

Both agents share the same file-queue contract and broker code; a session
record's `"kind": "claude" | "codex"` field is the only thing that changes how
it's handled (delivery mechanism, hook payload shape). Absent `kind` means
`"claude"` — every record predates Codex support.

## Architecture (do not break these)

1. **Hooks are stdlib-only and non-blocking.** Claude's `hooks/*.py` run from
   `~/.claude/settings.json`, Codex's `hooks/codex_*.py` from
   `~/.codex/hooks.json` — both with the *system* `python3`, on every session
   event.
   - No third-party imports. No `import ai_session_telegram`. `_bridge_common.py`
     is a deliberate standalone mirror of `paths.py` — keep them in sync by hand;
     do not merge them. Both agents' hooks share this one file.
   - A hook writes one small file under `paths.ROOT` and calls `bc.emit()`. It
     must never block, poll, or wait. (The old `Stop` hook blocked for minutes;
     that is gone and must not come back.)

2. **The broker is the only thing that talks to Telegram.** It owns the
   `getUpdates` offset, so nothing else may call the Bot API — concurrent
   sessions would race the offset.

3. **Telegram → session goes over an agent-specific channel**, not a hook.
   - **Claude**: `session_start.py` records `CLAUDE_CODE_MESSAGING_SOCKET` +
     `CLAUDE_CODE_MESSAGING_TOKEN` (inherited from the `claude` parent) into the
     register file; `claude_inject.py` connects to that `[uds-messaging]` socket, sends
     an `auth` frame then a `user` frame. This works whether the session is idle
     or mid-turn.
     - The session receives it as a **peer message**, not a first-person user
       prompt. Two setup requirements follow (neither is a bug to fix in the bridge):
       1. `~/.claude/settings.json` must set `"crossSessionInbound": "accept"`.
          Otherwise Claude Code *holds* peer messages from an unattested sender
          when the receiving session bypasses prompts — the socket write succeeds
          but the message never reaches the model (it lands in the transcript as a
          "Held peer message" system notice).
       2. Telegram-driven sessions must run with `--dangerously-skip-permissions`
          (or an equivalent trusted mode). A peer message will *not* dismiss a
          native tool-permission dialog.
   - **Codex**: no socket to capture — every Codex session registers with one
     shared local app-server daemon, so `codex_inject.py` just shells out
     `codex queue --thread <sid> --message <text>` (confirmed live: this starts
     a new turn immediately in an idle session, no keypress). Unlike Claude's
     peer message, Codex has **no wrapper** distinguishing an injected prompt
     from a typed one at `UserPromptSubmit` — so `codex_inject.py` drops a
     marker in `paths.PENDING` right before calling `codex queue`, and
     `codex_user_prompt_submit.py` (via `_bridge_common.consume_pending_injection`)
     checks it instead of pattern-matching text. Codex sessions also need
     `--dangerously-bypass-hook-trust` (or one-time interactive trust) before
     the bridge's hooks run at all — see `hookinstall.install_codex`.

4. **File-queue contract between hook and broker:**
   - `register/<sid>.json` — session_start → broker makes/refreshes a topic.
     Carries `"kind": "claude" | "codex"`; the broker copies it onto the
     session record and it's `kind` that drives every fork below, including
     the topic's icon color (`broker.ICON_COLOR`) — the only cue that survives
     once an `ai_title`/`/title` overwrites the `[codex] ` prefix in the name.
   - `sessions/<sid>.json` — broker's record (kind, label, thread_id, socket,
     token, status, titled)
   - `outbox/<sid>/<ts>.json` — `{"role": "user"|"assistant"|"note"|"event", "text": ...}`,
     optional `"ai_title"` (Claude Code's own session title, forwarded by the
     `Stop` hook — the broker renames the topic to it once) → broker sends to the topic.
     `event` (🔔) is what `notification.py` / `codex_permission_request.py`
     queues when the session wants attention, and what `tidy_prompt` downgrades
     machine turns to.
   - `inbox/<sid>.jsonl` — commands that *failed* to inject, retried each loop
   - `busy/<sid>` — present between `UserPromptSubmit` and `Stop`: a turn is
     running. `/status` reads it; a message sent while it exists gets a
     "queued behind the current turn" note. mtime = turn start.
   - `end/<sid>.json` — session_end → broker marks ended / deletes topic
   - `pending/<sid>.json` — Codex only: texts `codex_inject.py` just queued,
     awaiting the `UserPromptSubmit` echo (see item 3). TTL-pruned, never read
     by Claude sessions.
   Change the `outbox` JSON shape and you must change both the hook that writes
   it (`_bridge_common.queue_outbox`) and `broker._read_outbox_item`.

5. **Mirrored message bodies go out as Telegram HTML.** `render.to_telegram_html`
   maps Claude's Markdown onto Telegram's tag subset; `_process_outbox` sends it
   with `parse_mode="HTML"`. `telegram.send_message` retries a chunk tag-stripped
   if Telegram rejects the markup, so a converter bug un-styles a message but
   never drops it. The bridge's *own* messages (`_say`, topic header) stay plain
   — don't pass `parse_mode` for those unless you also escape them.

6. **`UserPromptSubmit` also fires for machine turns** — a finished background
   task, a locally-run slash command, injected context blocks. `render.tidy_prompt`
   (called in `_process_outbox` for `role == "user"`) rewrites the ones worth
   showing into a one-line `event` (🔔) and returns `None` for pure noise, which
   the broker then drops. Add a pattern there, not in the hook.
   - **The one exception is the Telegram echo:** a message the user sent from the
     topic fires `UserPromptSubmit` too (Claude Code delivered the broker's
     injection, wrapped in an "Another Claude session sent a message:" preamble).
     `user_prompt_submit.py` drops it *before* queuing (still marks the turn
     busy); `tidy_prompt` has the same prefix check as a backstop. Without this
     every Telegram message double-posts in its topic. Codex has no such
     wrapper to match against — see the `pending/` mechanism in items 3 and 4.

## Secrets

- The Telegram bot token lives **only** in `~/.ai-session-telegram/config.json`
  (chmod 600), written by `bridge setup`. It is never in the repo.
- `messaging_token` is a per-session Claude Code secret. It is written into
  `sessions/` / `register/` (runtime dir, git-ignored). Never log it, never
  print it, never commit a fixture containing a real one.
- Before every commit, scan for the token: `git grep -i "$(printf %s '8713')"` /
  a plain `grep -rn` for the known value. Zero hits required.

## Dev workflow

```bash
uv sync
uv run ruff check .
uv run pytest
```

- Line length 100, target py312, `from __future__ import annotations` at the top
  of every module.
- Tests must not hit the network or the real `~/.claude`. `tests/conftest.py`
  points `AI_TG_BRIDGE_HOME` at a temp dir before collection; use
  `tests/fakes.py::FakeTelegram` and a stubbed `broker.inject_user_message`.
- Hooks are exercised as real subprocesses (`tests/test_hooks.py`, both the
  Claude and `codex_*` ones) — that is how each agent actually runs them, so
  keep it that way.

## Commits

- Short imperative subject. Body explains *why* when it isn't obvious.
- End every commit message with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```
- Don't commit to `main` directly; branch and open a PR.

## Running as a service

`service/ai-session-telegram.service.in` is a template; `service/install.sh`
renders `@REPO_DIR@` / `@BRIDGE_BIN@` from its own location, so the checkout can
live anywhere. After moving the repo: `uv sync`, `bridge install-hooks`
(add `--agent codex` or `--agent all` if Codex sessions are in use too),
`./service/install.sh` again.

Neither macOS nor Windows has systemd; `src/ai_session_telegram/serviceinstall.py`
dispatches on `platform.system()` to the right analog for `bridge install-service` /
`bridge uninstall-service`: launchd on macOS (plist built directly with `plistlib`,
no template file), Task Scheduler on Windows (`schtasks`, logon trigger). Linux
still refuses here and points at `./service/install.sh` — no reason to
reimplement something that already works.

Getting Windows this far required fixing several POSIX-only assumptions that
predate this file, since a "no service" platform is moot if the broker can't
even run there:
- `broker.py`, `codex_inject.py`, and `hooks/_bridge_common.py` each imported
  `fcntl` unconditionally at module scope (doesn't exist on Windows). This
  mattered for the hook file specifically because it's a separate,
  deliberately standalone module (see item 1 below) — fixing `broker.py`
  alone would still leave every hook crashing on Windows before it got
  anywhere near the broker.
- `_alive()` (duplicated in `broker.py` and `cli.py`) used `os.kill(pid, 0)`
  as a liveness probe. On Windows, `os.kill` ignores the signal value and
  always calls `TerminateProcess` — so that probe was **killing the process
  it was checking**. Windows now shells out to `tasklist` instead.
- The `fcntl`/`msvcrt` branching and the `os.kill`/`tasklist` branching were
  each repeated at 2-3 call sites, so both got pulled into one shared
  `src/ai_session_telegram/_procutil.py` (`is_alive()`, `locked()`) that
  `broker.py`, `cli.py`, and `codex_inject.py` import instead of branching
  `os.name` themselves. `hooks/_bridge_common.py` can't use it — hooks must
  stay standalone stdlib and never `import ai_session_telegram` — so it keeps
  its own inline branch for the one lock it needs.
- Windows can't deliver SIGTERM the way `cmd_stop` expects (same
  `TerminateProcess`-not-a-signal issue), so there's no way for the broker to
  catch it and shut down gracefully. `cmd_stop` on Windows instead touches
  `paths.STOP_FLAG`, which `Broker.run()`'s loop polls every cycle; only after
  that grace period times out does it fall back to `os.kill(pid, SIGTERM)`
  (= an immediate hard kill there, same as it always was).
- `hookinstall._command_for` hardcoded `python3 <path>`; Windows Python
  installs don't reliably put `python3` on PATH, so it now uses `py -3
  "<path>"` there instead (the official Windows launcher).
- `cli.cmd_logs` shelled out to `tail`, which Windows doesn't ship. Replaced
  with a small stdlib-only tail (`collections.deque` for the last N lines,
  then poll-and-append for `-f`) — this dropped the external-binary
  dependency on every platform, not just Windows.

None of this has been run on an actual Windows machine — it's implemented
from documented API behavior only. `tests/test_procutil.py`,
`tests/test_serviceinstall.py`, `tests/test_cli.py`, and
`tests/test_hookinstall.py` cover the Windows branches by monkeypatching
`platform.system`/`os.name` and the relevant subprocess calls, but the
`msvcrt` branch in `_procutil.locked()` can't be exercised on Linux at all
(the module doesn't exist there) — CI's `windows-latest` matrix leg is the
only thing that actually imports it.

Only one broker may run at a time, machine-wide — it's a single-instance lock
on `~/.ai-session-telegram/state/broker.pid`, and that runtime dir is shared across
*every* checkout of this repo regardless of path (see `paths.py`). Cloning or
worktree-ing the repo a second place and running `bridge start`/the service
there races the first one for that lock; whichever loses silently no-ops
("broker already running") while the other — possibly running stale code —
keeps serving. If a broker seems to be running old behavior, check
`ps aux | grep ai_session_telegram.broker` for more than one hit before
assuming the code itself is wrong.
