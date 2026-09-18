"""Merge/unmerge of bridge hook entries into ~/.claude/settings.json and
~/.codex/hooks.json — exercised against tmp_path stand-ins, never the real files.
"""

from __future__ import annotations

import json
import platform

from ai_session_telegram import hookinstall


def _patch_settings(monkeypatch, tmp_path):
    claude = tmp_path / "claude-settings.json"
    codex = tmp_path / "codex-hooks.json"
    monkeypatch.setattr(hookinstall, "CLAUDE_SETTINGS", claude)
    monkeypatch.setattr(hookinstall, "CODEX_SETTINGS", codex)
    return claude, codex


def test_install_creates_file_and_all_events(monkeypatch, tmp_path):
    claude, _ = _patch_settings(monkeypatch, tmp_path)
    hookinstall.install()

    data = json.loads(claude.read_text())
    assert set(data["hooks"]) == set(hookinstall.CLAUDE_HOOKS)
    for event, (script, _timeout) in hookinstall.CLAUDE_HOOKS.items():
        [group] = data["hooks"][event]
        [entry] = group["hooks"]
        assert script in entry["command"]  # not endswith: Windows quotes the path


def test_install_backs_up_existing_file(monkeypatch, tmp_path):
    claude, _ = _patch_settings(monkeypatch, tmp_path)
    claude.write_text('{"other": true}\n')
    hookinstall.install()

    backups = list(tmp_path.glob("claude-settings.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {"other": True}
    # untouched keys survive
    assert json.loads(claude.read_text())["other"] is True


def test_install_is_idempotent(monkeypatch, tmp_path):
    claude, _ = _patch_settings(monkeypatch, tmp_path)
    hookinstall.install()
    hookinstall.install()

    data = json.loads(claude.read_text())
    for event in hookinstall.CLAUDE_HOOKS:
        assert len(data["hooks"][event]) == 1


def test_install_preserves_foreign_hook_entries(monkeypatch, tmp_path):
    claude, _ = _patch_settings(monkeypatch, tmp_path)
    claude.write_text(json.dumps({
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}
    }))
    hookinstall.install()

    groups = json.loads(claude.read_text())["hooks"]["SessionStart"]
    commands = [h["command"] for g in groups for h in g["hooks"]]
    assert "echo mine" in commands
    assert any("session_start.py" in c for c in commands)


def test_uninstall_removes_only_our_entries(monkeypatch, tmp_path):
    claude, _ = _patch_settings(monkeypatch, tmp_path)
    claude.write_text(json.dumps({
        "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}
    }))
    hookinstall.install()
    hookinstall.uninstall()

    data = json.loads(claude.read_text())
    groups = data["hooks"]["SessionStart"]
    commands = [h["command"] for g in groups for h in g["hooks"]]
    assert commands == ["echo mine"]


def test_uninstall_missing_file_is_a_noop(monkeypatch, tmp_path, capsys):
    claude, _ = _patch_settings(monkeypatch, tmp_path)
    hookinstall.uninstall()
    assert not claude.exists()
    assert "no " in capsys.readouterr().out


def test_codex_install_uses_codex_hooks_and_file(monkeypatch, tmp_path):
    _, codex = _patch_settings(monkeypatch, tmp_path)
    hookinstall.install_codex()

    data = json.loads(codex.read_text())
    assert set(data["hooks"]) == set(hookinstall.CODEX_HOOKS)
    for event, (script, _timeout) in hookinstall.CODEX_HOOKS.items():
        [group] = data["hooks"][event]
        [entry] = group["hooks"]
        assert script in entry["command"]  # not endswith: Windows quotes the path

    hookinstall.uninstall_codex()
    assert json.loads(codex.read_text()).get("hooks", {}) == {}


def test_command_for_uses_python3_by_default(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    cmd = hookinstall._command_for("stop.py")
    assert cmd.startswith("python3 ")
    assert cmd.endswith("stop.py")


def test_command_for_uses_py_launcher_on_windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    cmd = hookinstall._command_for("stop.py")
    assert cmd.startswith('py -3 "')
    assert cmd.endswith('stop.py"')
