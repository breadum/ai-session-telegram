"""The [uds-messaging] socket client."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import uuid

import pytest

from ai_session_telegram.claude_inject import InjectError, inject_user_message


class _Server:
    """Minimal AF_UNIX server: accept one client, read newline frames."""

    def __init__(self, path: str) -> None:
        self.frames: list[dict] = []
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(path)
        self._sock.listen(1)
        self._t = threading.Thread(target=self._serve, daemon=True)
        self._t.start()

    def _serve(self) -> None:
        conn, _ = self._sock.accept()
        buf = b""
        conn.settimeout(2.0)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self.frames.append(json.loads(line))
        except OSError:
            pass
        finally:
            conn.close()
            self._sock.close()

    def join(self) -> None:
        self._t.join(timeout=3)


@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="AF_UNIX isn't available on this platform's socket module",
)
def test_inject_sends_auth_then_user_frame():
    # A short path directly under the OS temp root, not pytest's tmp_path:
    # AF_UNIX paths are capped at ~104 bytes on macOS, and tmp_path's nested
    # pytest-of-<user>/pytest-<n>/<test-name>/ routinely blows past that.
    path = os.path.join(tempfile.gettempdir(), f"ait-{uuid.uuid4().hex[:8]}.sock")
    try:
        srv = _Server(path)
        inject_user_message(path, "mytoken", "run the tests")
        srv.join()
        assert srv.frames[0] == {"type": "auth", "token": "mytoken"}
        assert srv.frames[1] == {
            "type": "user",
            "message": {"role": "user", "content": "run the tests"},
        }
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_inject_missing_socket_raises(tmp_path):
    with pytest.raises(InjectError):
        inject_user_message(str(tmp_path / "gone.sock"), "t", "hi")


def test_inject_requires_socket_and_token():
    with pytest.raises(InjectError):
        inject_user_message("", "t", "hi")
    with pytest.raises(InjectError):
        inject_user_message("/x", "", "hi")
