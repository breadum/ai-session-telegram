"""The broker daemon.

Single long-running process. It is the *only* thing that talks to Telegram:

  * turns SessionStart registrations into forum topics
  * long-polls getUpdates and injects each topic message into the matching
    running Claude Code session over its [uds-messaging] socket
  * ships outbox/<sid>/*.json (mirrored prompts + responses) back to the topic
  * handles /status /exit /title without touching the session

Hooks never call Telegram and never block; they only read/write files under
paths.ROOT. Delivery of a Telegram message into a session does not involve a
hook at all — the broker connects to $CLAUDE_CODE_MESSAGING_SOCKET directly.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import paths
from ._procutil import is_alive as _alive
from ._procutil import locked as _file_locked
from .claude_inject import InjectError, inject_user_message
from .codex_inject import CodexInjectError, inject_codex_message
from .config import Config
from .render import tidy_prompt, to_telegram_html
from .telegram import Telegram, TelegramError, send_with_retry

log = logging.getLogger("bridge.broker")

# getUpdates long-poll seconds. Also the loop cadence and the worst-case latency
# for shipping a response to Telegram / retrying a failed injection. Kept short
# (rather than a more typical 20-30s long-poll) because outbox mirroring — a
# session's reply reaching the topic — sits behind this same loop iteration;
# a longer value directly adds to how long a reply takes to show up.
POLL_TIMEOUT = 2
SPECIAL = {"/status", "/sessions", "/help", "/exit", "/title"}

# Prepended once to the first message ever injected from Telegram into a given
# session — never again after that (see `telegram_touched` on the session
# record). It becomes part of that session's own transcript, so later turns
# (even ones typed at the desktop) still have it in context; that's what makes
# "once touched from Telegram, stay in that mode" possible without a Claude
# Code API to actually disable a tool from outside.
REMOTE_SESSION_NOTICE = (
    "[Remote session notice] This session is now also being operated remotely "
    "via Telegram. The user may not be at their desktop, so from now on, ask "
    "questions as plain text and wait for a reply instead of interactive UI "
    "like AskUserQuestion.\n\n"
)

# Reacted onto the user's own message once it's handed to the session, so
# there's an immediate signal even when the reply itself is still a few
# seconds out. Claude-only: its socket write either succeeds or raises, so
# the reaction can honestly mean "received". Codex gets none — codex queue
# succeeding just means the thread id was once real, not that a live session
# picked the message up (see codex_inject.py), so it can't honestly claim
# "received" either; a separate weaker "queued" reaction existed briefly but
# was dropped as more confusing than useful. Telegram's reaction set is a
# fixed, undocumented list, not "any emoji" — verified these against the
# live Bot API (setMessageReaction) directly, since silent failure here
# previously went unlogged and unnoticed. Confirmed invalid: 🐮 ⏳ ✅ ☑️ ✔️ 🐼
# 🐨 🐸 🦊.
RECEIVED_REACTION = "👀"

# Telegram's fixed set of forum-topic icon colors (createForumTopic's
# icon_color — one of exactly 6 presets, no arbitrary hex). Kept distinct per
# agent kind so topics are tellable apart in the topic list even after the
# name gets overwritten by an ai_title/`/title`. Chosen as the closest
# approximation of each agent's own brand color: coral (#FB6F5F) for Claude's
# orange, pale yellow (#FFD67E) for Codex's white/neutral mark.
ICON_COLOR = {"claude": 16478047, "codex": 16766590}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# session record helpers
# --------------------------------------------------------------------------


def _read_session(sid: str) -> dict | None:
    f = paths.session_file(sid)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_session(sid: str, rec: dict) -> None:
    tmp = paths.session_file(sid).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    tmp.replace(paths.session_file(sid))


def _sid_for_thread(thread_id: int) -> str | None:
    f = paths.thread_file(thread_id)
    if not f.exists():
        return None
    return f.read_text().strip() or None


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with open(lock, "w") as fh, _file_locked(fh):
        yield


def _inbox_append(sid: str, text: str) -> None:
    """Queue a command that failed to inject, for retry on a later loop."""
    f = paths.inbox_file(sid)
    with _locked(f), f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"text": text, "ts": _now()}, ensure_ascii=False) + "\n")


def _inbox_lines(sid: str) -> list[str]:
    f = paths.inbox_file(sid)
    if not f.exists():
        return []
    return [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _inbox_rewrite(sid: str, lines: list[str]) -> None:
    f = paths.inbox_file(sid)
    with _locked(f):
        f.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


# A turn that has "run" for longer than this is treated as a stale marker left
# by a crashed session, not real activity.
_BUSY_STALE_S = 3600


def _busy_seconds(sid: str) -> int | None:
    """Seconds since the session's current turn started, or None if it's idle."""
    try:
        age = int(time.time() - paths.busy_file(sid).stat().st_mtime)
    except OSError:
        return None
    return age if 0 <= age < _BUSY_STALE_S else None


def _wipe_outbox(sid: str) -> None:
    outdir = paths.outbox_dir(sid)
    if outdir.exists():
        for f in outdir.iterdir():
            f.unlink(missing_ok=True)
        outdir.rmdir()


def _forget_session(sid: str, thread_id: int | None) -> None:
    """Wipe all local state for a session. Does NOT delete the Telegram topic."""
    inbox = paths.inbox_file(sid)
    for p in (
        paths.session_file(sid),
        inbox,
        inbox.with_name(inbox.name + ".lock"),
        paths.REGISTER / f"{sid}.json",
        paths.END / f"{sid}.json",
    ):
        p.unlink(missing_ok=True)
    if thread_id is not None:
        paths.thread_file(thread_id).unlink(missing_ok=True)
    paths.busy_file(sid).unlink(missing_ok=True)
    paths.pending_file(sid).unlink(missing_ok=True)
    _wipe_outbox(sid)


# --------------------------------------------------------------------------
# broker
# --------------------------------------------------------------------------


class Broker:
    def __init__(self, cfg: Config) -> None:
        cfg.validate()
        self.cfg = cfg
        self.tg = Telegram(cfg.bot_token, timeout=POLL_TIMEOUT + 15)
        self._running = True

    # --- lifecycle ---------------------------------------------------

    def run(self) -> None:
        paths.ensure_dirs()
        paths.STOP_FLAG.unlink(missing_ok=True)  # stale flag from a prior run
        signal.signal(signal.SIGTERM, self._stop)
        signal.signal(signal.SIGINT, self._stop)
        self._init_offset()
        log.info("broker up (chat_id=%s, offset=%s)", self.cfg.chat_id, self._offset)
        while self._running and not paths.STOP_FLAG.exists():
            try:
                self._process_registrations()
                self._process_outbox()   # mirror prompts/responses to topics
                self._process_inbox()    # retry commands that failed to inject
                self._process_end()
                self._process_updates()  # long-poll (POLL_TIMEOUT) sits here
            except TelegramError as e:
                log.warning("telegram error: %s", e)
                time.sleep(3)
            except Exception:
                log.exception("unexpected error in main loop")
                time.sleep(3)
        self.tg.close()
        log.info("broker stopped")

    def _stop(self, *_: object) -> None:
        log.info("signal received, shutting down")
        self._running = False

    # --- offset ---------------------------------------------------

    def _init_offset(self) -> None:
        if paths.OFFSET_FILE.exists():
            self._offset = int(paths.OFFSET_FILE.read_text().strip() or "0")
            return
        # First run: fast-forward past any backlog so we don't replay old chatter.
        try:
            updates = self.tg.get_updates(offset=-1, timeout=0)
        except TelegramError:
            updates = []
        self._offset = (updates[-1]["update_id"] + 1) if updates else 0
        self._save_offset()

    def _save_offset(self) -> None:
        paths.OFFSET_FILE.write_text(str(self._offset))

    # --- registrations -> topics -----------------------------------

    _MSG_FIELDS = ("messaging_socket", "messaging_token", "pid")

    def _process_registrations(self) -> None:
        for f in sorted(paths.REGISTER.glob("*.json")):
            try:
                req = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                f.unlink(missing_ok=True)
                continue
            sid = req.get("session_id") or f.stem

            existing = _read_session(sid)
            if existing and existing.get("status") == "ended":
                # The session was /exit'd (or ended) but has come back. Drop the
                # frozen record + its dead topic mapping and fall through to make
                # a fresh topic for this run.
                paths.thread_file(existing.get("thread_id")).unlink(missing_ok=True)
                paths.session_file(sid).unlink(missing_ok=True)
                paths.busy_file(sid).unlink(missing_ok=True)
                log.info("session %s resumed after exit — new topic", existing.get("label", sid))
                existing = None
            if existing:
                # resume/clear: pid (hence socket) may have changed -> refresh.
                changed = False
                for k in self._MSG_FIELDS:
                    if req.get(k) and req.get(k) != existing.get(k):
                        existing[k] = req[k]
                        changed = True
                if "kind" not in existing and req.get("kind"):
                    # backfills records made before kind existed (or a Claude
                    # session's, which still doesn't send one — stays "claude").
                    existing["kind"] = req["kind"]
                    changed = True
                if changed:
                    _write_session(sid, existing)
                    log.info("refreshed messaging socket for %s", existing.get("label", sid))
                f.unlink(missing_ok=True)
                continue

            label = req.get("label") or sid[:12]
            cwd = req.get("cwd", "?")
            base = req.get("base") or label
            kind = req.get("kind", "claude")
            initial = f"{'[codex] ' if kind == 'codex' else ''}{base} …"
            try:
                thread_id = self.tg.create_forum_topic(
                    self.cfg.chat_id, initial, icon_color=ICON_COLOR.get(kind)
                )
            except TelegramError as e:
                log.error("createForumTopic failed for %s: %s", sid, e)
                send_with_retry(
                    self.tg,
                    self.cfg.chat_id,
                    f"⚠️ could not create topic for session {label} ({sid}): {e}",
                )
                f.unlink(missing_ok=True)
                continue
            rec = {
                "session_id": sid,
                "kind": kind,
                "label": label,
                "base": base,
                "cwd": cwd,
                "thread_id": thread_id,
                "status": "active",
                "titled": False,
                "telegram_touched": False,
                "messaging_socket": req.get("messaging_socket", ""),
                "messaging_token": req.get("messaging_token", ""),
                "pid": req.get("pid", ""),
                "started": _now(),
            }
            _write_session(sid, rec)
            paths.thread_file(thread_id).write_text(sid)
            f.unlink(missing_ok=True)
            # Codex has no socket to check — `codex queue` just needs the session id.
            can_inject = kind == "codex" or bool(rec["messaging_socket"] and rec["messaging_token"])
            header = (
                f"🟢 {base}\n"
                f"cwd: {cwd}\n"
                f"id: {sid}\n\n"
                + (
                    "Send a message here and it goes straight into this session.\n"
                    if can_inject
                    else "⚠️ This session has no socket info, so commands can't be "
                    "injected here (mirror-only).\n"
                )
                + "/status  /exit  /title <text>"
            )
            send_with_retry(self.tg, self.cfg.chat_id, header, message_thread_id=thread_id)
            log.info("registered %s -> topic %s (kind=%s inject=%s)", label, thread_id, kind, can_inject)

    # --- inbound updates -> session -------------------------------

    def _process_updates(self) -> None:
        updates = self.tg.get_updates(offset=self._offset, timeout=POLL_TIMEOUT)
        for upd in updates:
            self._offset = upd["update_id"] + 1
            msg = upd.get("message")
            if msg:
                try:
                    self._handle_message(msg)
                except Exception:
                    log.exception("failed handling update %s", upd.get("update_id"))
            self._save_offset()  # per-update so a crash never replays a command

    def _handle_message(self, msg: dict) -> None:
        text = msg.get("text")
        if not text or not text.strip():
            return  # service message, media without caption, whitespace, etc.
        thread_id = msg.get("message_thread_id")
        if thread_id is None:
            self._reply_general(msg)
            return
        sid = _sid_for_thread(thread_id)
        if not sid:
            return  # a topic we don't manage

        rec = _read_session(sid)
        if not rec:
            return

        cmd = text.strip()
        if cmd.split()[0] in SPECIAL:
            self._handle_special(sid, rec, thread_id, cmd)
            return

        if rec.get("status") == "ended":
            self._say(thread_id, "session has ended — message ignored. (/exit to delete this topic)")
            return

        kind = rec.get("kind", "claude")
        if kind != "codex" and not (rec.get("messaging_socket") and rec.get("messaging_token")):
            self._say(thread_id, "This session has no socket info, so messages can't be injected (mirror-only).")
            return

        if not rec.get("telegram_touched"):
            text = REMOTE_SESSION_NOTICE + text
            rec["telegram_touched"] = True
            _write_session(sid, rec)

        busy = _busy_seconds(sid)
        try:
            if kind == "codex":
                inject_codex_message(sid, text)
            else:
                inject_user_message(sid, rec["messaging_socket"], rec["messaging_token"], text)
            log.info("injected -> %s (%d chars)", rec["label"], len(text))
        except (InjectError, CodexInjectError) as e:
            _inbox_append(sid, text)
            self._say(thread_id, "⚠️ Couldn't reach the session directly. Queued for retry.")
            log.warning("inject failed for %s: %s (queued)", rec["label"], e)
            return
        message_id = msg.get("message_id")
        if message_id is not None and kind != "codex":
            self.tg.set_message_reaction(self.cfg.chat_id, message_id, RECEIVED_REACTION)
        if busy is not None:
            self._say(thread_id, f"⏳ Busy ({busy}s) — this message will be handled once the current turn finishes.")

    def _handle_special(self, sid: str, rec: dict, thread_id: int, cmd: str) -> None:
        head = cmd.split()[0]
        if head == "/help":
            self._say(
                thread_id,
                "Just send a message to deliver it to this session.\n"
                "/status        show status\n"
                "/exit          delete this topic (local session record is kept)\n"
                "/title <text>  rename the topic\n"
                "/sessions      list all sessions",
            )
        elif head == "/title":
            new = cmd[len("/title"):].strip()
            if not new:
                self._say(thread_id, "usage: /title <new topic name>")
            elif self.tg.edit_forum_topic(self.cfg.chat_id, thread_id, new[:128]):
                rec["titled"] = True
                _write_session(sid, rec)
            else:
                self._say(thread_id, "couldn't rename the topic.")
        elif head == "/status":
            kind = rec.get("kind", "claude")
            if kind == "codex":
                delivery = "codex queue"
            else:
                sock = rec.get("messaging_socket", "")
                reachable = bool(sock) and Path(sock).exists()
                delivery = "ok" if reachable else ("missing" if sock else "unknown")
            pending = len(_inbox_lines(sid))
            busy = _busy_seconds(sid)
            activity = f"🔧 busy ({busy}s)" if busy is not None else "idle"
            self._say(
                thread_id,
                f"label: {rec['label']}\nstatus: {rec['status']}"
                f"\nkind: {kind}"
                f"\nactivity: {activity}"
                f"\nsocket: {delivery}"
                f"\npending (retry): {pending}\ncwd: {rec['cwd']}",
            )
        elif head == "/sessions":
            self._say(thread_id, _sessions_summary())
        elif head == "/exit":
            # Delete the Telegram topic but keep the local session record, the
            # same way `/exit` in the terminal ends the session without deleting
            # its transcript. Mark it ended so the broker stops mirroring to the
            # now-gone topic; `bridge prune` clears the record later.
            deleted = self.tg.delete_forum_topic(self.cfg.chat_id, thread_id)
            paths.thread_file(thread_id).unlink(missing_ok=True)
            paths.busy_file(sid).unlink(missing_ok=True)
            rec["status"] = "ended"
            rec["ended"] = _now()
            _write_session(sid, rec)
            _inbox_rewrite(sid, [])
            _wipe_outbox(sid)
            if not deleted:
                self._say(thread_id, "Couldn't delete this topic — remove it manually.")
            log.info("exited %s (topic %s deleted=%s, record kept)", rec["label"], thread_id, deleted)

    def _reply_general(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        self.tg.send_message(chat_id, "Send messages inside a session's topic, not here.")

    # --- inbox retry -> session ---------------------------------

    def _process_inbox(self) -> None:
        for f in sorted(paths.INBOX.glob("*.jsonl")):
            sid = f.stem
            lines = _inbox_lines(sid)
            if not lines:
                continue
            rec = _read_session(sid)
            if rec is None or rec.get("status") == "ended":
                _inbox_rewrite(sid, [])
                continue
            kind = rec.get("kind", "claude")
            sock, tok = rec.get("messaging_socket", ""), rec.get("messaging_token", "")
            if kind != "codex" and not (sock and tok):
                continue
            remaining = list(lines)
            for line in lines:
                try:
                    text = json.loads(line).get("text", "")
                except json.JSONDecodeError:
                    remaining.pop(0)
                    continue
                try:
                    if kind == "codex":
                        inject_codex_message(sid, text)
                    else:
                        inject_user_message(sid, sock, tok, text)
                except (InjectError, CodexInjectError):
                    break  # still unreachable; keep this line and the rest
                remaining.pop(0)
                log.info("retry-injected -> %s", rec["label"])
            _inbox_rewrite(sid, remaining)

    # --- outbox -> telegram --------------------------------------

    def _process_outbox(self) -> None:
        if not paths.OUTBOX.exists():
            return
        for sdir in sorted(paths.OUTBOX.iterdir()):
            if not sdir.is_dir():
                continue
            sid = sdir.name
            rec = _read_session(sid)
            if rec is None:
                # No session record. If a registration is still pending, hold the
                # files (topic is about to exist). Otherwise it's an orphan.
                if not (paths.REGISTER / f"{sid}.json").exists():
                    _wipe_outbox(sid)
                continue
            if rec.get("status") == "ended":
                # /exit or SessionEnd — the topic is gone or frozen, drop the
                # mirror files instead of retrying forever.
                _wipe_outbox(sid)
                continue
            thread_id = rec["thread_id"]
            for f in sorted([*sdir.glob("*.json"), *sdir.glob("*.txt")]):
                role, text, ai_title = _read_outbox_item(f)
                if role == "user":
                    tidied = tidy_prompt(text)
                    if tidied is None:
                        f.unlink(missing_ok=True)
                        continue
                    role, text = tidied
                if ai_title and not rec.get("titled") and thread_id:
                    name = ai_title[:128]
                    if self.tg.edit_forum_topic(self.cfg.chat_id, thread_id, name):
                        rec["titled"] = True
                        _write_session(sid, rec)
                        log.info("titled topic %s: %s", thread_id, name)
                ok = send_with_retry(
                    self.tg,
                    self.cfg.chat_id,
                    _format_outbox(role, text),
                    message_thread_id=thread_id,
                    parse_mode="HTML",
                )
                if ok:
                    log.info("sent -> %s (%s, %d chars)", rec["label"], role, len(text))
                    f.unlink(missing_ok=True)
                else:
                    log.warning("failed to send outbox %s, will retry", f)
                    break

    # --- end -> cleanup ----------------------------------------

    def _process_end(self) -> None:
        for f in sorted(paths.END.glob("*.json")):
            sid = f.stem
            rec = _read_session(sid)
            tid = rec.get("thread_id") if rec else None
            if rec and self.cfg.delete_topic_on_end:
                if tid is not None:
                    self.tg.delete_forum_topic(self.cfg.chat_id, tid)
                _forget_session(sid, tid)
                log.info("session %s ended -> topic %s deleted", sid, tid)
            elif rec:
                rec["status"] = "ended"
                rec["ended"] = _now()
                _write_session(sid, rec)
                if tid is not None:
                    self._say(tid, "🔴 session ended. (/exit to delete this topic)")
                log.info("session %s ended", sid)
            f.unlink(missing_ok=True)

    # --- small helpers ---------------------------------------

    def _say(self, thread_id: int, text: str) -> None:
        send_with_retry(self.tg, self.cfg.chat_id, text, message_thread_id=thread_id)


_ROLE_PREFIX = {"user": "🐮 ", "assistant": "🤖 ", "note": "⚠️ ", "event": "🔔 "}
# _format_outbox output is sent with parse_mode="HTML" (see _process_outbox).


def _read_outbox_item(path: Path) -> tuple[str, str, str]:
    """Return (role, text, ai_title) for an outbox file.

    ai_title is Claude Code's own session title when the hook forwarded one,
    else "". Legacy .txt files are bare assistant text."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            obj = json.loads(raw)
            return (
                str(obj.get("role", "assistant")),
                str(obj.get("text", "")),
                str(obj.get("ai_title", "")),
            )
        except (json.JSONDecodeError, AttributeError):
            return "assistant", raw, ""
    return "assistant", raw, ""


