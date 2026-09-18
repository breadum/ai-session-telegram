"""Telegram Bot API client: request shape and the markup-retry fallback."""

from __future__ import annotations

import json

import httpx
import pytest

from ai_session_telegram.telegram import Telegram, TelegramError


def _client(handler) -> Telegram:
    tg = Telegram("tok")
    tg._client = httpx.Client(transport=httpx.MockTransport(handler))
    return tg


def test_get_me_hits_expected_url():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "b"}})

    tg = _client(handler)
    result = tg.get_me()

    assert seen["url"] == "https://api.telegram.org/bottok/getMe"
    assert result == {"id": 1, "username": "b"}


def test_get_updates_sends_offset_and_allowed_updates():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": []})

    tg = _client(handler)
    tg.get_updates(offset=42, timeout=5)

    assert seen["body"] == {
        "offset": 42,
        "timeout": 5,
        "allowed_updates": ["message"],
    }


def test_create_forum_topic_truncates_long_names_and_returns_thread_id():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert len(body["name"]) <= 128
        return httpx.Response(200, json={"ok": True, "result": {"message_thread_id": 99}})

    tg = _client(handler)
    assert tg.create_forum_topic(-1, "x" * 500) == 99


def test_error_response_raises_telegram_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error_code": 400, "description": "bad"})

    tg = _client(handler)
    with pytest.raises(TelegramError, match="bad"):
        tg.get_me()


def test_send_message_retries_stripped_on_markup_error():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body.get("parse_mode") == "HTML":
            return httpx.Response(
                200, json={"ok": False, "error_code": 400, "description": "can't parse entities"}
            )
        return httpx.Response(200, json={"ok": True, "result": {}})

    tg = _client(handler)
    tg.send_message(-1, "<b>hi</b>", parse_mode="HTML")

    assert len(calls) == 2
    assert calls[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in calls[1]
    assert calls[1]["text"] == "hi"


def test_send_message_reraises_non_markup_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"ok": False, "error_code": 403, "description": "bot was blocked"}
        )

    tg = _client(handler)
    with pytest.raises(TelegramError, match="blocked"):
        tg.send_message(-1, "hi", parse_mode="HTML")


def test_delete_forum_topic_returns_false_on_error_instead_of_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error_code": 400, "description": "gone"})

    tg = _client(handler)
    assert tg.delete_forum_topic(-1, 5) is False
