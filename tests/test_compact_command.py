"""POST /sessions/{id}/compact ("/compact"): forces compress_history_if_needed
to summarize the oldest turns right now, instead of waiting for the
automatic trigger in run_chat_stream (context already over
MAX_CONTEXT_CHARS - see chat_loop.py). No network call needed - call_chat
is monkeypatched so the underlying summarize() never actually hits the
model."""

from typing import cast

import pytest
from fastapi.testclient import TestClient
from openai.types.chat import ChatCompletionMessageParam

import server
from triton.llm import chat_loop
from triton.llm.api import ChatResult
from triton.storage import sessions


@pytest.fixture(autouse=True)
def _isolated_sessions_dir(tmp_path, monkeypatch):
    # server.py does `from triton.storage.sessions import SESSIONS_DIR`, its
    # own separate name bound at import time - patching sessions.SESSIONS_DIR
    # alone leaves server.py's compact_session pointed at the real
    # sessions/ directory, so both need patching.
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


def test_compact_404_for_unknown_session(client):
    r = client.post("/sessions/does-not-exist/compact")
    assert r.status_code == 404


def test_compact_reports_nothing_to_do_for_a_short_conversation(client):
    session_id = _session([_system("s"), _user("hi"), _assistant("ok")])

    r = client.post(f"/sessions/{session_id}/compact")

    assert r.status_code == 200
    assert r.json()["result"] == "nothing to compact yet: not enough exchanges in this conversation"
    # untouched: nothing was summarized
    assert sessions.load_session(sessions.session_path(session_id)) == [
        _system("s"),
        _user("hi"),
        _assistant("ok"),
    ]


def test_compact_summarizes_and_saves_even_under_the_size_threshold(client, monkeypatch):
    """The whole point of /compact: it must work well under
    MAX_CONTEXT_CHARS, unlike the automatic trigger."""
    monkeypatch.setattr(chat_loop, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(chat_loop, "estimate_cost", lambda *_args: None)
    monkeypatch.setattr(
        chat_loop,
        "call_chat",
        lambda *_args, **_kwargs: ChatResult(
            content="summary of the old turns",
            tool_calls=[],
            model="test-model",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
    )

    messages = [
        _system("system prompt"),
        _user("turn 1"),
        _assistant("reply 1"),
        _user("turn 2"),
        _assistant("reply 2"),
        _user("turn 3"),
        _assistant("reply 3"),
        _user("turn 4"),
        _assistant("reply 4"),
    ]
    assert chat_loop.estimate_size(messages) <= chat_loop.MAX_CONTEXT_CHARS
    session_id = _session(messages)

    r = client.post(f"/sessions/{session_id}/compact")

    assert r.status_code == 200
    assert r.json()["result"] == "history compressed: 2 messages summarized into 1"

    saved = sessions.load_session(sessions.session_path(session_id))
    assert saved[0] == messages[0]
    assert saved[1]["role"] == "system"
    assert "summary of the old turns" in cast(str, saved[1]["content"])
    assert saved[2:] == messages[3:]
