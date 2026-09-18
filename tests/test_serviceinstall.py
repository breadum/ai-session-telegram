"""macOS launchd / Windows Task Scheduler install-uninstall — exercised
against tmp_path and a stubbed launchctl/schtasks, never the real thing
(this runs on Linux CI where neither exists)."""

from __future__ import annotations

import platform
import plistlib

import pytest

from ai_session_telegram import serviceinstall


def _patch_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(serviceinstall, "LAUNCH_AGENTS_DIR", tmp_path)
    bridge_bin = tmp_path / "bridge"
    bridge_bin.write_text("#!/bin/sh\n")
    bridge_bin.chmod(0o755)
    monkeypatch.setattr(serviceinstall, "_bridge_bin", lambda: bridge_bin)

    calls: list[tuple[str, ...]] = []

    class _Result:
        returncode = 0
        stderr = ""

    def fake_launchctl(*args: str):
        calls.append(args)
        return _Result()

    monkeypatch.setattr(serviceinstall, "_launchctl", fake_launchctl)
    return calls


def test_install_writes_plist_with_expected_fields(monkeypatch, tmp_path):
    _patch_macos(monkeypatch, tmp_path)
    serviceinstall.install()

    plist_path = tmp_path / "ai-session-telegram.plist"
    assert plist_path.exists()
    data = plistlib.loads(plist_path.read_bytes())
    assert data["Label"] == "ai-session-telegram"
    assert data["ProgramArguments"][-1] == "run"
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["StandardOutPath"] == data["StandardErrorPath"]


def test_install_calls_launchctl_bootout_then_bootstrap_then_enable(monkeypatch, tmp_path):
    calls = _patch_macos(monkeypatch, tmp_path)
    serviceinstall.install()

    verbs = [c[0] for c in calls]
    assert verbs == ["bootout", "bootstrap", "enable"]
    assert calls[1][1] == serviceinstall._domain_target()
    assert calls[1][2] == str(tmp_path / "ai-session-telegram.plist")


def test_install_is_idempotent(monkeypatch, tmp_path):
    _patch_macos(monkeypatch, tmp_path)
    serviceinstall.install()
    first = (tmp_path / "ai-session-telegram.plist").read_bytes()
    serviceinstall.install()
    second = (tmp_path / "ai-session-telegram.plist").read_bytes()
    assert first == second


def test_install_requires_bridge_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(serviceinstall, "LAUNCH_AGENTS_DIR", tmp_path)
    monkeypatch.setattr(serviceinstall, "_bridge_bin", lambda: tmp_path / "missing" / "bridge")
    with pytest.raises(SystemExit):
        serviceinstall.install()


def test_uninstall_removes_plist_and_calls_bootout(monkeypatch, tmp_path):
    calls = _patch_macos(monkeypatch, tmp_path)
    serviceinstall.install()
    calls.clear()

    serviceinstall.uninstall()

    assert not (tmp_path / "ai-session-telegram.plist").exists()
    assert calls == [("bootout", f"{serviceinstall._domain_target()}/ai-session-telegram")]


def test_uninstall_missing_plist_is_a_noop(monkeypatch, tmp_path, capsys):
    _patch_macos(monkeypatch, tmp_path)
    serviceinstall.uninstall()
    assert "no " in capsys.readouterr().out


@pytest.mark.parametrize("fn", [serviceinstall.install, serviceinstall.uninstall])
def test_refuses_unsupported_os(monkeypatch, fn):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit):
        fn()


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------


def _patch_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    bridge_bin = tmp_path / "bridge.exe"
    bridge_bin.write_text("")
    monkeypatch.setattr(serviceinstall, "_bridge_bin", lambda: bridge_bin)

    calls: list[tuple[str, ...]] = []

    class _Result:
        returncode = 0
        stderr = ""

    def fake_schtasks(*args: str):
        calls.append(args)
        return _Result()

    monkeypatch.setattr(serviceinstall, "_schtasks", fake_schtasks)
    return calls, bridge_bin


def test_windows_install_creates_then_runs_task(monkeypatch, tmp_path):
    calls, bridge_bin = _patch_windows(monkeypatch, tmp_path)
    serviceinstall.install()

    verbs = [c[0] for c in calls]
    assert verbs == ["/Create", "/Run"]
    create_args = calls[0]
    assert "/TN" in create_args and serviceinstall.TASK_NAME in create_args
    tr_value = create_args[create_args.index("/TR") + 1]
    assert tr_value == f'"{bridge_bin}" run'
    assert "ONLOGON" in create_args
    assert "LIMITED" in create_args
    assert "/F" in create_args


def test_windows_install_requires_bridge_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(serviceinstall, "_bridge_bin", lambda: tmp_path / "missing" / "bridge.exe")
    with pytest.raises(SystemExit):
        serviceinstall.install()


def test_windows_uninstall_deletes_task(monkeypatch, tmp_path):
    calls, _ = _patch_windows(monkeypatch, tmp_path)
    serviceinstall.uninstall()

    assert calls == [("/Delete", "/TN", serviceinstall.TASK_NAME, "/F")]
