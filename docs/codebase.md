# Codebase map and contracts

## Overview

This project connects Claude Code and Codex CLI sessions to Telegram forum topics. Each session gets a topic. A local broker owns Telegram communication; agent hooks exchange data with it through files under the runtime directory. There is no web service or database.

The main implementation is in `src/ai_session_telegram/`. The standalone hooks are in `hooks/`; tests are in `tests/`; service integration is in `service/`.

## Important boundaries

- Hooks run with the system Python and must stay stdlib-only, fast, and non-blocking. They write small runtime files and exit.
- `hooks/_bridge_common.py` intentionally mirrors `src/ai_session_telegram/paths.py`; hooks cannot import the package. Keep the path definitions in sync.
- The broker is the only component that calls the Telegram Bot API and owns the `getUpdates` offset.
- Claude receives Telegram input over its local messaging socket. Codex receives it through `codex queue`. Both injectors write a pending marker before delivery so the matching prompt echo is not mirrored twice.
- Claude peer messages require `crossSessionInbound: accept` and a trusted permission mode. Codex hooks require hook trust to be enabled.

## Runtime files

The runtime root is shared by checkouts at `~/.ai-session-telegram` unless overridden for tests.

| Path | Purpose |
|---|---|
| `register/<sid>.json` | Hook registration; includes agent kind and delivery details |
| `sessions/<sid>.json` | Broker session and Telegram topic record |
| `outbox/<sid>/` | Messages for Telegram (`user`, `assistant`, `note`, `event`) |
| `inbox/<sid>.jsonl` | Telegram messages awaiting injection or retry |
| `busy/<sid>` | Marks a running turn |
| `pending/<sid>.json` | Injected or dispatched prompt echoes awaiting consumption |
| `end/<sid>.json` | Session termination signal |

The broker's reader in `broker.py` and hook writer in `_bridge_common.py` must change together if the outbox format changes.

## Prompt and message roles

- Claude `Agent`/`Task` and Codex agent dispatches are detected from native `PreToolUse` events and mirrored as `assistant`.
- Their matching `UserPromptSubmit` echoes are consumed using pending markers. Every other prompt is `user`, regardless of its wording; do not infer authorship from text.
- Telegram injections are also consumed from pending markers. Claude's peer-message preamble is only a fallback after a marker expires.
- `UserPromptSubmit` can represent machine activity as well as user input. `render.tidy_prompt` converts known machine turns to `event` or drops noise.
- The role-to-icon mapping lives in `broker._ROLE_PREFIX`. Hook subprocess tests cover the role files.

## Assistant output and rendering

- Claude assistant output is assembled from the turn's transcript in `_bridge_common.last_assistant_text`; transcript writes may lag the Stop hook, so the helper retries before reading the final text.
- Tool-only Claude turns may produce a tool summary; synthetic turns with nothing to show are skipped. Codex output is taken from its stop event and empty replies are skipped.
- Mirrored message bodies use Telegram HTML through `render.to_telegram_html`. Telegram send retries without markup if parsing fails. Bridge-owned notices remain plain text.

## Lifecycle and topic names

- `SessionEnd` writes an end signal. Codex topics are removed automatically; Claude topic deletion follows `delete_topic_on_end`.
- If Codex explicitly reports an unknown thread, the broker verifies the session/topic mapping and Telegram deletion before clearing its stale routing state. Transient failures remain retryable.
- Agent kind controls topic icon color. Automatic topic migrations must preserve titles marked `titled`, including user `/title` and AI-assigned titles.
- Only one broker may run machine-wide. All checkouts share the same runtime root and single-instance lock; running brokers from multiple checkouts can leave stale code serving requests.

## Development and platform notes

- Python 3.12+, line length 100. Add `from __future__ import annotations` to modules.
- Tests must not use the network or the real `~/.claude`; `tests/conftest.py` configures a temporary runtime root. Hooks are tested as subprocesses.
- CI runs Ruff, pytest, and a Telegram token scan on Ubuntu, macOS, and Windows. Windows tests use `PYTHONUTF8=1`.
- Store the bot token only in the runtime config (`~/.ai-session-telegram/config.json`). Session messaging tokens are runtime data. Never log or commit either.
- `bridge install-hooks` registers native Claude/Codex hook events; uninstalling removes those registrations. See `hookinstall.py` for the event and matcher configuration.
- Linux service installation uses systemd; macOS uses launchd; Windows uses Task Scheduler. Platform details and compatibility rationale are in `serviceinstall.py` and [the Windows decision](decisions/windows-compatibility.md).
