"""Editing a past message or regenerating the last response (PLAN.md's
"Edit / regenerate de message" entry) are the same server-side operation:
POST /chat's edit_turn_index drops a turn and everything after it
(server.truncate_before_turn) before appending `message` as that turn's
new content - a fresh edited text for "edit", the same text unchanged for
"regenerate". No network call needed: run_chat_stream is monkeypatched to
capture the messages it was handed instead of actually calling a model."""

from typing import cast

import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletionMessageParam

import server
from triton.storage import sessions


@pytest.fixture(autouse=True)
def _isolated_sessions_dir(tmp_path, monkeypatch):
    # server.py does `from triton.storage.sessions import SESSIONS_DIR`, its
    # own separate name bound at import time - patching sessions.SESSIONS_DIR
    # alone leaves server.py's own copy pointed at the real sessions/
    # directory (see test_compact_command.py for the same footgun).
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)


@pytest.fixture
def client():
    return TestClient(server.app)


def _user(text: str) -> ChatCompletionMessageParam:
    return cast(ChatCompletionMessageParam, {"role": "user", "content": text})


def _assistant(text: str) -> ChatCompletionMessageParam:
    return cast(ChatCompletionMessageParam, {"role": "assistant", "content": text})


def _system(text: str) -> ChatCompletionMessageParam:
    return cast(ChatCompletionMessageParam, {"role": "system", "content": text})


def _session(messages: list[ChatCompletionMessageParam]) -> str:
    path = sessions.new_session_path()
    sessions.save_session(path, messages)
    return path.stem


# --- truncate_before_turn (the underlying helper) ---


def test_truncate_before_turn_drops_this_turn_and_everything_after():
    messages = [
        _system("s"),
        _user("turn 1"),
        _assistant("reply 1"),
        _user("turn 2"),
        _assistant("reply 2"),
    ]

    assert server.truncate_before_turn(messages, 2) == [
        _system("s"),
        _user("turn 1"),
        _assistant("reply 1"),
    ]
    assert server.truncate_before_turn(messages, 1) == [_system("s")]


@pytest.mark.parametrize("turn_index", [0, -1, 3])
def test_truncate_before_turn_rejects_an_out_of_range_turn_index(turn_index):
    messages = [_system("s"), _user("turn 1"), _assistant("reply 1"), _user("turn 2")]

    with pytest.raises(server.HTTPException) as exc_info:
        server.truncate_before_turn(messages, turn_index)
    assert exc_info.value.status_code == 400


# --- POST /chat's edit_turn_index ---


def test_edit_turn_index_truncates_before_resending(client, monkeypatch):
    captured: list[list[ChatCompletionMessageParam]] = []

    def fake_run_chat_stream(session_path, messages, first_message=None):
        captured.append(messages)
        yield "event: session\ndata: {}\n\n"

    monkeypatch.setattr(server, "run_chat_stream", fake_run_chat_stream)

    session_id = _session(
        [
            _system("s"),
            _user("turn 1"),
            _assistant("reply 1"),
            _user("turn 2 (typo)"),
            _assistant("reply 2"),
        ]
    )

    r = client.post(
        "/chat",
        json={"session_id": session_id, "message": "turn 2 (fixed)", "edit_turn_index": 2},
    )

    assert r.status_code == 200
    assert len(captured) == 1
    assert captured[0] == [
        _system("s"),
        _user("turn 1"),
        _assistant("reply 1"),
        _user("turn 2 (fixed)"),
    ]


def test_regenerate_resends_the_same_turn_unchanged(client, monkeypatch):
    """Regenerate is just an edit that resends the exact same text - this
    only pins down that POST /chat doesn't need a different code path for
    it (see App.tsx's regenerateResponse, which calls sendMessage the same
    way edit does)."""
    captured: list[list[ChatCompletionMessageParam]] = []

    def fake_run_chat_stream(session_path, messages, first_message=None):
        captured.append(messages)
        yield "event: session\ndata: {}\n\n"

    monkeypatch.setattr(server, "run_chat_stream", fake_run_chat_stream)

    session_id = _session([_system("s"), _user("turn 1"), _assistant("reply 1")])

    r = client.post(
        "/chat",
        json={"session_id": session_id, "message": "turn 1", "edit_turn_index": 1},
    )

    assert r.status_code == 200
    assert captured[0] == [_system("s"), _user("turn 1")]


def test_edit_turn_index_out_of_range_returns_400(client, monkeypatch):
    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("run_chat_stream must not run past an invalid edit_turn_index")

    monkeypatch.setattr(server, "run_chat_stream", _fail_if_called)

    session_id = _session([_system("s"), _user("turn 1"), _assistant("reply 1")])

    r = client.post(
        "/chat",
        json={"session_id": session_id, "message": "does not matter", "edit_turn_index": 5},
    )

    assert r.status_code == 400


def test_omitted_edit_turn_index_behaves_like_a_normal_new_message(client, monkeypatch):
    captured: list[list[ChatCompletionMessageParam]] = []

    def fake_run_chat_stream(session_path, messages, first_message=None):
        captured.append(messages)
        yield "event: session\ndata: {}\n\n"

    monkeypatch.setattr(server, "run_chat_stream", fake_run_chat_stream)

    session_id = _session([_system("s"), _user("turn 1"), _assistant("reply 1")])

    r = client.post("/chat", json={"session_id": session_id, "message": "turn 2"})

    assert r.status_code == 200
    assert captured[0] == [_system("s"), _user("turn 1"), _assistant("reply 1"), _user("turn 2")]
