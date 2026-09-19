"""The terminal client must apply the same project boundary as FastAPI.

In particular, read-only tools are dangerous here: the old CLI shortcut
executed them without confirmation, so missing this check could disclose a
local file to the remote model without any user interaction.
"""

import json
from types import SimpleNamespace
from typing import cast

from openai.types.chat import ChatCompletionMessageToolCallUnion
from rich.console import Console

import main
from triton.storage.projects import Project
from triton.tools._shared import Tool


def _tool_call(name: str, args: dict[str, object]) -> ChatCompletionMessageToolCallUnion:
    return cast(
        ChatCompletionMessageToolCallUnion,
        SimpleNamespace(
            id="call_1",
            type="function",
            function=SimpleNamespace(name=name, arguments=json.dumps(args)),
        ),
    )


def _tool(fn) -> Tool:
    return Tool(schema={}, fn=fn, read_only=True)  # type: ignore[arg-type]


def test_cli_blocks_read_only_filesystem_tool_without_project(monkeypatch):
    invoked = False

    def read_file(*, path: str) -> str:
        nonlocal invoked
        invoked = True
        return path

    monkeypatch.setitem(main.TOOLS_REGISTRY, "read_file", _tool(read_file))

    messages = main.run_tool_calls(
        Console(),
        "session",
        [_tool_call("read_file", {"path": "/etc/passwd"})],
        project=None,
    )

    assert invoked is False
    assert "needs a project" in str(messages[0].get("content"))


def test_cli_blocks_path_outside_selected_project(monkeypatch, tmp_path):
    invoked = False
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = Project(id="p1", name="project", folder_path=str(project_root))

    def read_file(*, path: str) -> str:
        nonlocal invoked
        invoked = True
        return path

    monkeypatch.setitem(main.TOOLS_REGISTRY, "read_file", _tool(read_file))

    messages = main.run_tool_calls(
        Console(),
        "session",
        [_tool_call("read_file", {"path": str(tmp_path / "private.txt")})],
        project,
    )

    assert invoked is False
    assert "resolves outside" in str(messages[0].get("content"))


def test_cli_invokes_read_only_tool_inside_selected_project(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    allowed_file = project_root / "allowed.txt"
    project = Project(id="p1", name="project", folder_path=str(project_root))
    invoked_with: list[str] = []

    def read_file(*, path: str) -> str:
        invoked_with.append(path)
        return "safe content"

    monkeypatch.setitem(main.TOOLS_REGISTRY, "read_file", _tool(read_file))

    messages = main.run_tool_calls(
        Console(),
        "session",
        [_tool_call("read_file", {"path": str(allowed_file)})],
        project,
    )

    assert invoked_with == [str(allowed_file)]
    assert messages[0].get("content") == "safe content"
