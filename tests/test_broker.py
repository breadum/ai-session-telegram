"""Broker loop steps, with a fake Telegram and a stubbed injector."""

from __future__ import annotations

import json

import fakes

from ai_session_telegram import broker, paths


def _register(sid="s1", socket="/run/cc-socks/9.sock", token="tok9"):
    paths.ensure_dirs()
    (paths.REGISTER / f"{sid}.json").write_text(json.dumps({
        "session_id": sid, "label": f"proj-{sid}", "base": "proj", "cwd": "/w/proj",
        "messaging_socket": socket, "messaging_token": token, "pid": "9",
    }))


def _register_codex(sid="cx1"):
    paths.ensure_dirs()
    (paths.REGISTER / f"{sid}.json").write_text(json.dumps({
        "session_id": sid, "kind": "codex", "label": f"proj-{sid}", "base": "proj", "cwd": "/w/proj",
    }))


def _mark_telegram_touched(sid="s1"):
    """So a test can send a message without tripping the one-time remote-session
    notice (see test_first_telegram_message_gets_remote_notice_once for that)."""
    rec = broker._read_session(sid)
    rec["telegram_touched"] = True
    broker._write_session(sid, rec)


def test_registration_creates_topic(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["thread_id"] == 101
    assert rec["messaging_socket"] == "/run/cc-socks/9.sock"
    assert rec["status"] == "active"
    assert paths.thread_file(101).read_text() == "s1"
    assert fake.created == [(-1001, "proj …")]
    assert fake.icon_colors == [broker.ICON_COLOR["claude"]]
    assert any("proj" in t for _, t, *_ in fake.sent)  # header sent to topic
    assert not (paths.REGISTER / "s1.json").exists()


def test_registration_refreshes_socket_on_resume(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    assert len(fake.created) == 1

    # resume: same sid, new pid/socket
    _register(socket="/run/cc-socks/77.sock", token="tok77")
    b._process_registrations()

    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["messaging_socket"] == "/run/cc-socks/77.sock"
    assert rec["messaging_token"] == "tok77"
    assert len(fake.created) == 1  # no second topic


def test_codex_resume_removes_legacy_topic_prefix(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    fake.edited.clear()

    _register_codex()
    b._process_registrations()

    assert fake.edited == [(-1001, 101, "proj …")]


def test_startup_migrates_legacy_codex_topic_names(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    fake.edited.clear()

    b._migrate_codex_topic_names()

    assert fake.edited == [(-1001, 101, "proj …")]


def test_topic_message_is_injected(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    _mark_telegram_touched()

    calls = []
    monkeypatch.setattr(
        broker, "inject_user_message", lambda sid, s, t, text: calls.append((s, t, text))
    )

    b._handle_message({"message_thread_id": 101, "text": "run the build"})
    assert calls == [("/run/cc-socks/9.sock", "tok9", "run the build")]
    # session was idle -> no "queued behind current turn" note
    assert not any("Busy" in t for _, t, *_ in fake.sent)


def test_successful_injection_reacts_to_the_original_message(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    _mark_telegram_touched()
    monkeypatch.setattr(broker, "inject_user_message", lambda sid, s, t, text: None)

    b._handle_message({"message_thread_id": 101, "message_id": 555, "text": "run the build"})
    assert fake.reactions == [(-1001, 555, broker.RECEIVED_REACTION)]


def test_no_message_id_is_fine_no_reaction_attempted(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    _mark_telegram_touched()
    monkeypatch.setattr(broker, "inject_user_message", lambda sid, s, t, text: None)

    b._handle_message({"message_thread_id": 101, "text": "no message_id here"})
    assert fake.reactions == []


def test_first_telegram_message_gets_remote_notice_once(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    calls = []
    monkeypatch.setattr(
        broker, "inject_user_message", lambda sid, s, t, text: calls.append((s, t, text))
    )

    b._handle_message({"message_thread_id": 101, "text": "first"})
    b._handle_message({"message_thread_id": 101, "text": "second"})

    first_text, second_text = calls[0][2], calls[1][2]
    assert first_text == broker.REMOTE_SESSION_NOTICE + "first"
    assert second_text == "second"  # not repeated
    assert json.loads(paths.session_file("s1").read_text())["telegram_touched"] is True


def _mark_busy(sid="s1"):
    paths.BUSY.mkdir(parents=True, exist_ok=True)
    paths.busy_file(sid).write_text("2026-01-01T00:00:00")


def test_message_while_busy_warns_it_is_queued(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    _mark_busy()
    monkeypatch.setattr(broker, "inject_user_message", lambda *a: None)

    b._handle_message({"message_thread_id": 101, "text": "one more thing"})
    assert any("Busy" in t and "current turn" in t for _, t, *_ in fake.sent)


def test_status_reports_activity(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()

    b._handle_message({"message_thread_id": 101, "text": "/status"})
    assert any("activity: idle" in t for _, t, *_ in fake.sent)

    fake.sent.clear()
    _mark_busy()
    b._handle_message({"message_thread_id": 101, "text": "/status"})
    assert any("activity: 🔧 busy" in t for _, t, *_ in fake.sent)


def test_failed_injection_is_queued_for_retry(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    _mark_telegram_touched()

    def boom(*a):
        raise broker.InjectError("no socket")

    monkeypatch.setattr(broker, "inject_user_message", boom)
    b._handle_message({"message_thread_id": 101, "text": "later"})

    lines = paths.inbox_file("s1").read_text().splitlines()
    assert json.loads(lines[0])["text"] == "later"
    assert any("retry" in t for _, t, *_ in fake.sent)

    # now the socket comes back; retry drains the queue
    ok = []
    monkeypatch.setattr(broker, "inject_user_message", lambda sid, s, t, text: ok.append(text))
    b._process_inbox()
    assert ok == ["later"]
    assert paths.inbox_file("s1").read_text().strip() == ""


def test_slash_exit_deletes_topic_but_keeps_session_record(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    broker._inbox_append("s1", "queued")
    paths.outbox_dir("s1").mkdir(parents=True, exist_ok=True)
    (paths.outbox_dir("s1") / "x.json").write_text('{"role":"assistant","text":"hi"}')

    _mark_busy()
    b._handle_message({"message_thread_id": 101, "text": "/exit"})

    assert fake.deleted == [(-1001, 101)]
    assert not paths.thread_file(101).exists()          # dead routing dropped
    assert not paths.busy_file("s1").exists()           # activity marker cleared
    assert paths.inbox_file("s1").read_text().strip() == ""
    assert not paths.outbox_dir("s1").exists()          # mirror queue wiped
    rec = json.loads(paths.session_file("s1").read_text())  # record kept
    assert rec["status"] == "ended"


def test_exited_session_outbox_is_dropped_not_retried(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    b._handle_message({"message_thread_id": 101, "text": "/exit"})
    fake.sent.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "late.json").write_text('{"role":"assistant","text":"late reply"}')
    b._process_outbox()
    assert fake.sent == []
    assert not d.exists()


def test_resume_after_exit_gets_a_fresh_topic(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    b._handle_message({"message_thread_id": 101, "text": "/exit"})

    _register()  # SessionStart fires again on resume
    b._process_registrations()

    assert len(fake.created) == 2                       # a new topic, not reused
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["status"] == "active"
    assert rec["thread_id"] == 102


def test_message_to_ended_session_is_ignored(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    # mark ended without deleting the topic (SessionEnd, delete_topic_on_end off)
    rec = json.loads(paths.session_file("s1").read_text())
    rec["status"] = "ended"
    paths.session_file("s1").write_text(json.dumps(rec))
    fake.sent.clear()

    monkeypatch.setattr(broker, "inject_user_message", lambda *a: (_ for _ in ()).throw(AssertionError("injected!")))
    b._handle_message({"message_thread_id": 101, "text": "hello?"})
    assert any("ended" in t for _, t, *_ in fake.sent)


def test_codex_session_end_deletes_topic_even_when_option_is_off(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    (paths.END / "cx1.json").write_text(json.dumps({"session_id": "cx1"}))

    b._process_end()

    assert fake.deleted == [(-1001, 101)]
    assert not paths.session_file("cx1").exists()
    assert not paths.thread_file(101).exists()


def test_session_end_keeps_state_when_topic_mapping_is_not_owned(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    paths.thread_file(101).write_text("another-session")
    (paths.END / "cx1.json").write_text(json.dumps({"session_id": "cx1"}))

    b._process_end()

    assert fake.deleted == []
    assert paths.session_file("cx1").exists()
    assert (paths.END / "cx1.json").exists()


def test_session_end_retries_when_topic_deletion_fails(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    monkeypatch.setattr(fake, "delete_forum_topic", lambda *args: False)
    (paths.END / "cx1.json").write_text(json.dumps({"session_id": "cx1"}))

    b._process_end()

    assert paths.session_file("cx1").exists()
    assert (paths.END / "cx1.json").exists()


def test_outbox_titles_topic_from_ai_title(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.edited.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps(
        {"role": "assistant", "text": "done", "ai_title": "Fix the flaky login test"}
    ))
    b._process_outbox()

    assert fake.edited and fake.edited[0][2] == "Fix the flaky login test"
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec["titled"] is True


def test_outbox_without_ai_title_does_not_rename(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.edited.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps({"role": "user", "text": "hello"}))
    b._process_outbox()

    assert fake.edited == []
    rec = json.loads(paths.session_file("s1").read_text())
    assert rec.get("titled") is False


def test_outbox_renders_markdown_as_html(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.sent.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    (d / "001.json").write_text(json.dumps(
        {"role": "assistant", "text": "## Done\n\n**bold** and `code` and <raw>"}
    ))
    b._process_outbox()

    _, text, thread, parse_mode = fake.sent[-1]
    assert parse_mode == "HTML"
    assert text.startswith("🤖 ")
    assert "<b>Done</b>" in text
    assert "<b>bold</b>" in text
    assert "<code>code</code>" in text
    assert "&lt;raw&gt;" in text and "<raw>" not in text
    assert "##" not in text and "**" not in text


def test_codex_registration_creates_topic_without_a_socket(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()

    rec = json.loads(paths.session_file("cx1").read_text())
    assert rec["kind"] == "codex"
    assert rec["thread_id"] == 101
    assert fake.created == [(-1001, "proj …")]
    assert fake.icon_colors == [broker.ICON_COLOR["codex"]]
    assert broker.ICON_COLOR["codex"] != broker.ICON_COLOR["claude"]
    header = next(t for _, t, *_ in fake.sent if "proj" in t)
    assert "goes straight into this session" in header  # can_inject even with no socket recorded


def test_codex_topic_message_is_injected_via_codex_queue(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    _mark_telegram_touched("cx1")

    calls = []
    monkeypatch.setattr(broker, "inject_codex_message", lambda sid, text: calls.append((sid, text)))

    b._handle_message({"message_thread_id": 101, "text": "run the build"})
    assert calls == [("cx1", "run the build")]


def test_codex_successful_injection_gets_no_reaction(monkeypatch):
    # codex queue succeeding only means the thread id was once real, not that
    # a live session is attached to pick the message up — Codex can't
    # honestly claim "received", so it gets no reaction at all (a separate
    # weaker "queued" reaction existed briefly but was dropped as confusing).
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    _mark_telegram_touched("cx1")
    monkeypatch.setattr(broker, "inject_codex_message", lambda sid, text: None)

    b._handle_message({"message_thread_id": 101, "message_id": 555, "text": "run the build"})
    assert fake.reactions == []


def test_codex_failed_injection_is_queued_for_retry(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    _mark_telegram_touched("cx1")

    def boom(sid, text):
        raise broker.CodexInjectError("codex CLI not found on PATH")

    monkeypatch.setattr(broker, "inject_codex_message", boom)
    b._handle_message({"message_thread_id": 101, "text": "later"})

    lines = paths.inbox_file("cx1").read_text().splitlines()
    assert json.loads(lines[0])["text"] == "later"
    assert any("retry" in t for _, t, *_ in fake.sent)

    ok = []
    monkeypatch.setattr(broker, "inject_codex_message", lambda sid, text: ok.append(text))
    b._process_inbox()
    assert ok == ["later"]
    assert paths.inbox_file("cx1").read_text().strip() == ""


def test_codex_gone_session_deletes_stale_topic(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    _mark_telegram_touched("cx1")

    def gone(sid, text):
        raise broker.CodexSessionGoneError("no thread named cx1")

    monkeypatch.setattr(broker, "inject_codex_message", gone)
    b._handle_message({"message_thread_id": 101, "text": "continue"})

    assert fake.deleted == [(-1001, 101)]
    assert not paths.session_file("cx1").exists()
    assert not paths.thread_file(101).exists()
    assert not paths.pending_file("cx1").exists()
    assert not paths.inbox_file("cx1").exists()


def test_registration_backfills_kind_on_legacy_record(monkeypatch):
    # A record written before "kind" existed (or by a broker that predates this
    # session's install) must not get stuck defaulting to "claude" forever.
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    rec = json.loads(paths.session_file("cx1").read_text())
    del rec["kind"]
    paths.session_file("cx1").write_text(json.dumps(rec))

    _register_codex()  # SessionStart fires again (resume), still says kind: codex
    b._process_registrations()

    assert json.loads(paths.session_file("cx1").read_text())["kind"] == "codex"
    assert len(fake.created) == 1  # no second topic


def test_codex_status_shows_queue_delivery_not_socket(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register_codex()
    b._process_registrations()
    fake.sent.clear()

    b._handle_message({"message_thread_id": 101, "text": "/status"})
    assert any("kind: codex" in t and "socket: codex queue" in t for _, t, *_ in fake.sent)


def test_outbox_tidies_task_notification(monkeypatch):
    b, fake = fakes.install(monkeypatch)
    _register()
    b._process_registrations()
    fake.sent.clear()

    d = paths.outbox_dir("s1")
    d.mkdir(parents=True, exist_ok=True)
    payload = (
        "<task-notification><status>completed</status>"
        '<summary>Background command "probe the fix" completed (exit code 0)</summary>'
        "</task-notification>"
    )
    (d / "001.json").write_text(json.dumps({"role": "user", "text": payload}))
    (d / "002.json").write_text(json.dumps(
        {"role": "user", "text": "<local-command-stdout></local-command-stdout>"}
    ))
    b._process_outbox()

    texts = [t for _, t, *_ in fake.sent]
    assert texts == ["🔔 probe the fix — completed (exit code 0)"]
    assert list(d.iterdir()) == []  # both consumed, the noise one silently
