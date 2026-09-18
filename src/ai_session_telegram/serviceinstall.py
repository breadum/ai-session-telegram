"""Install (and uninstall) the broker as a native background service.

The Linux path is still the systemd --user unit rendered by
service/install.sh; this module covers the platforms that don't have
systemd, driven by `bridge install-service` / `bridge uninstall-service`:

  * macOS: a launchd user agent, plist built directly with plistlib (no
    template file to render, unlike systemd's).
  * Windows: a Task Scheduler task with a logon trigger, registered via
    schtasks.exe.

install()/uninstall() dispatch on platform.system() and raise on anything
else (Linux keeps using service/install.sh, which is battle-tested and not
worth re-implementing here).
"""

from __future__ import annotations

import os
import platform
import plistlib
import subprocess
from pathlib import Path

from . import paths

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LABEL = "ai-session-telegram"


def _repo_dir() -> Path:
    # src/ai_session_telegram/serviceinstall.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def _bridge_bin() -> Path:
    if platform.system() == "Windows":
        return _repo_dir() / ".venv" / "Scripts" / "bridge.exe"
    return _repo_dir() / ".venv" / "bin" / "bridge"


def install() -> None:
    system = platform.system()
    if system == "Darwin":
        _install_macos()
    elif system == "Windows":
        _install_windows()
    else:
        raise SystemExit(
            f"service install/uninstall isn't implemented for {system} "
            "— on Linux use ./service/install.sh"
        )


def uninstall() -> None:
    system = platform.system()
    if system == "Darwin":
        _uninstall_macos()
    elif system == "Windows":
        _uninstall_windows()
    else:
        raise SystemExit(
            f"service install/uninstall isn't implemented for {system} "
            "— on Linux use ./service/uninstall.sh"
        )


# --------------------------------------------------------------------------
# macOS (launchd)
# --------------------------------------------------------------------------


def _plist_path() -> Path:
    return LAUNCH_AGENTS_DIR / f"{LABEL}.plist"


def _plist_dict() -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [str(_bridge_bin()), "run"],
        "WorkingDirectory": str(_repo_dir()),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(paths.LOG_FILE),
        "StandardErrorPath": str(paths.LOG_FILE),
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _domain_target() -> str:
    # getattr'd rather than os.getuid() directly: that attribute doesn't
    # exist in Windows' os module at all, and this only needs to be safe to
    # *call* there for tests that simulate the macOS path on any host OS —
    # real macOS always has getuid.
    getuid = getattr(os, "getuid", lambda: 0)
    return f"gui/{getuid()}"


def _install_macos() -> None:
    bridge_bin = _bridge_bin()
    if not bridge_bin.is_file():
        raise SystemExit(f"!! {bridge_bin} not found — run 'uv sync' in {_repo_dir()} first")

    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_path = _plist_path()
    with plist_path.open("wb") as f:
        plistlib.dump(_plist_dict(), f)
    print(f"wrote {plist_path}")

    domain = _domain_target()
    _launchctl("bootout", f"{domain}/{LABEL}")  # ignore failure: fine if it wasn't loaded
    result = _launchctl("bootstrap", domain, str(plist_path))
    if result.returncode != 0:
        raise SystemExit(f"launchctl bootstrap failed: {result.stderr.strip()}")
    _launchctl("enable", f"{domain}/{LABEL}")

    print(f"loaded as {domain}/{LABEL}")
    print(f"restart:  launchctl kickstart -k {domain}/{LABEL}")
    print("logs:     uv run bridge logs -f")


def _uninstall_macos() -> None:
    domain = _domain_target()
    _launchctl("bootout", f"{domain}/{LABEL}")  # ignore failure: fine if it wasn't loaded
    plist_path = _plist_path()
    if plist_path.exists():
        plist_path.unlink()
        print(f"removed {plist_path}")
    else:
        print(f"no {plist_path}")


# --------------------------------------------------------------------------
# Windows (Task Scheduler)
# --------------------------------------------------------------------------

TASK_NAME = "ai-session-telegram"


def _schtasks(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, check=False)


def _install_windows() -> None:
    bridge_bin = _bridge_bin()
    if not bridge_bin.is_file():
        raise SystemExit(f"!! {bridge_bin} not found — run 'uv sync' in {_repo_dir()} first")

    # `bridge run` always attaches a FileHandler to paths.LOG_FILE regardless of
    # how it's launched (see broker._setup_logging), so `bridge logs -f` works
    # the same way here as under systemd/launchd — no output redirection needed.
    tr_value = f'"{bridge_bin}" run'
    result = _schtasks(
        "/Create", "/TN", TASK_NAME, "/TR", tr_value,
        "/SC", "ONLOGON", "/RL", "LIMITED", "/F",
    )
    if result.returncode != 0:
        raise SystemExit(f"schtasks /Create failed: {result.stderr.strip()}")
    print(f"registered scheduled task {TASK_NAME!r} (runs at logon)")

    # /SC ONLOGON only fires at the *next* logon; run it once now too, so
    # `install-service` starts the broker immediately like launchd/systemd do.
    result = _schtasks("/Run", "/TN", TASK_NAME)
    if result.returncode != 0:
        print(f"warning: could not start it immediately: {result.stderr.strip()}")

    print(f"restart:  schtasks /End /TN {TASK_NAME} && schtasks /Run /TN {TASK_NAME}")
    print("logs:     uv run bridge logs -f")


def _uninstall_windows() -> None:
    result = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if result.returncode == 0:
        print(f"removed scheduled task {TASK_NAME!r}")
    else:
        print(f"no scheduled task {TASK_NAME!r} ({result.stderr.strip()})")
