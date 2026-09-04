"""/yolo: a session is in yolo mode purely by a `.yolo` marker file's
presence next to its `.json` (see storage/sessions.py's is_yolo_enabled/
set_yolo_enabled), the same convention as pinning (test_sessions_pin.py).
Covers the storage layer directly, the GET/POST /sessions/{id}/yolo
endpoints, and that run_chat_stream actually skips the confirmation
prompt for a non-read-only tool call while it's on - without touching
enforce_project_sandbox at all."""

import json

import pytest
from fastapi.testclient import TestClient
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageToolCallUnion,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

import server
from triton.llm.api import ChatResult
from triton.storage import projects, sessions, settings


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    # server.py does `from triton.storage.sessions import SESSIONS_DIR`, its
    # own separate name bound at import time - both need patching (see
    # test_sessions_pin.py for the same footgun).
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
def client():
    return TestClient(server.app)


def _new_session() -> str:
    path = sessions.new_session_path()
    sessions.save_session(path, [])
    return path.stem


# --- storage layer ---


def test_new_session_is_not_in_yolo_mode():
    session_id = _new_session()
    assert sessions.is_yolo_enabled(session_id) is False


def test_set_yolo_enabled_toggles_the_marker_file():
    session_id = _new_session()
    sessions.set_yolo_enabled(session_id, True)
    assert sessions.is_yolo_enabled(session_id) is True

    sessions.set_yolo_enabled(session_id, False)
    assert sessions.is_yolo_enabled(session_id) is False


def test_delete_session_removes_the_yolo_marker():
    session_id = _new_session()
    sessions.set_yolo_enabled(session_id, True)

    sessions.delete_session(session_id)

    assert not sessions.yolo_path(session_id).exists()


# --- GET/POST /sessions/{id}/yolo ---


def test_yolo_endpoint_toggles_and_persists(client):
    session_id = _new_session()

    r = client.get(f"/sessions/{session_id}/yolo")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}

    r = client.post(f"/sessions/{session_id}/yolo")
    assert r.status_code == 200
    assert r.json() == {"enabled": True}
    assert sessions.is_yolo_enabled(session_id) is True

    r = client.post(f"/sessions/{session_id}/yolo")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}
    assert sessions.is_yolo_enabled(session_id) is False


def test_yolo_endpoints_404_for_unknown_session(client):
    assert client.get("/sessions/does-not-exist/yolo").status_code == 404
    assert client.post("/sessions/does-not-exist/yolo").status_code == 404


# --- run_chat_stream actually skips confirmation while yolo is on ---


def _tool_call_result(tool_name: str, **arguments: object) -> ChatResult:
    tool_calls: list[ChatCompletionMessageToolCallUnion] = [
        ChatCompletionMessageFunctionToolCall(
            id="call_1",
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


def test_yolo_mode_skips_confirmation_for_a_write_tool(tmp_path, monkeypatch):
    """write_file is not read-only - normally this would emit
    confirmation_required and block on PendingConfirmation.event.wait().
    With yolo on, it must run straight through instead."""
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    project = projects.create_project("test-project", str(project_dir))

    session_id = _new_session()
    sessions.save_session_project(session_id, project.id)
    sessions.set_yolo_enabled(session_id, True)

    def fake_timed_stream_chat(*_args, **_kwargs):
        yield _tool_call_result("write_file", path=str(project_dir / "hello.txt"), content="hi")

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    session_path = sessions.session_path(session_id)
    events = list(
        server.run_chat_stream(
            session_path, sessions.load_session(session_path) or [{"role": "user", "content": "hi"}]
        )
    )

    assert not any("confirmation_required" in e for e in events)
    assert (project_dir / "hello.txt").read_text() == "hi"


def test_without_yolo_a_write_tool_still_asks_for_confirmation(tmp_path, monkeypatch):
    """Sanity check for the test above: the same setup, minus yolo, must
    still go through the normal confirmation flow (and therefore never
    write the file, since nothing answers the prompt here).

    Deliberately does NOT drain the generator with list(...): past the
    confirmation_required event, run_chat_stream blocks for up to 300s
    on PendingConfirmation.event.wait() - stopping as soon as that event
    is seen leaves the generator paused right at its yield, never
    reaching that call."""
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    project = projects.create_project("test-project", str(project_dir))

    session_id = _new_session()
    sessions.save_session_project(session_id, project.id)

    def fake_timed_stream_chat(*_args, **_kwargs):
        yield _tool_call_result("write_file", path=str(project_dir / "hello.txt"), content="hi")

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    session_path = sessions.session_path(session_id)
    initial_messages = sessions.load_session(session_path) or [{"role": "user", "content": "hi"}]
    gen = server.run_chat_stream(session_path, initial_messages)
    events = []
    for event in gen:
        events.append(event)
        if "confirmation_required" in event:
            break
    server.PENDING_CONFIRMATIONS.clear()

    assert any("confirmation_required" in e for e in events)
    assert not (project_dir / "hello.txt").exists()
