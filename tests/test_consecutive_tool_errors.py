"""server.py's MAX_CONSECUTIVE_TOOL_ERRORS: a tool call failing over and
over (the model repeating the same broken call, or hallucinating a tool
name that doesn't exist) is a much stronger "genuinely stuck" signal than
iteration count alone - the real replacement for MAX_ITERATIONS having
been raised from 25 to 100 (chat_loop.py) specifically so a long but
otherwise-successful task doesn't need a manual "Continue" click partway
through. No real model call: timed_stream_chat is monkeypatched to a fake
tool-call sequence."""

import json

import pytest
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageToolCallUnion,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

import server
from triton.llm.api import ChatResult
from triton.storage import sessions, settings


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    # server.py does `from triton.storage.sessions import SESSIONS_DIR`, its
    # own separate name bound at import time - both need patching (see
    # test_compact_command.py for the same footgun).
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")


def _tool_call_result(tool_name: str, call_id: str = "call_1", **arguments: object) -> ChatResult:
    tool_calls: list[ChatCompletionMessageToolCallUnion] = [
        ChatCompletionMessageFunctionToolCall(
            id=call_id,
            type="function",
            function=Function(name=tool_name, arguments=json.dumps(arguments)),
        )
    ]
    return ChatResult(
        content=None,
        tool_calls=tool_calls,
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="tool_calls",
    )


def _session_path(tmp_path):
    path = tmp_path / "sessions" / "test.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_stops_after_too_many_consecutive_tool_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    calls: list[int] = []

    def fake_timed_stream_chat(*_args, **_kwargs):
        calls.append(1)
        # a tool name that isn't in TOOLS_REGISTRY at all - a real,
        # deterministic failure with no filesystem/network dependency
        yield _tool_call_result("this_tool_does_not_exist")

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    events = list(
        server.run_chat_stream(_session_path(tmp_path), [{"role": "user", "content": "hi"}])
    )

    # stopped exactly at the threshold, nowhere near MAX_ITERATIONS
    assert len(calls) == server.MAX_CONSECUTIVE_TOOL_ERRORS
    error_events = [e for e in events if "event: error" in e]
    assert len(error_events) == 1
    assert f"{server.MAX_CONSECUTIVE_TOOL_ERRORS}" in error_events[0]
    assert "échoué d'affilée" in error_events[0]


def test_a_successful_tool_call_resets_the_streak(tmp_path, monkeypatch):
    """A success between failures must not let them accumulate towards
    the threshold - only a genuine unbroken streak trips it."""
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    call_count = 0

    def fake_timed_stream_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        # MAX_CONSECUTIVE_TOOL_ERRORS - 1 failures, then one success,
        # repeated for as long as the loop keeps running
        cycle_position = (call_count - 1) % server.MAX_CONSECUTIVE_TOOL_ERRORS
        if cycle_position == server.MAX_CONSECUTIVE_TOOL_ERRORS - 1:
            yield _tool_call_result("todo_write", todos=[])
        else:
            yield _tool_call_result("this_tool_does_not_exist")

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    events = list(
        server.run_chat_stream(_session_path(tmp_path), [{"role": "user", "content": "hi"}])
    )

    assert not any("échoué d'affilée" in e for e in events)
    # ran all the way to MAX_ITERATIONS - the breaker never tripped
    assert call_count == server.MAX_ITERATIONS
