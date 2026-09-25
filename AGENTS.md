# AGENTS.md — working rules for this repo

## Project workflow

이 프로젝트는 기능적으로 완성된 상태이므로, 모든 변경은 PR을 통해 확인받는다.

1. 작업별 브랜치를 만든다.
2. 변경을 구현하고 관련 테스트와 검증을 실행한다.
3. 변경 내용을 커밋한다.
4. PR을 생성하고 변경 내용·검증 결과·주의 사항을 기록한다.
5. 사용자의 확인을 받은 뒤에만 머지한다.

사용자의 확인 없이 기본 브랜치에 직접 커밋하거나 머지하지 않는다. 긴급한 운영 조치가 필요한 경우에도 코드 변경과 운영 조치를 구분하고, PR에 해당 내용을 명확히 남긴다.

## Development philosophy

이 프로젝트의 상세 운영 spec은
[`docs/agents-audit/engineering-philosophy-spec.md`](docs/agents-audit/engineering-philosophy-spec.md)에 있다.
핵심 규칙은 다음과 같다.

1. **Spec first, code second.** 기능 변경은 크기와 관계없이 간단한 변경 spec을
   먼저 작성하고 사용자 승인을 받은 뒤 구현한다. 메시지 role, session lifecycle,
   Telegram API, runtime state, hook contract, service 동작이 바뀌는 경우에는
   문제·범위·비목표·상태·실패·acceptance criteria를 빠뜨리지 않는다. 코드와
   spec이 충돌하면 임의로 결정하지 않고 `spec gap`으로 남겨 판단을 요청한다.
2. **사용자는 판단 책임자, AI는 구현자다.** AI는 조사·질문·spec 정리·코드·
   테스트를 담당하지만 제품 의미, trade-off, 권한·보안 완화, 데이터/topic
   삭제, retry/drop 정책을 사용자 대신 확정하지 않는다. 최종 spec 승인자는 사용자다.
3. **지식은 저장소에 외부화한다.** 계약은 코드·테스트·AGENTS, 기술 결정은
   `docs/decisions/`, 장애 복구는 `docs/operations/`, 작업 spec은
   `docs/agents-audit/` 또는 작업 문서에 둔다. Telegram 대화나 모델 memory는
   원본이 아니다.
4. **구현 전 딥인터뷰를 한다.** 누가 어떤 문제를 겪는지, 보존할 기존 동작,
   유실·중복·지연 중 우선 위험, 종료/자동정리 기대, 권한·비용·운영 제약,
   acceptance criteria를 확인한다. 핵심 답이 비어 있으면 구현을 시작하지
   않는다.
5. **실패는 learning asset이다.** 실패·반려·오판은 원인, 놓친 신호, 수정한
   규칙, 재발 방지 테스트, 남은 불확실성을 기록한다. 반복 가능한 학습은
   regression test·불변식·decision·runbook·acceptance criterion 중 하나로
   승격한다.
6. **세션 간 handoff를 남긴다.** 시작할 때 AGENTS와 관련 spec/decision/
   operation/learning을 읽고, 종료할 때 완료·미해결·검증 결과·실패 학습·
   다음 agent가 읽을 파일·사용자 판단 질문을 기록한다.

문서-only 변경은 사용자가 정한 운영에 따라 직접 갱신한다. 코드·hook·service·
runtime 동작을 바꾸는 변경은 spec과 검증을 먼저 준비하고 기존 PR 절차를 따른다.

