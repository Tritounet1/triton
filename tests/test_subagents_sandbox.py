"""subagents.py's _run now wires enforce_project_sandbox into its own
tool-dispatch loop - previously it called every tool directly with no
sandboxing at all, so a subagent could read anywhere on disk regardless
of the parent conversation's own project scope (or lack of one). Mocks
call_chat to avoid a real model call: these tests only care about which
tool result lands back in the conversation, not the model's own
reasoning."""

import json

import pytest
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageToolCallUnion,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

from triton.agents import subagents
from triton.llm.api import ChatResult
from triton.storage import projects, sessions
from triton.storage.projects import Project
from triton.tools.background import dispatch_subagent


def _tool_call_reply(name: str, **arguments: object) -> ChatResult:
    tool_calls: list[ChatCompletionMessageToolCallUnion] = [
        ChatCompletionMessageFunctionToolCall(
            id="call_1",
            type="function",
            function=Function(name=name, arguments=json.dumps(arguments)),
        )
    ]
    return ChatResult(
        content=None,
        tool_calls=tool_calls,
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    )


def _final_reply(content: str) -> ChatResult:
    return ChatResult(
        content=content,
        tool_calls=[],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
    )


def _run_one_tool_call(monkeypatch, project: Project | None, name: str, **arguments: object) -> str:
    """Runs a subagent through exactly one tool call, returning the
    result that landed back in its own conversation - the sandbox error
    if enforce_project_sandbox blocked it, or the tool's real output."""
    captured: list[str] = []

    def _fake_call_chat(messages, **_kwargs):
        last = messages[-1]
        if last["role"] == "tool":
            captured.append(last["content"])
            return _final_reply("done")
        return _tool_call_reply(name, **arguments)

    monkeypatch.setattr(subagents, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(subagents, "call_chat", _fake_call_chat)

    task_entry = subagents.SubagentTask(id="t1", task="test task")
    subagents._run(task_entry, project)

    assert task_entry.status == "done"
    return captured[0]


def test_read_file_is_blocked_without_a_project(monkeypatch, tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("should never be read")

    result = _run_one_tool_call(monkeypatch, None, "read_file", path=str(target))

    assert result.startswith("error:")
    assert "needs a project" in result


def test_read_file_is_scoped_to_the_dispatching_conversations_project(monkeypatch, tmp_path):
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    project = Project(id="p1", name="myproject", folder_path=str(project_dir))
    outside = tmp_path / "outside.txt"
    outside.write_text("should never be read")

    result = _run_one_tool_call(monkeypatch, project, "read_file", path=str(outside))

    assert result.startswith("error:")
    assert "outside of it" in result


def test_read_file_succeeds_for_a_path_inside_the_scoped_project(monkeypatch, tmp_path):
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / "a.txt").write_text("inside the project")
    project = Project(id="p1", name="myproject", folder_path=str(project_dir))

    result = _run_one_tool_call(monkeypatch, project, "read_file", path=str(project_dir / "a.txt"))

    assert result == "inside the project"


def test_web_search_is_unaffected_by_missing_project(monkeypatch):
    from triton.tools import TOOLS_REGISTRY

    monkeypatch.setattr(subagents, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(TOOLS_REGISTRY["web_search"], "fn", lambda query: f"results for {query}")

    result = _run_one_tool_call(monkeypatch, None, "web_search", query="triton")

    assert result == "results for triton"


# --- dispatch_subagent (tools/background.py): resolves the project from session_id ---


@pytest.fixture
def _isolated_session_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")


def test_dispatch_subagent_passes_the_sessions_project_through(
    monkeypatch, _isolated_session_storage
):
    project = projects.create_project("demo", "/tmp/demo")
    path = sessions.new_session_path()
    sessions.save_session(path, [])
    session_id = path.stem
    sessions.save_session_project(session_id, project.id)

    seen: list[Project | None] = []
    monkeypatch.setattr(subagents, "dispatch", lambda _task, project=None: seen.append(project))

    dispatch_subagent("do something", session_id)

    assert seen == [project]


def test_dispatch_subagent_passes_none_when_the_session_has_no_project(
    monkeypatch, _isolated_session_storage
):
    path = sessions.new_session_path()
    sessions.save_session(path, [])
    session_id = path.stem

    seen: list[Project | None] = []
    monkeypatch.setattr(subagents, "dispatch", lambda _task, project=None: seen.append(project))

    dispatch_subagent("do something", session_id)

    assert seen == [None]
