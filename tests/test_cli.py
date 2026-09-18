"""CLI argument dispatch and the read-only status/prune subcommands."""

from __future__ import annotations

import json

import fakes
import pytest

from ai_session_telegram import cli, paths
from ai_session_telegram.config import Config


class _CtxFakeTelegram(fakes.FakeTelegram):
    """cli.py uses `Telegram(...)` as a context manager; FakeTelegram doesn't need to."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def _write_session(sid: str, **fields) -> None:
    row = {
        "session_id": sid,
        "label": fields.pop("label", sid),
        "status": fields.pop("status", "active"),
        "cwd": fields.pop("cwd", "/tmp/proj"),
        **fields,
    }
    paths.session_file(sid).write_text(json.dumps(row))


@pytest.mark.parametrize(
    "argv,expected_agent",
    [(["install-hooks"], "claude"), (["install-hooks", "--agent", "codex"], "codex"),
     (["install-hooks", "--agent", "all"], "all")],
)
def test_install_hooks_dispatch(monkeypatch, argv, expected_agent):
    seen = {}
    monkeypatch.setattr(cli, "cmd_install_hooks", lambda agent: seen.setdefault("agent", agent))
    cli.main(argv)
    assert seen["agent"] == expected_agent


def test_uninstall_hooks_default_agent_is_claude(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "cmd_uninstall_hooks", lambda agent: seen.setdefault("agent", agent))
    cli.main(["uninstall-hooks"])
    assert seen["agent"] == "claude"


def test_install_hooks_rejects_unknown_agent():
    with pytest.raises(SystemExit):
        cli.main(["install-hooks", "--agent", "bogus"])


def test_status_lists_sessions(bridge_home, capsys):
    _write_session("sid-1", label="myproj-sid1", status="active", cwd="/home/x/myproj")
    cli.cmd_status()
    out = capsys.readouterr().out
    assert "myproj-sid1" in out
    assert "/home/x/myproj" in out
    assert "sessions (1):" in out


def test_status_shows_busy_and_codex_kind(bridge_home, capsys):
    _write_session("sid-2", label="codex-sess", kind="codex")
    paths.busy_file("sid-2").touch()
    cli.cmd_status()
    out = capsys.readouterr().out
    assert "busy" in out
    assert "codex" in out


def test_prune_without_all_only_targets_ended(bridge_home, monkeypatch, capsys):
    monkeypatch.setattr(Config, "load", staticmethod(lambda: Config(bot_token="t", chat_id=-1)))
    _write_session("active-sid", status="active")
    _write_session("ended-sid", status="ended", thread_id=7)

    fake = _CtxFakeTelegram()
    monkeypatch.setattr(cli, "Telegram", lambda *a, **k: fake)

    cli.cmd_prune(all_sessions=False, assume_yes=True)

    assert (-1, 7) in fake.deleted
    assert paths.session_file("ended-sid").exists() is False
    assert paths.session_file("active-sid").exists() is True


def test_prune_reports_nothing_to_do(bridge_home, monkeypatch, capsys):
    monkeypatch.setattr(Config, "load", staticmethod(lambda: Config(bot_token="t", chat_id=-1)))
    _write_session("active-sid", status="active")

    cli.cmd_prune(all_sessions=False, assume_yes=True)

    assert "nothing to prune" in capsys.readouterr().out
    assert paths.session_file("active-sid").exists()


# --------------------------------------------------------------------------
# Windows process-management branches
# --------------------------------------------------------------------------


def test_logs_prints_last_80_lines_without_external_tail(bridge_home, capsys):
    paths.LOG_FILE.write_text("".join(f"line {i}\n" for i in range(100)))
    cli.cmd_logs(follow=False)
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 80
    assert out[0] == "line 20"
    assert out[-1] == "line 99"


def test_logs_missing_file_is_a_noop(bridge_home, capsys):
    cli.cmd_logs(follow=False)
    assert "no log yet" in capsys.readouterr().out


def test_alive_windows_checks_tasklist_output(monkeypatch):
    monkeypatch.setattr(cli.os, "name", "nt")

    class _Result:
        stdout = "python.exe   4242 Console  1   12,345 K"

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _Result())
    assert cli._alive(4242) is True

    class _EmptyResult:
        stdout = "INFO: No tasks matching the given criteria.\n"

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: _EmptyResult())
    assert cli._alive(4242) is False


def test_windows_start_uses_creationflags_not_start_new_session(monkeypatch, bridge_home):
    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(Config, "load", staticmethod(lambda: Config(bot_token="t", chat_id=-1)))
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    captured = {}

    class _FakeProc:
        pid = 999

        def poll(self):
            return None

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    cli.cmd_start()

    assert "creationflags" in captured
    assert "start_new_session" not in captured


def test_windows_stop_touches_flag_and_waits_for_alive_to_clear(monkeypatch, bridge_home):
    monkeypatch.setattr(cli.os, "name", "nt")
    paths.PID_FILE.write_text("4242")
    monkeypatch.setattr(cli, "_alive", lambda pid: not paths.STOP_FLAG.exists())

    assert cli.cmd_stop(quiet=True) is True
    assert not paths.STOP_FLAG.exists()


def test_windows_stop_force_kills_via_sigterm_after_timeout(monkeypatch, bridge_home):
    monkeypatch.setattr(cli.os, "name", "nt")
    paths.PID_FILE.write_text("4242")
    monkeypatch.setattr(cli, "_alive", lambda pid: True)  # never reports stopped
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    killed = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    cli.cmd_stop(quiet=True)

    assert killed == [(4242, cli.signal.SIGTERM)]
