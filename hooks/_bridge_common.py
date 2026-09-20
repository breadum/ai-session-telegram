"""Shared helpers for the bridge hooks.

STDLIB ONLY. These scripts run from ~/.claude/settings.json with the system
Python (python3, or `py -3` on Windows — see hookinstall._command_for) on
every SessionStart / UserPromptSubmit / Stop / SessionEnd / Notification, so
they must start fast and never import the project package or third-party
libs.

Every hook is non-blocking: it writes a small file under paths.ROOT and exits.
The broker does everything else (topics, Telegram, injecting commands back into
the session over its [uds-messaging] socket).
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# --------------------------------------------------------------------------
# paths (mirror of ai_session_telegram.paths, kept standalone on purpose)
# --------------------------------------------------------------------------

def root() -> Path:
    env = os.environ.get("AI_TG_BRIDGE_HOME")
    return Path(env).expanduser() if env else Path.home() / ".ai-session-telegram"


ROOT = root()
REGISTER = ROOT / "register"
SESSIONS = ROOT / "sessions"
OUTBOX = ROOT / "outbox"
END = ROOT / "end"
BUSY = ROOT / "busy"          # <sid> present = a turn is in progress
PENDING = ROOT / "pending"    # <sid>.json = texts the broker just queued into Codex


def ensure_dirs() -> None:
    for d in (REGISTER, SESSIONS, OUTBOX, END, BUSY, PENDING):
        d.mkdir(parents=True, exist_ok=True)


def session_file(sid: str) -> Path:
    return SESSIONS / f"{sid}.json"


def mark_busy(sid: str) -> None:
    """A turn just started for this session."""
    BUSY.mkdir(parents=True, exist_ok=True)
    (BUSY / sid).write_text(ts())


def clear_busy(sid: str) -> None:
    """The turn finished (or the session ended)."""
    (BUSY / sid).unlink(missing_ok=True)


def queue_outbox(sid: str, role: str, text: str, *, ai_title: str = "") -> None:
    """Drop a message for the broker to deliver to this session's topic.
    role: "user" | "assistant" | "note". Filenames sort chronologically.
    ai_title, when set, carries Claude Code's own session title so the broker
    can name the topic without an LLM call of its own."""
    d = OUTBOX / sid
    d.mkdir(parents=True, exist_ok=True)
    name = f"{ts()}-{secrets.token_hex(2)}.json"
    item: dict = {"role": role, "text": text}
    if ai_title:
        item["ai_title"] = ai_title
    (d / name).write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------
# pending-injection tracking
#
# Neither agent's UserPromptSubmit payload turned out to be a reliable signal
# for "this was injected by the bridge, not typed": Codex has no wrapper at
# all (arrives looking exactly like something the user typed), and Claude
# Code's peer-message wrapper/origin/promptSource fields turned out not to be
# consistently present or matchable in practice either (a real bridge-caused
# duplicate mirror was traced back to exactly this). So both claude_inject.py
# and codex_inject.py record the exact text they're about to deliver here
# (paths.queue_pending) before delivering it, and this consumes a matching
# entry so the echo isn't mirrored twice. Claude Code wraps the original text
# before the hook sees it (Codex doesn't), hence substring rather than exact
# match below.
# --------------------------------------------------------------------------

_PENDING_TTL_S = 60  # keep in sync with paths.queue_pending's writer


def consume_pending_injection(sid: str, prompt: str) -> bool:
    """True and removes the entry if `prompt` contains a message the broker
    just queued into this session; stale entries are pruned along the way."""
    f = PENDING / f"{sid}.json"
    if not f.exists():
        return False
    with open(f, "a+", encoding="utf-8") as fh:
        if os.name == "nt":
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            items = json.loads(fh.read() or "[]")
        except json.JSONDecodeError:
            items = []
        now = time.time()
        items = [it for it in items if now - it.get("ts", 0) < _PENDING_TTL_S]
        found = False
        for i, it in enumerate(items):
            if it.get("text") and it["text"] in prompt:
                items.pop(i)
                found = True
                break
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(items, ensure_ascii=False))
    return found


# --------------------------------------------------------------------------
# hook io
# --------------------------------------------------------------------------

def read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def emit(obj: dict | None = None) -> None:
    """Print the hook's JSON result and exit 0."""
    sys.stdout.write(json.dumps(obj or {}, ensure_ascii=False))
    sys.stdout.flush()
    raise SystemExit(0)


# --------------------------------------------------------------------------
# transcript
# --------------------------------------------------------------------------

# last_assistant_text: always re-read this many times (with a real pause
# between reads) before trusting the transcript, to give Claude Code's own
# writer a chance to land the turn's last append before Stop's hook commits
# to whatever it's already seen. See that function's docstring for why this
# can't be made conditional on what the first read finds.
_SETTLE_ATTEMPTS = 3
_SETTLE_INTERVAL_S = 0.08


def _is_turn_start(obj: dict) -> bool:
    """A real user (or peer-injected) prompt, not a tool_result. Both are
    recorded as type=="user", but only a genuine prompt has a plain string
    `content` — a tool_result's content is always a list of blocks."""
    if obj.get("type") != "user":
        return False
    return isinstance((obj.get("message") or {}).get("content"), str)


