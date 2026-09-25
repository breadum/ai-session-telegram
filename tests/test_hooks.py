"""Run the hook scripts the way Claude Code does: as subprocesses fed JSON on stdin."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import _bridge_common as bc

HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def run_hook(name: str, event: dict, env: dict, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(env)
    e.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=e,
        timeout=10,
    )


def test_session_start_writes_register_with_socket(hook_env):
    r = run_hook(
        "session_start.py",
        {"session_id": "sess-A", "cwd": "/home/x/proj", "source": "startup"},
        hook_env,
        {"CLAUDE_CODE_MESSAGING_SOCKET": "/run/x/cc-socks/1.sock",
         "CLAUDE_CODE_MESSAGING_TOKEN": "tkn", "CLAUDE_PID": "4242"},
    )
    assert r.returncode == 0
    reg = json.loads((bc.REGISTER / "sess-A.json").read_text())
    assert reg["base"] == "proj"
    assert reg["messaging_socket"] == "/run/x/cc-socks/1.sock"
    assert reg["messaging_token"] == "tkn"
    assert reg["pid"] == "4242"


def test_stop_hook_silent_for_unregistered_session(hook_env, tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}}
    ) + "\n")
    r = run_hook("stop.py", {"session_id": "ghost", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "ghost").exists()


def test_stop_hook_mirrors_response_for_registered_session(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-B"), {"session_id": "sess-B", "status": "active"})
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "the answer"}]}}
    ) + "\n")
    r = run_hook("stop.py", {"session_id": "sess-B", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-B").iterdir())
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == {"role": "assistant", "text": "the answer"}


def test_stop_hook_skips_outbox_for_a_genuinely_empty_machine_turn(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-M"), {"session_id": "sess-M", "status": "active"})
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(
        {"type": "user", "message": {"role": "user", "content": "<command-name>/compact</command-name>"}}
    ) + "\n")
    r = run_hook("stop.py", {"session_id": "sess-M", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "sess-M").exists()


def test_stop_hook_summarizes_tool_only_turn(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-K"), {"session_id": "sess-K", "status": "active"})
    t = tmp_path / "t.jsonl"
    t.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "clean up"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}) + "\n"
    )
    r = run_hook("stop.py", {"session_id": "sess-K", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-K").iterdir())
    assert json.loads(files[0].read_text())["text"] == "🔧 Ran tools without a text response: Bash"


def test_stop_hook_forwards_ai_title(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-T"), {"session_id": "sess-T", "status": "active"})
    t = tmp_path / "t.jsonl"
    t.write_text(
        json.dumps({"type": "ai-title", "aiTitle": "old title", "sessionId": "sess-T"}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "text", "text": "hi"}]}}) + "\n"
        + json.dumps({"type": "ai-title", "aiTitle": "새 제목", "sessionId": "sess-T"}) + "\n"
    )
    r = run_hook("stop.py", {"session_id": "sess-T", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-T").iterdir())
    assert json.loads(files[0].read_text()) == {
        "role": "assistant", "text": "hi", "ai_title": "새 제목",
    }


def test_user_prompt_submit_mirrors_when_pending(hook_env):
    bc.write_json_atomic(bc.REGISTER / "sess-C.json", {"session_id": "sess-C"})
    r = run_hook("user_prompt_submit.py", {"session_id": "sess-C", "prompt": "  do it  "}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-C").iterdir())
    assert json.loads(files[0].read_text()) == {"role": "user", "text": "do it"}
    assert (bc.BUSY / "sess-C").exists()  # turn is now in progress


def test_user_prompt_submit_skips_peer_injection_echo(hook_env):
    # A Telegram message the broker injected comes back through this hook wrapped
    # in Claude Code's peer preamble. It must not be re-mirrored (double post),
    # but it still starts a turn.
    bc.write_json_atomic(bc.session_file("sess-P"), {"session_id": "sess-P", "status": "active"})
    wrapped = (
        "Another Claude session sent a message:\n지금 잘 돌고있나\n\n"
        "This came from another Claude session — not typed by your user..."
    )
    r = run_hook("user_prompt_submit.py", {"session_id": "sess-P", "prompt": wrapped}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "sess-P").exists()
    assert (bc.BUSY / "sess-P").exists()


def test_user_prompt_submit_skips_echo_via_pending_marker_even_without_peer_prefix(hook_env):
    # The pending marker (what claude_inject.py now writes before delivering)
    # must be the authoritative check on its own — not just a backstop behind
    # the preamble-prefix heuristic, which is what actually missed a real
    # peer message in production. Prove it by using a "wrapper" that doesn't
    # match _PEER_PREFIXES at all.
    bc.write_json_atomic(bc.session_file("sess-Q"), {"session_id": "sess-Q", "status": "active"})
    bc.PENDING.mkdir(parents=True, exist_ok=True)
    (bc.PENDING / "sess-Q.json").write_text(
        json.dumps([{"text": "지금 잘 돌고있나", "ts": time.time()}])
    )
    wrapped = "Some future Claude Code wrapper format:\n지금 잘 돌고있나\n(disclaimer text)"

    r = run_hook("user_prompt_submit.py", {"session_id": "sess-Q", "prompt": wrapped}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "sess-Q").exists()
    assert (bc.BUSY / "sess-Q").exists()
    assert json.loads((bc.PENDING / "sess-Q.json").read_text()) == []  # consumed


def test_user_prompt_submit_skips_system_prompt_source(hook_env):
    bc.write_json_atomic(bc.session_file("sess-S"), {"session_id": "sess-S", "status": "active"})
    r = run_hook(
        "user_prompt_submit.py",
        {"session_id": "sess-S", "prompt": "wake up", "promptSource": "system"},
        hook_env,
    )
    assert r.returncode == 0
    assert not (bc.OUTBOX / "sess-S").exists()


def test_stop_hook_clears_busy_marker(hook_env, tmp_path):
    bc.write_json_atomic(bc.session_file("sess-BZ"), {"session_id": "sess-BZ", "status": "active"})
    bc.mark_busy("sess-BZ")
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}
    ) + "\n")
    r = run_hook("stop.py", {"session_id": "sess-BZ", "transcript_path": str(t)}, hook_env)
    assert r.returncode == 0
    assert not (bc.BUSY / "sess-BZ").exists()


def test_session_end_clears_busy_marker(hook_env):
    bc.mark_busy("sess-BE")
    r = run_hook("session_end.py", {"session_id": "sess-BE", "reason": "exit"}, hook_env)
    assert r.returncode == 0
    assert not (bc.BUSY / "sess-BE").exists()


def test_notification_hook_mirrors_attention_request(hook_env):
    bc.write_json_atomic(bc.session_file("sess-N"), {"session_id": "sess-N", "status": "active"})
    r = run_hook(
        "notification.py",
        {"session_id": "sess-N", "message": "Claude needs your permission to use Bash"},
        hook_env,
    )
    assert r.returncode == 0
    files = list((bc.OUTBOX / "sess-N").iterdir())
    assert json.loads(files[0].read_text()) == {
        "role": "event", "text": "Claude needs your permission to use Bash",
    }


def test_notification_hook_skips_idle_nudge(hook_env):
    bc.write_json_atomic(bc.session_file("sess-N2"), {"session_id": "sess-N2", "status": "active"})
    r = run_hook(
        "notification.py",
        {"session_id": "sess-N2", "message": "Claude is waiting for your input"},
        hook_env,
    )
    assert r.returncode == 0
    assert not (bc.OUTBOX / "sess-N2").exists()


def test_notification_hook_silent_for_unregistered_session(hook_env):
    r = run_hook("notification.py", {"session_id": "ghostN", "message": "hi"}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "ghostN").exists()


def test_session_end_writes_end_file(hook_env):
    r = run_hook("session_end.py", {"session_id": "sess-D", "reason": "exit"}, hook_env)
    assert r.returncode == 0
    end = json.loads((bc.END / "sess-D.json").read_text())
    assert end["session_id"] == "sess-D"
    assert end["reason"] == "exit"


# --- Codex CLI hooks ---------------------------------------------------------
# Same file-queue contract as the Claude hooks above, but Codex's own payload
# shapes: SessionStart has no socket/token to capture, Stop hands back the
# reply text directly (no transcript to reopen), and a queued message is
# indistinguishable from a typed one at UserPromptSubmit (no peer wrapper) —
# so the echo check goes through the pending-injection file instead.


def test_codex_session_start_writes_register_with_kind(hook_env):
    r = run_hook(
        "codex_session_start.py",
        {"session_id": "cx-A", "cwd": "/home/x/proj", "source": "startup"},
        hook_env,
    )
    assert r.returncode == 0
    reg = json.loads((bc.REGISTER / "cx-A.json").read_text())
    assert reg["kind"] == "codex"
    assert reg["base"] == "proj"
    assert "messaging_socket" not in reg


def test_codex_stop_mirrors_last_assistant_message(hook_env):
    bc.write_json_atomic(bc.session_file("cx-B"), {"session_id": "cx-B", "status": "active"})
    r = run_hook(
        "codex_stop.py",
        {"session_id": "cx-B", "last_assistant_message": "the answer"},
        hook_env,
    )
    assert r.returncode == 0
    files = list((bc.OUTBOX / "cx-B").iterdir())
    assert json.loads(files[0].read_text()) == {"role": "assistant", "text": "the answer"}


def test_codex_stop_skips_outbox_when_no_final_message(hook_env):
    bc.write_json_atomic(bc.session_file("cx-E"), {"session_id": "cx-E", "status": "active"})
    r = run_hook("codex_stop.py", {"session_id": "cx-E"}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "cx-E").exists()


def test_codex_stop_silent_for_unregistered_session(hook_env):
    r = run_hook(
        "codex_stop.py", {"session_id": "cx-ghost", "last_assistant_message": "hi"}, hook_env
    )
    assert r.returncode == 0
    assert not (bc.OUTBOX / "cx-ghost").exists()


def test_codex_stop_clears_busy_marker(hook_env):
    bc.write_json_atomic(bc.session_file("cx-BZ"), {"session_id": "cx-BZ", "status": "active"})
    bc.mark_busy("cx-BZ")
    r = run_hook(
        "codex_stop.py", {"session_id": "cx-BZ", "last_assistant_message": "ok"}, hook_env
    )
    assert r.returncode == 0
    assert not (bc.BUSY / "cx-BZ").exists()


def test_codex_user_prompt_submit_mirrors_when_pending(hook_env):
    bc.write_json_atomic(bc.REGISTER / "cx-C.json", {"session_id": "cx-C", "kind": "codex"})
    r = run_hook(
        "codex_user_prompt_submit.py", {"session_id": "cx-C", "prompt": "  do it  "}, hook_env
    )
    assert r.returncode == 0
    files = list((bc.OUTBOX / "cx-C").iterdir())
    assert json.loads(files[0].read_text()) == {"role": "user", "text": "do it"}
    assert (bc.BUSY / "cx-C").exists()  # turn is now in progress


def test_codex_structured_handoff_header_is_mirrored_as_assistant(hook_env):
    sid = "cx-handoff"
    prompt = (
        "저장소 /home/breadum/Work/backnote. 역할은 docs/team/roles/po.md의 backnote-po. "
        "task 008: docs/team/tasks/queue/008-sdd-po-workflow/task.md.\n\n"
        "현재 별도 PO 검수가 반려됐다. 지적사항을 모두 반영하라."
    )
    bc.write_json_atomic(bc.REGISTER / f"{sid}.json", {"session_id": sid})
    r = run_hook("codex_user_prompt_submit.py", {"session_id": sid, "prompt": prompt}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / sid).iterdir())
    assert json.loads(files[0].read_text()) == {"role": "assistant", "text": prompt}


def test_codex_role_wording_alone_remains_user(hook_env):
    sid = "cx-wording"
    prompt = "당신은 backnote-po agent입니다. 지적사항을 반영하라."
    bc.write_json_atomic(bc.REGISTER / f"{sid}.json", {"session_id": sid})
    r = run_hook("codex_user_prompt_submit.py", {"session_id": sid, "prompt": prompt}, hook_env)
    assert r.returncode == 0
    files = list((bc.OUTBOX / sid).iterdir())
    assert json.loads(files[0].read_text()) == {"role": "user", "text": prompt}


def test_codex_user_prompt_submit_skips_pending_injection_echo(hook_env):
    # The broker queued this exact text via `codex queue` just before it landed
    # here — codex_inject.py leaves a marker for it. Must not double-post.
    bc.write_json_atomic(
        bc.session_file("cx-D"), {"session_id": "cx-D", "kind": "codex", "status": "active"}
    )
    bc.PENDING.mkdir(parents=True, exist_ok=True)
    (bc.PENDING / "cx-D.json").write_text(
        json.dumps([{"text": "지금 잘 돌고있나", "ts": time.time()}])
    )
    r = run_hook(
        "codex_user_prompt_submit.py", {"session_id": "cx-D", "prompt": "지금 잘 돌고있나"}, hook_env
    )
    assert r.returncode == 0
    assert not (bc.OUTBOX / "cx-D").exists()
    assert (bc.BUSY / "cx-D").exists()  # still starts a turn
    assert json.loads((bc.PENDING / "cx-D.json").read_text()) == []  # consumed


def test_codex_session_end_writes_end_file(hook_env):
    r = run_hook("codex_session_end.py", {"session_id": "cx-E", "reason": "exit"}, hook_env)
    assert r.returncode == 0
    end = json.loads((bc.END / "cx-E.json").read_text())
    assert end["session_id"] == "cx-E"
    assert end["reason"] == "exit"


def test_codex_permission_request_mirrors_message(hook_env):
    bc.write_json_atomic(
        bc.session_file("cx-F"), {"session_id": "cx-F", "kind": "codex", "status": "active"}
    )
    r = run_hook(
        "codex_permission_request.py",
        {"session_id": "cx-F", "message": "approve running `rm -rf build`?"},
        hook_env,
    )
    assert r.returncode == 0
    files = list((bc.OUTBOX / "cx-F").iterdir())
    assert json.loads(files[0].read_text()) == {
        "role": "event", "text": "approve running `rm -rf build`?",
    }


def test_codex_permission_request_silent_when_no_text_field(hook_env):
    bc.write_json_atomic(
        bc.session_file("cx-G"), {"session_id": "cx-G", "kind": "codex", "status": "active"}
    )
    r = run_hook("codex_permission_request.py", {"session_id": "cx-G"}, hook_env)
    assert r.returncode == 0
    assert not (bc.OUTBOX / "cx-G").exists()


def test_codex_permission_request_silent_for_unregistered_session(hook_env):
    r = run_hook(
        "codex_permission_request.py", {"session_id": "cx-ghost", "message": "hi"}, hook_env
    )
    assert r.returncode == 0
    assert not (bc.OUTBOX / "cx-ghost").exists()
