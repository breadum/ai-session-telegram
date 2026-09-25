# ai-session-telegram

Run Claude Code / Codex CLI sessions from Telegram. Each session gets its own
room (a topic) in a group; prompts and responses flow through it. Pick up
where you left off from your phone, even when you're away from your desk.

## Features

Built entirely on Telegram's forum (Topics) feature. Each session gets its
own topic, so you can follow several pieces of work separately inside one
group, and keep going from your phone whenever you step away.

- **One topic per session.** Run several sessions at once — even a mix of
  Claude Code and Codex — without the conversations bleeding into each
  other. A Claude session names its own topic from the conversation, too.
  Topic icon colors split by agent (coral for Claude, pale yellow for Codex)
  so they're still tellable apart at a glance even after the name changes.
- **Keep working from anywhere.** Check on a session you started at your
  desktop and steer it from your phone while out. Don't lose the thread on a
  long-running migration or refactor.
- **Not tied to a terminal.** Works with a session started from a terminal,
  Orca, or Claude Desktop — no tmux or PTY tricks required. Uses the socket
  Claude Code 2.x opens per session, and Codex CLI's `codex queue`.
- **Simple to set up.** `bridge setup`, `bridge install-hooks`,
  `./service/install.sh` — that's it. No web server, no database — one
  daemon and a handful of hooks passing files back and forth.
- **Reads well on Telegram.** Markdown gets mapped to Telegram's formatting,
  and tables get their columns aligned. Shows whether a session is working
  or waiting for input.
- **Light and quiet.** The bot token only ever lives in a local config file,
  and hooks use nothing but the standard library. The only thing that leaves
  the machine is Telegram API calls.

A typical topic looks something like this:

```
🐮  Logging in redirects to /login instead of home. Take a look.
🤖  The auth middleware sends to /login whenever there's no session, but
    that also catches requests mid token-refresh. Let the refresh
    handler run first and it's fixed.
🐮  Go ahead and fix it.
🔧  Working (14s)
🤖  Added a refresh-token exception at middleware/auth.ts:23. Logged in
    locally and home stays put now.
```

## Requirements

- Claude Code 2.x (a version with the `[uds-messaging]` socket) and/or Codex
  CLI (a version with the `codex queue` subcommand)