def _format_outbox(role: str, text: str) -> str:
    """Role emoji + the message body rendered as Telegram HTML."""
    return _ROLE_PREFIX.get(role, "") + to_telegram_html(text)


def _sessions_summary() -> str:
    rows = []
    for f in sorted(paths.SESSIONS.glob("*.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        sid = r["session_id"]
        act = "🔧" if _busy_seconds(sid) is not None else "  "
        tag = "codex" if r.get("kind") == "codex" else "claude"
        rows.append(f"{act} {r['label']:<24} {tag:<6} {r['status']:<8} q={len(_inbox_lines(sid))}")
    return "\n".join(rows) if rows else "(no sessions)"


# --------------------------------------------------------------------------
# entry point used by the CLI
# --------------------------------------------------------------------------


def _setup_logging(foreground: bool) -> None:
    paths.ensure_dirs()
    handlers: list[logging.Handler] = [logging.FileHandler(paths.LOG_FILE, encoding="utf-8")]
    if foreground:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main(foreground: bool = True) -> None:
    _setup_logging(foreground)
    if paths.PID_FILE.exists():
        old = paths.PID_FILE.read_text().strip()
        if old and old.isdigit() and _alive(int(old)):
            raise SystemExit(f"broker already running (pid {old})")
    paths.PID_FILE.write_text(str(os.getpid()))
    try:
        Broker(Config.load()).run()
    finally:
        paths.PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    # spawned by `bridge start` with stdout/stderr already pointed at the log file
    main(foreground=False)
