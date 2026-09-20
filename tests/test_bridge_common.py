"""Hook-side stdlib helpers."""

from __future__ import annotations

import json
import time

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


def test_last_assistant_text_missing_file():
    assert bc.last_assistant_text("/no/such/file") == "(transcript unavailable)"


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