## Codebase guidance

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
     - `claude_inject.py` drops a marker in `paths.PENDING` (via `paths.queue_pending`)
       right before writing the socket frame, same as Codex below — Claude Code's
       own peer-message signals (`origin.kind`, `promptSource`, the wrapper text
       preamble) turned out not to be a reliable enough match at `UserPromptSubmit`
       on their own; a real duplicate-mirror bug traced back to exactly that. The
       preamble-prefix check in `user_prompt_submit.py`/`render.tidy_prompt` is now
       just a backstop for a pending marker that already expired.
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
     the topic's icon color (`broker.ICON_COLOR`) — the visual cue that
     distinguishes Claude and Codex topics without hiding the working-directory
     label in the topic name.
   - `sessions/<sid>.json` — broker's record (kind, label, thread_id, socket,
     token, status, titled)
   - `outbox/<sid>/<ts>.json` — `{"role": "user"|"assistant"|"note"|"event", "text": ...}`,
     optional `"ai_title"` (Claude Code's own session title, forwarded by the
     `Stop` hook — the broker renames the topic to it once) → broker sends to the topic.
     `event` (🔔) is what `notification.py` / `codex_permission_request.py`
     queues when the session wants attention, and what `tidy_prompt` downgrades
     machine turns to. The `"assistant"` text comes from
     `_bridge_common.last_assistant_text`, which joins *every* assistant
     message since the turn's last real user/peer prompt (scoped via
     `_is_turn_start`) — a turn commonly has several, interleaved with tool
     calls, and an earlier version that kept only the last one silently
     dropped real narration on any multi-tool-call turn. A turn with *no*
     text at all gets a tool-name summary if it at least ran tools (real
     silent work), or `None` — meaning `stop.py` skips `queue_outbox`
     entirely — if it's one of Claude Code's synthetic machine turns (slash
     command, background-task notification, local-command echo) with
     nothing to show; don't reintroduce the old bare "(no text in final
     response)" placeholder for either case. `codex_stop.py` does the
     simpler version of the same thing (skip when `last_assistant_message`
     is empty) since Codex hands the reply over directly, no transcript to
     mine for tool names. Reading the transcript itself races Claude Code's
     own writer: Stop can fire before the turn's *last* line is fully
     flushed, so `_read_transcript_objs` retries (a few times, tens of ms
     apart) when only the last line fails to parse — a real bug had this
     silently drop the turn's actual conclusion while earlier, already-
     flushed lines (progress narration) still went out looking complete.
     Two nastier shapes of the same race, both confirmed from live
     transcripts, cost real answers before `last_assistant_text` was changed
     to guard against them:
     - The concluding text message missing from the file *outright* (not
       torn — Stop just fires before that line is appended at all), which is
       indistinguishable from a genuine tool-only turn at read time. A long
       final report reliably lost this way, mirrored as a bare tool-name
       summary instead.
     - A multi-segment turn with its first two or three narrated segments
       already on disk and the rest — including the real closing summary —
       still landing. The first version of the fix above only re-read when a
       scan found *zero* text, on the assumption that some text meant the
       read was complete; that's false, and a real reply got truncated to
       its first two segments this way.
     Content-based heuristics (retry only when text is missing; trust it once
     any text shows up) cover one shape but not the other, and checking the
     file's mtime doesn't help either — Stop fires right after Claude Code's
     own last write, so the mtime is "suspiciously fresh" for nearly every
     turn, race or not. So `last_assistant_text` now unconditionally re-reads
     a fixed, small number of times with a real pause between them and
     trusts only the last one — a blind debounce, since a write that hasn't
     started yet at check time leaves nothing to detect. Costs a fixed
     ~150ms on every Stop, race or not.
   - `inbox/<sid>.jsonl` — commands that *failed* to inject, retried each loop
   - `busy/<sid>` — present between `UserPromptSubmit` and `Stop`: a turn is
     running. `/status` reads it; a message sent while it exists gets a
     "queued behind the current turn" note. mtime = turn start.
   - `end/<sid>.json` — session_end → broker marks ended; Codex topics are
     deleted automatically, while Claude follows `delete_topic_on_end`
   - `pending/<sid>.json` — texts `claude_inject.py`/`codex_inject.py` just
     queued (via `paths.queue_pending`), awaiting the `UserPromptSubmit` echo
     (see item 3). TTL-pruned. `consume_pending_injection` matches Claude's
     entries by substring (Code wraps the original text before the hook sees
     it) and Codex's by the same check (trivially exact, since Codex doesn't
     wrap at all).
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
     injection, wrapped in an "Another Claude session sent a message:" preamble
     for Claude; verbatim, no wrapper, for Codex). `user_prompt_submit.py`/
     `codex_user_prompt_submit.py` drop it *before* queuing (still mark the turn
     busy) via `consume_pending_injection` against the `pending/` marker each
     inject function writes first (items 3–4) — that's the authoritative check
     for both agents now. The preamble-prefix check is only a backstop for an
     already-expired marker; relying on it (or on Claude Code's
     origin/promptSource fields) alone is what caused a real double-post bug.
     Without *some* working version of this, every Telegram message
     double-posts in its topic.

