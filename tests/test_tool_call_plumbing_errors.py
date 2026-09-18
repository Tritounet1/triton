"""server.py's run_chat_stream: a tool call's own fn() bug is already
guarded (invoke_tool, _shared.py), but the plumbing around it (the
sandbox check, the snapshot safety net, the confirmation wait...) wasn't
- an exception there used to propagate straight out of the generator,
silently ending the SSE stream with no error event at all (found via a
real report: a message sent, nothing came back, not even an error - just
a lone "history compressed" line then silence). Pins down that any such
exception now surfaces as one failed tool call instead."""

import json
from typing import cast

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


def _final_reply() -> ChatResult:
    return ChatResult(
        content="done",
        tool_calls=[],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="stop",
    )


def _session_path(tmp_path):
    path = tmp_path / "sessions" / "test.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_an_unexpected_error_around_a_tool_call_does_not_kill_the_stream(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "enforce_project_sandbox", boom)

    call_count = 0

    def fake_timed_stream_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        yield _tool_call_result("todo_write", todos=[]) if call_count == 1 else _final_reply()

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    session_path = _session_path(tmp_path)
    events = list(server.run_chat_stream(session_path, [{"role": "user", "content": "hi"}]))

    # the stream reached a normal completion - not silently cut off
    assert any("event: done" in e for e in events)
    tool_call_events = [e for e in events if "event: tool_call" in e]
    assert len(tool_call_events) == 1
    assert "unexpected failure handling todo_write" in tool_call_events[0]
    assert "RuntimeError" in tool_call_events[0]
    assert '"model": "test-model"' in tool_call_events[0]
    saved_tool_request = next(
        message
        for message in sessions.load_session(session_path)
        if message["role"] == "assistant" and message.get("tool_calls")
    )
    assert cast(dict[str, object], saved_tool_request)["model"] == "test-model"
