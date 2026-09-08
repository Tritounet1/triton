"""Every SSE event run_chat_stream yields now carries the session_id it
belongs to (via the emit() closure, wrapping sse()) - what actually makes
"changer de conversation pendant qu'une réponse arrive en streaming" safe
on the client side (App.tsx's sendMessage): it can tell an event meant
for a conversation it's since navigated away from apart from one for
what's currently displayed, instead of blindly applying every update to
`messages`. No real model call: timed_stream_chat is monkeypatched to a
fake reply sequence (one tool call, then a final text reply)."""

import json

import pytest
from openai.types.chat import ChatCompletionMessageFunctionToolCall
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
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)


def _parse_sse(raw: str) -> tuple[str, dict[str, object]]:
    event_line, data_line = raw.strip("\n").split("\n", 1)
    assert event_line.startswith("event: ")
    assert data_line.startswith("data: ")
    return event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: "))


def _session_path(tmp_path):
    path = tmp_path / "sessions" / "test.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_every_event_carries_the_session_id(tmp_path, monkeypatch):
    tool_call_reply = ChatResult(
        content=None,
        tool_calls=[
            ChatCompletionMessageFunctionToolCall(
                id="call_1",
                type="function",
                function=Function(name="this_tool_does_not_exist", arguments="{}"),
            )
        ],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="tool_calls",
    )
    text_reply = ChatResult(
        content="all done",
        tool_calls=[],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="stop",
    )

    calls = 0

    def fake_timed_stream_chat(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        yield "hello "  # a plain text chunk, before the final ChatResult
        yield tool_call_reply if calls == 1 else text_reply

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    session_path = _session_path(tmp_path)
    session_id = session_path.stem
    raw_events = list(server.run_chat_stream(session_path, [{"role": "user", "content": "hi"}]))

    parsed = [_parse_sse(e) for e in raw_events]
    assert len(parsed) >= 4  # session, token, tool_call, done at minimum

    for event, data in parsed:
        assert data.get("session_id") == session_id, f"{event} event missing session_id"

    event_names = [event for event, _ in parsed]
    assert event_names[0] == "session"
    assert "tool_call" in event_names
    assert "done" in event_names


def test_confirmation_required_event_carries_the_session_id(tmp_path, monkeypatch):
    from triton.storage import projects

    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    project = projects.create_project("test-project", str(project_dir))

    session_path = _session_path(tmp_path)
    session_id = session_path.stem
    sessions.save_session_project(session_id, project.id)

    write_reply = ChatResult(
        content=None,
        tool_calls=[
            ChatCompletionMessageFunctionToolCall(
                id="call_1",
                type="function",
                function=Function(
                    name="write_file",
                    arguments=json.dumps({"path": str(project_dir / "hello.txt"), "content": "hi"}),
                ),
            )
        ],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="tool_calls",
    )

    def fake_timed_stream_chat(*_args, **_kwargs):
        yield write_reply

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    gen = server.run_chat_stream(session_path, [{"role": "user", "content": "hi"}])
    events = []
    for raw in gen:
        event, data = _parse_sse(raw)
        events.append((event, data))
        if event == "confirmation_required":
            break

    confirmation_events = [data for event, data in events if event == "confirmation_required"]
    assert len(confirmation_events) == 1
    assert confirmation_events[0]["session_id"] == session_id
    server.PENDING_CONFIRMATIONS.clear()