7. **Prompt role classification has an explicit order.** Pending injection
   echoes are consumed first, known Claude peer/system echoes are then dropped,
   narrowly recognized AI handoff prompts are mirrored as `assistant` (`🤖`),
   and ordinary prompts remain `user` (`🐮`). The heuristic lives in
   `hooks/user_prompt_submit.py` and `hooks/codex_user_prompt_submit.py` and
   must stay conservative. `note`/`event` use `⚠️`/`🔔`; the source of truth is
   `broker._ROLE_PREFIX`, with subprocess hook tests covering the role files.

   분류 결과가 애매한 상태는 허용되는 사용자 경험이 아니라 버그다. 새 형태의
   handoff나 user prompt가 발견되면 임의로 분류하지 말고 원인·예시를
   `docs/learning/`에 기록한 뒤 명시적인 분류 규칙과 regression test를 추가한다.

8. **Codex stale sessions are cleaned up on explicit thread failure.** If
   `codex queue` reports that the thread is unknown or does not exist,
   `CodexSessionGoneError` triggers deletion of the stale topic and removal of
   its thread mapping, session record, pending marker, inbox, and outbox only
   after the session/topic mapping is verified and Telegram confirms deletion.
   Pending local work is explicitly discarded and logged after this definitive
   stale decision; a temporary queue or Telegram failure remains retryable. A
   missing `SessionEnd` hook must not leave a dead topic retrying forever.

9. **Topic migrations protect user titles.** Codex automatic topic names no
   longer include a `[codex]` prefix because icon color identifies the agent.
   Startup/resume migration may rename only records without `titled`; a user
   `/title` or an AI title must never be overwritten.

## Secrets

- The Telegram bot token lives **only** in `~/.ai-session-telegram/config.json`
  (chmod 600), written by `bridge setup`. It is never in the repo.
- `messaging_token` is a per-session Claude Code secret. It is written into
  `sessions/` / `register/` (runtime dir, git-ignored). Never log it, never
  print it, never commit a fixture containing a real one.
- Before every commit, inspect the staged diff and run the repository's generic
  secret scan. Never put a real token or a token-derived fragment in source,
  docs, fixtures, logs, or examples. CI rejects Telegram bot-token-shaped
  strings.

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
- On Windows, run tests with `PYTHONUTF8=1` set (CI does this in
  `.github/workflows/ci.yml`) — unlike the production code, which always
  passes `encoding="utf-8"` explicitly, the *tests'* own `read_text()`/
  `write_text()` calls rely on Python's UTF-8 mode to not mangle the
  non-ASCII fixtures (Korean text) they round-trip.
- CI acceptance runs `ruff check .`, `pytest`, and the generic Telegram token
  scan on Python 3.12 across Ubuntu, macOS, and Windows. Local Linux success
  is not sufficient when a change touches platform branches or encoding.

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

Windows-specific implementation history is recorded in
[docs/decisions/windows-compatibility.md](docs/decisions/windows-compatibility.md).
The current rules are: use `_procutil` for process/lock portability, keep
explicit UTF-8 encodings, guard Claude injection when `socket.AF_UNIX` is
unavailable, and use the platform service adapter. CI's Windows matrix leg is
the executable verification; local Linux tests alone do not prove Windows
support.

Only one broker may run at a time, machine-wide — it's a single-instance lock
on `~/.ai-session-telegram/state/broker.pid`, and that runtime dir is shared across
*every* checkout of this repo regardless of path (see `paths.py`). Cloning or
worktree-ing the repo a second place and running `bridge start`/the service
there races the first one for that lock; whichever loses silently no-ops
("broker already running") while the other — possibly running stale code —
keeps serving. If a broker seems to be running old behavior, check
`ps aux | grep ai_session_telegram.broker` for more than one hit before
assuming the code itself is wrong.