- [uv](https://docs.astral.sh/uv/)
- A Telegram supergroup with Topics enabled, and a bot

## Install

### 1. Telegram bot and group (one time)

1. Create a bot with `/newbot` at [@BotFather](https://t.me/BotFather) and
   get its token.
2. Make a group and turn on Topics.
   - Create a new group in the Telegram app. It won't exist with just you in
     it — you need to invite at least one other member — so invite the bot
     you just made right here.
   - Group info → Edit (pencil icon) → the "Topics" toggle near the bottom.
     Flipping it **automatically converts the group into a supergroup** —
     there's no separate "make a supergroup" menu.
3. Promote the bot to admin. In the admin permissions screen you have to
   explicitly turn on "Manage Topics" — it's off by default even for admins.
4. Once the bot is an admin, send any message in the group. The bot can't
   see anything sent before that.

### 2. Install the bridge

Clone the repo and install dependencies.

```bash
git clone https://github.com/breadum/ai-session-telegram
cd ai-session-telegram
uv sync
```

Then register three things.

```bash
uv run bridge setup           # asks for the bot token, saves it to ~/.ai-session-telegram/config.json
uv run bridge install-hooks   # adds the Claude Code hooks to ~/.claude/settings.json (backs up the original)
```

The third one — putting the broker up as an always-on service — differs by OS.

```bash
./service/install.sh          # Linux: registers a systemd --user service
uv run bridge install-service # macOS: registers a launchd user agent (~/Library/LaunchAgents)
uv run bridge install-service # Windows: registers a Task Scheduler logon trigger
```

> Windows hasn't been verified on real Windows hardware from this repo (all
> development/testing has been on Linux; CI's `windows-latest` only checks
> the unit-test level). `install-service` also starts it once immediately on
> registration, but if something's off, see "Running as a service" in
> [CLAUDE.md](CLAUDE.md), or file an issue.
>
> **Known limitation**: depending on the Windows Python build,
> `socket.AF_UNIX` may not exist at all (confirmed on GitHub Actions'
> windows-latest) — if so, **message injection into Claude Code sessions
> (Telegram → session) won't work** (session → Telegram mirroring is fine).
> Codex sessions don't use a socket, so they're unaffected. `config.json`'s
> bot token also isn't meaningfully permission-restricted (0o600) on
> Windows — NTFS has no such concept.

To also bridge Codex CLI sessions in the same group, register one more set
of hooks (`--agent all` does both).

```bash
uv run bridge install-hooks --agent codex   # adds to ~/.codex/hooks.json
```

Codex has to trust a freshly-added hook once before it'll run it. Either
launch with `codex --dangerously-bypass-hook-trust`, or approve it at the
interactive trust prompt.

Finally, add one line to `~/.claude/settings.json`. Without it, Claude Code
holds the messages the broker injects and never delivers them to the
session — see [Permissions](#permissions) for why.

```json
"crossSessionInbound": "accept"
```

> For a quick try without setting up a service, use `uv run bridge start` /
> `stop` (works on macOS too). If you move the repo to a different path, run
> `bridge uninstall-hooks` from the old location first (on macOS, also bring
> the service down first with `bridge uninstall-service`), then from the new
> location run `uv sync && uv run bridge install-hooks &&
> ./service/install.sh` again (`bridge install-service` on macOS) — add
> `--agent codex` or `--agent all` to `install-hooks`/`uninstall-hooks` if
> Codex hooks were registered too, since the default is `claude` only.

### 3. First session

```bash
claude --dangerously-skip-permissions
```

A `<directory>-<session-id>` topic shows up in the group. See
[Permissions](#permissions) for why this flag is needed.

Start Codex with `codex --dangerously-bypass-approvals-and-sandbox` (or
something less extreme like `-a never`). An interactive session's topic
shows up **when it sends its first prompt** — unlike Claude Code, it's
normal for this to happen a bit after the session actually starts, not at
launch.

## Usage

Prompts (`🐮`) and responses (`🤖`) land in the topic as-is. Markdown gets
converted to Telegram formatting, and tables become width-aligned monospace
blocks.

A message you write in the topic reaches the session within a couple of
seconds. Once it's actually been delivered, your message gets a 👀 reaction
— so you know it was received even before the reply shows up. If the
session is busy, you also get a note that it'll be handled once the current
turn finishes.

When a session is waiting on input (an `AskUserQuestion`, say), it shows up
as `🔔`. Just write your answer in the topic.

### Topic commands

| Command | What it does |
|---|---|
| `/status` | session status, busy or not, delivery method (socket/`codex queue`), working directory |
| `/title <text>` | rename the topic. A Claude session also renames it automatically from the conversation (Codex doesn't do this yet — the directory name is the default) |
| `/sessions` | list every session |
| `/exit` | delete this topic. The local session record is kept |
| `/help` | list of commands |

`/exit` only deletes the topic. To also clean up records for sessions that
have ended, use `uv run bridge prune`. `--all` does every session, `-y`
skips the confirmation.

## Configuration

What `bridge setup` writes to `~/.ai-session-telegram/config.json`:

| Key | Default | Meaning |
|---|---|---|
| `bot_token` | – | Telegram bot token |
| `chat_id` | – | supergroup ID |
| `delete_topic_on_end` | `false` | whether ending a session in the terminal also deletes its topic (Codex topics are always deleted when Codex reports `SessionEnd`) |

Can be overridden with the environment variables `AI_TG_BOT_TOKEN`,
`AI_TG_CHAT_ID`, `AI_TG_DELETE_TOPIC_ON_END`.

## Managing the broker

```bash
uv run bridge status      # broker and session status
uv run bridge logs -f     # logs
uv run bridge prune       # clean up ended sessions
```

If it's running as a service, use systemd (Linux) / launchd (macOS) / Task
Scheduler (Windows) instead of `start` / `stop`.

```bash
systemctl --user restart ai-session-telegram.service   # Linux: after changing broker code
journalctl --user -u ai-session-telegram.service -f
./service/uninstall.sh                                 # Linux: remove just the service

launchctl kickstart -k gui/$(id -u)/ai-session-telegram # macOS: after changing broker code
uv run bridge logs -f                                   # macOS/Windows: use this for logs
uv run bridge uninstall-service                         # macOS/Windows: remove just the service

schtasks /End /TN ai-session-telegram                   # Windows: after changing broker code
schtasks /Run /TN ai-session-telegram
```

Hooks are re-read every time, so you don't need to restart anything after
changing just the hooks.

## Permissions

### Claude Code

A message the broker injects arrives at the session as a peer message —
treated as coming from another Claude session, not a human-typed prompt. So
running unattended needs two things.

**`crossSessionInbound: accept`** in `~/.claude/settings.json`. By default,
a session that skips prompts won't let an unattested sender inject a
message — Claude Code holds it instead. `accept` delivers it right away.

**Start the session with `--dangerously-skip-permissions`.** A trusted
folder with `acceptEdits` also works. A peer message can't dismiss a
tool-permission dialog for you, so that dialog needs to never come up in
the first place.

Ordinary task instructions go through fine, but a request to change
permissions or settings is treated as lower-trust and the session may
refuse it.

### Codex CLI

**Hook trust.** A hook just added via `bridge install-hooks --agent codex`
needs Codex's one-time approval before it'll run. Either launch with
`codex --dangerously-bypass-hook-trust`, or approve it at the interactive
trust prompt.

**Approval bypass.** Like Claude Code's peer messages, a message queued via
`codex queue` can't dismiss a tool-permission dialog either. Launch with
`codex --dangerously-bypass-approvals-and-sandbox`, or less extremely with
`-a never` (skips approval prompts, keeps the sandbox).

## How it works

A hook writes one file under `~/.ai-session-telegram/` per session event and
exits immediately. Stdlib only, never blocks.

The broker is the only process that talks to Telegram. It creates topics,
ships out responses, and injects messages into sessions — how, depends on
the agent.

Claude Code 2.x opens a Unix socket per session
(`$CLAUDE_CODE_MESSAGING_SOCKET`, `$CLAUDE_CODE_MESSAGING_TOKEN`). The
`SessionStart` hook records these, and the broker connects to that socket to
put a message on the prompt queue.

Codex CLI doesn't hand out a per-session socket — every session shares one
local daemon, so the broker just calls
`codex queue --thread <session-id> --message <text>`. Unlike Claude, though,
Codex has no way to tell an injected message apart from something typed, so
the broker separately records the text it just injected, and the hook checks
that record so it doesn't mirror its own echo back.

More on the architecture and contribution rules in
[`CLAUDE.md`](CLAUDE.md).

## Troubleshooting

**`is_forum: None` or `the chat is not a forum`**
Topics isn't turned on for the group. Turn it on from group editing.

**`not enough rights to create a topic`**
The bot doesn't have "Manage Topics" permission. Turn it on for the bot in
the group's admin settings.

**`0 update(s)` during `setup`**
Either the bot isn't an admin yet, or the only messages predate it becoming
one. Make it an admin, then send a new message.

**Writing in the topic doesn't reach the session (Claude)**
Check the broker is up with `bridge status`. If `/status`'s socket value is
`missing`, the session restarted and its pid changed — give it one prompt
and it'll be picked up again. `unknown` means that session has no
`[uds-messaging]` socket at all, so it's mirror-only. `Held peer message` in
the session transcript means `crossSessionInbound: accept` is missing.

**Writing in the topic doesn't reach the session (Codex)**
If `/status` shows `kind: claude`, it's going through socket/token logic it
shouldn't be — restart `bridge` on the latest code, then give that session
one more prompt to re-trigger registration (`SessionStart` fills in `kind`
on re-registration). If that still doesn't fix it, check that `codex` is on
the `PATH` of the user/shell running the broker, and that the hooks are
trusted (`--dangerously-bypass-hook-trust`).

**A reply shows up in the group's General topic**
That session started before `bridge install-hooks` was run. Open a new
session.

**`broker already running` but it's actually dead**
A stale pidfile got left behind. Check
`~/.ai-session-telegram/state/broker.pid` and remove it if nothing's
actually running.

**This repo is checked out in more than one place**
`~/.ai-session-telegram` is a shared, global state directory independent of
checkout path, so **only one broker — whichever checkout came up first —
may be alive at a time** (otherwise two processes fight over the
`getUpdates` offset). Check with
`ps aux | grep ai_session_telegram.broker` for more than one hit, and stop
whichever one systemd isn't managing.

## Development

```bash
uv sync && uv run ruff check . && uv run pytest
```

Rules are in [`CLAUDE.md`](CLAUDE.md).