def _read_transcript_objs(p: Path) -> list[dict]:
    """Read+parse a transcript .jsonl, retrying briefly if the *last* line
    fails to parse — Claude Code may still be flushing the final message to
    disk exactly when Stop fires, and a torn write there would otherwise
    silently drop exactly the content a mirror most needs (the turn's real
    conclusion), while earlier, already-flushed lines (scaffolding/progress
    notes) still parse fine and go out looking complete. A handful of
    retries at a few tens of ms each is negligible next to hooks' own
    non-blocking budget."""
    objs: list[dict] = []
    for attempt in range(5):
        raw_lines = [
            ln.strip()
            for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()
        ]
        objs = []
        last_line_failed = False
        for i, line in enumerate(raw_lines):
            try:
                objs.append(json.loads(line))
            except json.JSONDecodeError:
                if i == len(raw_lines) - 1:
                    last_line_failed = True
        if not last_line_failed or attempt == 4:
            break
        time.sleep(0.05)
    return objs


def last_assistant_text(transcript_path: str) -> str | None:
    """Join the text blocks of every assistant message since this turn began,
    or build a fallback summary if the turn had none. Returns None when
    there's nothing worth mirroring at all (caller should skip queuing).

    A single Stop-bounded turn commonly spans several assistant messages
    interleaved with tool calls (narration, then a tool call, then more
    narration, ...) — every one of those is real content the user would
    want mirrored, not just whatever text happened to come last. Scoped to
    "since the last real user/peer prompt" so this doesn't re-include
    earlier turns' responses on every Stop.

    A turn can also legitimately have *no* text at all: Claude ran tools
    without narrating (real work — surface a tool-name summary instead of a
    bare placeholder) or the turn was one of Claude Code's synthetic machine
    turns (a slash command, a background-task notification, a local-command
    echo — genuinely nothing to show; skip it, the same way tidy_prompt
    already skips these on the user-prompt side).

    Those two "no text" cases are indistinguishable from a third, real bug:
    the turn's actual concluding text message just hasn't been appended to
    the transcript file yet. `_read_transcript_objs` only catches this when
    the last line is torn (fails to parse); when Stop fires a beat before
    that line is written *at all*, the file simply looks like it ends one
    message early — no parse error to retry on.

    An earlier version of this function only re-read when the scan found
    zero text at all, on the assumption that *some* text meant the read was
    complete. Live data proved that wrong: a turn with several narrated
    tool-call segments can have the first two or three already on disk and
    the rest — including the real closing summary — still landing, so the
    scan finds non-empty `all_texts` and stops right there, silently
    dropping everything written after that read. There's no way to tell
    "this is genuinely all of it" from "the writer just hasn't gotten to the
    rest yet" by content alone — and checking the file's mtime doesn't save
    us either: Stop fires right after Claude Code's *own* last write, so the
    mtime is "suspiciously fresh" for practically every turn, race or not,
    and a write that hasn't started yet at check time leaves no trace to
    detect. So this unconditionally re-reads a fixed, small number of times
    with a real pause between them and trusts only the last one — a blind
    debounce, not a targeted one, but the only kind that can catch a race
    whose next write hasn't happened yet. Costs a fixed ~150ms on every Stop,
    race or not; cheap next to how expensive silently mangling a turn's real
    answer turned out to be in practice (confirmed twice from live data).
    """
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return "(transcript unavailable)"

    all_texts: list[str] = []
    tool_names: list[str] = []
    for attempt in range(_SETTLE_ATTEMPTS):
        objs = _read_transcript_objs(p)

        turn_start = 0
        for i in range(len(objs) - 1, -1, -1):
            if _is_turn_start(objs[i]):
                turn_start = i + 1
                break

        all_texts = []
        tool_names = []
        for obj in objs[turn_start:]:
            if obj.get("type") != "assistant":
                continue
            msg = obj.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                if content.strip():
                    all_texts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "text" and blk.get("text", "").strip():
                    all_texts.append(blk["text"])
                elif blk.get("type") == "tool_use":
                    tool_names.append(blk.get("name") or "?")

        if attempt < _SETTLE_ATTEMPTS - 1:
            time.sleep(_SETTLE_INTERVAL_S)

    if all_texts:
        return "\n\n".join(all_texts)
    if tool_names:
        counts: dict[str, int] = {}
        for name in tool_names:
            counts[name] = counts.get(name, 0) + 1
        summary = ", ".join(f"{n}×{c}" if c > 1 else n for n, c in counts.items())
        return f"🔧 Ran tools without a text response: {summary}"
    return None


def last_ai_title(transcript_path: str) -> str:
    """Claude Code's own most-recent session title, or "" if none yet.

    Claude Code writes `{"type":"ai-title","aiTitle":"..."}` lines into the
    transcript once it has named the conversation. We forward the latest so the
    broker can title the Telegram topic with it."""
    p = Path(transcript_path) if transcript_path else None
    if not p or not p.exists():
        return ""
    title = ""
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or '"ai-title"' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "ai-title" and obj.get("aiTitle"):
            title = str(obj["aiTitle"])
    return title


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def ts() -> str:
    return time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}"


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
