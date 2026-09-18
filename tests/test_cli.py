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
