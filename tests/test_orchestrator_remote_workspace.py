"""orchestrator.py's _run_subtask now shares subagents.py's
invoke_agent_tool for its own tool dispatch, so a write-capable "code"
role's tools route through the isolated workspace runner for a remote
(workspace://) project the same way a normal conversation's own tool
calls already do - see subagents.py's module docstring."""

import json

from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageToolCallUnion,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

from triton.agents import orchestrator, subagents
from triton.llm.api import ChatResult
from triton.remote_workspaces import RemoteWorkspaceConfig
from triton.storage.projects import Project


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


def test_code_role_routes_writes_through_the_workspace_runner(monkeypatch):
    project = Project(id="p1", name="demo", folder_path="workspace://p1")
    workspace = (RemoteWorkspaceConfig(base_url="http://workspace:8001", token="tok"), "p1")
    role = orchestrator.MultiAgentRole(id="code", label="code", description="", can_write=True)
    subtask = orchestrator.Subtask(id="s1", role="code", description="d", model="m")

    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        subagents,
        "invoke_remote_workspace_tool",
        lambda config, workspace_id, name, args: calls.append((name, args)) or "written",
    )
    monkeypatch.setattr(orchestrator, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(orchestrator, "ensure_snapshot", lambda *a, **kw: False)

    def _fake_call_chat(messages, **_kwargs):
        last = messages[-1]
        if last["role"] == "tool":
            return _final_reply(last["content"])
        return _tool_call_reply("write_file", path="workspace://p1/out.txt", content="hi")

    monkeypatch.setattr(orchestrator, "call_chat", _fake_call_chat)

    orchestrator._run_subtask(subtask, project, None, 1, [subtask], [role], workspace)

    assert subtask.status == "done"
    assert calls == [("write_file", {"path": "out.txt", "content": "hi"})]


def test_research_role_stays_read_only_even_for_a_remote_project(monkeypatch):
    project = Project(id="p1", name="demo", folder_path="workspace://p1")
    workspace = (RemoteWorkspaceConfig(base_url="http://workspace:8001", token="tok"), "p1")
    role = orchestrator.MultiAgentRole(id="research", label="research", description="")
    subtask = orchestrator.Subtask(id="s1", role="research", description="d", model="m")

    monkeypatch.setattr(
        subagents,
        "invoke_remote_workspace_tool",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not reach the runner")),
    )
    monkeypatch.setattr(orchestrator, "log_event", lambda **_kwargs: None)

    def _fake_call_chat(messages, **_kwargs):
        last = messages[-1]
        if last["role"] == "tool":
            return _final_reply(last["content"])
        return _tool_call_reply("write_file", path="workspace://p1/out.txt", content="hi")

    monkeypatch.setattr(orchestrator, "call_chat", _fake_call_chat)

    orchestrator._run_subtask(subtask, project, None, 1, [subtask], [role], workspace)

    assert subtask.status == "done"
