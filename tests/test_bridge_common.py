"""Hook-side stdlib helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path

import _bridge_common as bc
from conftest import transcript


def test_queue_outbox_writes_role_and_text():
    bc.queue_outbox("sid1", "user", "안녕하세요")
    files = list((bc.OUTBOX / "sid1").iterdir())
    assert len(files) == 1
    obj = json.loads(files[0].read_text())
    assert obj == {"role": "user", "text": "안녕하세요"}


def test_last_assistant_text_takes_final_assistant(tmp_path):
    t = transcript(
        tmp_path / "t.jsonl",
        [("user", "hi"), ("assistant", "first"), ("user", "more"), ("assistant", "final answer")],
    )
    assert bc.last_assistant_text(str(t)) == "final answer"


def test_last_assistant_text_joins_every_segment_since_the_turn_started(tmp_path):
    # A turn commonly has several assistant messages interleaved with tool
    # calls (narration, tool call, more narration, ...) — all of it is real
    # content, not just whichever one happened to come last. This is the
    # exact shape of a real bug: only "final" used to reach Telegram.
    t = transcript(
        tmp_path / "t.jsonl",
        [
            ("user", "do the migration"),
            ("assistant", "first, backing up"),
            ("assistant", "backup done, now the DDL"),
            ("assistant", "final: all done, 151 tests passed"),
        ],
    )
    assert bc.last_assistant_text(str(t)) == (
        "first, backing up\n\nbackup done, now the DDL\n\nfinal: all done, 151 tests passed"
    )


def test_last_assistant_text_does_not_leak_earlier_turns(tmp_path):
    t = transcript(
        tmp_path / "t.jsonl",
        [
            ("user", "first request"),
            ("assistant", "first response"),
            ("user", "second request"),
            ("assistant", "second response part 1"),
            ("assistant", "second response part 2"),
        ],
    )
    assert bc.last_assistant_text(str(t)) == "second response part 1\n\nsecond response part 2"


def test_last_assistant_text_missing_file():
    assert bc.last_assistant_text("/no/such/file") == "(transcript unavailable)"


def _write_raw(path, lines: list[dict]):
    path.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")
    return path


def test_last_assistant_text_summarizes_tool_calls_when_no_text(tmp_path):
    # A real turn can do substantial work — tool calls only, no narration.
    # "(no text in final response)" was a bare, unhelpful placeholder for
    # this; a tool-name summary at least says something happened.
    t = _write_raw(tmp_path / "t.jsonl", [
        {"type": "user", "message": {"role": "user", "content": "clean up the old files"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Read", "input": {}},
        ]}},
    ])
    assert bc.last_assistant_text(str(t)) == "🔧 Ran tools without a text response: Bash×2, Read"


def test_last_assistant_text_retries_a_torn_final_write(tmp_path, monkeypatch):
    # Real bug: Claude Code can still be flushing the turn's last message to
    # disk exactly when Stop fires. A torn last line failed to parse and was
    # silently dropped — losing exactly the turn's real conclusion while
    # earlier, already-flushed lines (progress notes) still went out,
    # looking complete. Simulate the write finishing a couple of reads in.
    complete = (
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "final answer"}]}}) + "\n"
    )
    torn = complete[:-20]  # cuts the last line mid-JSON
    t = tmp_path / "t.jsonl"
    t.write_text(torn, encoding="utf-8")

    reads = {"n": 0}
    real_read_text = Path.read_text

    def flaky_read_text(self, *a, **k):
        reads["n"] += 1
        if reads["n"] >= 3:
            t.write_text(complete, encoding="utf-8")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)  # don't actually wait in tests

    assert bc.last_assistant_text(str(t)) == "final answer"
    assert reads["n"] >= 3


def test_last_assistant_text_retries_when_final_text_message_is_missing_outright(
    tmp_path, monkeypatch
):
    # Real bug, found from a live transcript: a long final response can lose
    # the race entirely rather than arriving torn — Stop fires and the hook
    # reads the file *before* the concluding text message has been appended
    # at all. That's indistinguishable at read time from a genuine tool-only
    # turn (valid JSON throughout, just fewer lines than the finished turn
    # will have), so the parse-failure retry in _read_transcript_objs never
    # triggers. Simulate the missing line landing a couple of reads in.
    before_text = (
        json.dumps({"type": "user", "message": {"role": "user", "content": "status?"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]}}) + "\n"
    )
    after_text = before_text + json.dumps({"type": "assistant", "message": {"role": "assistant",
        "content": [{"type": "text", "text": "progress report: 67/2074 done"}]}}) + "\n"
    t = tmp_path / "t.jsonl"
    t.write_text(before_text, encoding="utf-8")

    reads = {"n": 0}
    real_read_text = Path.read_text

    def flaky_read_text(self, *a, **k):
        reads["n"] += 1
        if reads["n"] >= 3:
            t.write_text(after_text, encoding="utf-8")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)

    assert bc.last_assistant_text(str(t)) == "progress report: 67/2074 done"


def test_last_assistant_text_gives_up_after_retries_exhausted(tmp_path, monkeypatch):
    # A last line that's persistently broken (not a transient torn write)
    # must not hang forever or silently return nothing — the rest of the
    # (complete) turn still gets mirrored.
    t = tmp_path / "t.jsonl"
    t.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "partial"}]}}) + "\n"
        + '{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "cut off mid',
        encoding="utf-8",
    )
    monkeypatch.setattr(bc.time, "sleep", lambda s: None)
    assert bc.last_assistant_text(str(t)) == "partial"


def test_last_assistant_text_none_for_a_genuinely_empty_machine_turn(tmp_path):
    # A synthetic/machine turn (slash command, background-task notification,
    # local-command echo) that produced neither text nor a tool call has
    # nothing worth mirroring — the caller (stop.py) should skip it entirely,
    # the same way tidy_prompt already skips these on the prompt side.
    t = _write_raw(tmp_path / "t.jsonl", [
        {"type": "user", "message": {"role": "user", "content": "<command-name>/compact</command-name>"}},
    ])
    assert bc.last_assistant_text(str(t)) is None


def test_write_json_atomic_roundtrip(tmp_path):
    p = tmp_path / "d" / "x.json"
    bc.write_json_atomic(p, {"a": 1, "ko": "값"})
    assert bc.read_json(p) == {"a": 1, "ko": "값"}
    assert not p.with_name(p.name + ".tmp").exists()


def test_ts_is_sortable():
    a = bc.ts()
    b = bc.ts()
    assert a <= b
    assert "T" in a


# --- consume_pending_injection (Codex echo suppression) ----------------------


def test_consume_pending_injection_matches_and_removes():
    f = bc.PENDING / "sidX.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([{"text": "hello from telegram", "ts": time.time()}]))

    assert bc.consume_pending_injection("sidX", "hello from telegram") is True
    assert json.loads(f.read_text()) == []


def test_consume_pending_injection_no_match_returns_false():
    assert bc.consume_pending_injection("sidY", "never queued") is False


def test_consume_pending_injection_leaves_other_entries():
    f = bc.PENDING / "sidZ.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    f.write_text(json.dumps([{"text": "one", "ts": now}, {"text": "two", "ts": now}]))

    assert bc.consume_pending_injection("sidZ", "one") is True
    assert json.loads(f.read_text()) == [{"text": "two", "ts": now}]


def test_consume_pending_injection_prunes_stale_entries():
    f = bc.PENDING / "sidW.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([{"text": "old", "ts": time.time() - 999}]))

    assert bc.consume_pending_injection("sidW", "old") is False  # too stale to match
    assert json.loads(f.read_text()) == []  # pruned along the way


def test_consume_pending_injection_matches_claude_wrapped_prompt():
    # Claude Code wraps the original text in a peer-message preamble before
    # UserPromptSubmit sees it, unlike Codex which passes it through verbatim
    # — so this must match by substring, not by exact equality.
    f = bc.PENDING / "sidV.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([{"text": "run the tests", "ts": time.time()}]))

    wrapped = (
        "Another Claude session sent a message:\nrun the tests\n\n"
        "This came from another Claude session — not typed by your user..."
    )
    assert bc.consume_pending_injection("sidV", wrapped) is True
    assert json.loads(f.read_text()) == []
