import json
import logging

import pytest
from fastapi.testclient import TestClient

import server
from triton import mcp_client
from triton.deployment import DeploymentProfile, WebAuthConfig
from triton.remote_workspaces import (
    RemoteWorkspaceConfig,
    mcp_session_workspace_id,
    normalize_remote_workspace_args,
)
from triton.storage import projects, sessions
from triton.web_runtime import WebRuntimeConfig


def _web_auth_config() -> WebAuthConfig:
    return WebAuthConfig(username="admin", password="password", session_secret="test-secret")


def _tool_names() -> set[str]:
    return {schema["function"]["name"] for schema in server._active_tool_schemas()}


def test_web_profile_only_advertises_safe_remote_tools(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "REMOTE_WORKSPACE_CONFIG", None)

    names = _tool_names()

    assert names == {
        "fetch_url",
        "show_link_preview",
        "show_map",
        "web_search",
        "remember",
        "todo_write",
    }


def test_web_profile_advertises_isolated_project_tools_with_a_workspace(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )

    names = _tool_names()

    assert {
        "read_file",
        "list_files",
        "write_file",
        "edit_file",
        "delete_file",
        "move_file",
        "run_shell",
    }.issubset(names)


def test_web_profile_advertises_runner_mcp_tools_without_a_project(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(
        server,
        "list_remote_mcp_tools",
        lambda config: [
            {
                "type": "function",
                "function": {
                    "name": "mcp__runner__search",
                    "description": "Search runner data",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    names = {schema["function"]["name"] for schema in server._active_tool_schemas()}

    assert "mcp__runner__search" in names


def test_web_mcp_uses_a_dedicated_workspace_for_a_projectless_session(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    created: list[str] = []
    monkeypatch.setattr(
        server,
        "ensure_remote_mcp_session_workspace",
        lambda config, session_id: created.append(session_id) or "mcp-session-test",
    )

    workspace_id = server._mcp_execution_workspace("session-a", None)

    assert workspace_id == "mcp-session-test"
    assert created == ["session-a"]
    assert mcp_session_workspace_id("session-a") == mcp_session_workspace_id("session-a")
    assert mcp_session_workspace_id("session-a") != mcp_session_workspace_id("session-b")


def test_deleting_a_projectless_web_session_removes_its_mcp_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    session_path = sessions.new_session_path()
    sessions.save_session(session_path, [])
    removed: list[str] = []
    monkeypatch.setattr(
        server,
        "delete_remote_workspace",
        lambda config, workspace_id: removed.append(workspace_id),
    )

    assert server.remove_session(session_path.stem) == {"ok": True}
    assert removed == [mcp_session_workspace_id(session_path.stem)]


def test_server_invokes_project_mcp_tools_through_the_workspace_runner(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(
        server,
        "invoke_remote_mcp_tool",
        lambda config, workspace_id, name, args: calls.append((workspace_id, name, args)) or "done",
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["write_file"],
        "mcp__runner__search",
        {"query": "Triton"},
        "session-a",
        "project-a",
    )

    assert result == "done"
    assert calls == [("project-a", "mcp__runner__search", {"query": "Triton"})]


def test_remote_workspace_tool_arguments_stay_in_the_selected_workspace():
    assert normalize_remote_workspace_args(
        "project-a",
        "write_file",
        {"path": "workspace://project-a/src/main.py", "content": "print('ok')"},
    ) == {"path": "src/main.py", "content": "print('ok')"}


def test_remote_workspace_normalizes_start_background_task_directory():
    assert normalize_remote_workspace_args(
        "project-a",
        "start_background_task",
        {"command": "pnpm dev", "directory": "workspace://project-a/app"},
    ) == {"command": "pnpm dev", "directory": "app"}


def test_remote_workspace_normalizes_search_and_git_directory_arguments():
    assert normalize_remote_workspace_args(
        "project-a", "grep", {"pattern": "TODO", "directory": "workspace://project-a/src"}
    ) == {"pattern": "TODO", "directory": "src"}
    assert normalize_remote_workspace_args(
        "project-a", "git_commit", {"message": "wip", "directory": "workspace://project-a"}
    ) == {"message": "wip", "directory": "."}


def test_server_invokes_project_tools_through_the_workspace_runner(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[tuple[str, str, dict[str, object]]] = []
    monkeypatch.setattr(
        server,
        "invoke_remote_workspace_tool",
        lambda config, workspace_id, name, args: calls.append((workspace_id, name, args)) or "done",
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["write_file"],
        "write_file",
        {"path": "main.py", "content": "print('ok')"},
        "session-a",
        "project-a",
    )

    assert result == "done"
    assert calls == [("project-a", "write_file", {"path": "main.py", "content": "print('ok')"})]


@pytest.mark.parametrize(
    "tool_name, args",
    [("web_search", {"query": "Triton"}), ("fetch_url", {"url": "https://example.com"})],
)
def test_server_keeps_project_network_tools_in_the_api(monkeypatch, tool_name, args):
    calls: list[tuple[str, dict[str, object], str]] = []
    monkeypatch.setattr(
        server,
        "invoke_remote_workspace_tool",
        lambda config, workspace_id, name, args: (_ for _ in ()).throw(AssertionError(name)),
    )
    monkeypatch.setattr(
        server,
        "invoke_tool",
        lambda tool, name, args, session_id: calls.append((name, args, session_id)) or "result",
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY[tool_name],
        tool_name,
        args,
        "session-a",
        "project-a",
    )

    assert result == "result"
    assert calls == [(tool_name, args, "session-a")]


def test_server_starts_a_background_task_through_the_workspace_runner(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[tuple[str, str, str, str, str]] = []
    monkeypatch.setattr(
        server,
        "start_remote_task",
        lambda config, workspace_id, session_id, command, name, directory: (
            calls.append((workspace_id, session_id, command, name, directory))
            or {"id": "task-1", "name": name or command, "directory": "."}
        ),
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["start_background_task"],
        "start_background_task",
        {"command": "pnpm dev"},
        "session-a",
        "project-a",
    )

    assert calls == [("project-a", "session-a", "pnpm dev", "", "")]
    assert "id=task-1" in result


def test_server_lists_and_stops_background_tasks_through_the_workspace_runner(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(
        server,
        "list_remote_tasks",
        lambda config, workspace_id, session_id: [
            {
                "id": "task-1",
                "status": "running",
                "name": "dev server",
                "directory": ".",
            }
        ],
    )
    stopped: list[str] = []
    monkeypatch.setattr(
        server,
        "stop_remote_task",
        lambda config, workspace_id, task_id: (
            stopped.append(task_id) or {"id": task_id, "status": "stopped"}
        ),
    )

    listed = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["list_background_tasks"],
        "list_background_tasks",
        {},
        "session-a",
        "project-a",
    )
    stopped_result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["stop_background_task"],
        "stop_background_task",
        {"task_id": "task-1"},
        "session-a",
        "project-a",
    )

    assert "task-1" in listed and "dev server" in listed
    assert stopped == ["task-1"]
    assert stopped_result == "task task-1 stopped"


def test_server_keeps_mcp_tools_local_for_the_desktop_executor(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[tuple[str, dict[str, object], str]] = []
    monkeypatch.setattr(
        server,
        "invoke_tool",
        lambda tool, name, args, session_id: calls.append((name, args, session_id)) or "done",
    )
    monkeypatch.setattr(
        server,
        "invoke_remote_workspace_tool",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not reach the runner")),
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY.get("mcp__example__tool", server.TOOLS_REGISTRY["write_file"]),
        "mcp__example__tool",
        {"query": "hi"},
        "session-a",
        None,
    )

    assert result == "done"
    assert calls == [("mcp__example__tool", {"query": "hi"}, "session-a")]


def test_desktop_profile_updates_an_mcp_server_without_deleting_it(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", tmp_path / "mcp_servers.json")

    with TestClient(server.app) as client:
        client.post(
            "/mcp/servers",
            json={"name": "notes", "command": "python", "args": [], "enabled": False},
        )
        updated = client.patch(
            "/mcp/servers/notes",
            json={"name": "notes", "command": "uvx", "args": ["notes-mcp"], "enabled": False},
        )
        missing = client.patch(
            "/mcp/servers/ghost",
            json={"name": "ghost", "command": "python", "enabled": False},
        )

    assert updated.status_code == 200
    [server_status] = updated.json()
    assert server_status["command"] == "uvx"
    assert server_status["args"] == ["notes-mcp"]
    assert missing.status_code == 404


def test_web_profile_updates_an_mcp_server_through_the_workspace_runner(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        server,
        "update_remote_mcp_server",
        lambda config, name, body: calls.append((name, body)) or [{"name": body["name"]}],
    )

    result = server.update_mcp_server(
        "notes", server.MCPServerCreate(name="notes", command="uvx", args=["notes-mcp"])
    )

    assert result == [{"name": "notes"}]
    assert calls[0][0] == "notes"
    assert calls[0][1]["command"] == "uvx"


def test_web_profile_resumes_orchestrator_runs_when_remote_workspaces_are_configured(
    monkeypatch,
):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[bool] = []
    monkeypatch.setattr(server.orchestrator, "resume_incomplete_runs", lambda: calls.append(True))

    with TestClient(server.app):
        pass

    assert calls == [True]


def test_web_profile_does_not_resume_orchestrator_runs_without_remote_workspaces(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "REMOTE_WORKSPACE_CONFIG", None)
    calls: list[bool] = []
    monkeypatch.setattr(server.orchestrator, "resume_incomplete_runs", lambda: calls.append(True))

    with TestClient(server.app):
        pass

    assert calls == []


def test_server_invokes_remember_locally_even_inside_a_remote_workspace(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        server,
        "invoke_tool",
        lambda tool, name, args, session_id: calls.append(name) or "remembered: hi",
    )
    monkeypatch.setattr(
        server,
        "invoke_remote_workspace_tool",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not reach the runner")),
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["remember"],
        "remember",
        {"note": "hi"},
        "session-a",
        "project-a",
    )

    assert result == "remembered: hi"
    assert calls == ["remember"]


def test_server_invokes_dispatch_subagent_locally_even_inside_a_remote_workspace(monkeypatch):
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        server,
        "invoke_tool",
        lambda tool, name, args, session_id: calls.append(name) or "dispatched",
    )
    monkeypatch.setattr(
        server,
        "invoke_remote_workspace_tool",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not reach the runner")),
    )

    result = server._invoke_chat_tool(
        server.TOOLS_REGISTRY["dispatch_subagent"],
        "dispatch_subagent",
        {"task": "investigate"},
        "session-a",
        "project-a",
    )

    assert result == "dispatched"
    assert calls == ["dispatch_subagent"]


def test_desktop_profile_keeps_local_tools(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.DESKTOP)

    assert "run_shell" in _tool_names()
    assert "read_file" in _tool_names()


def test_web_profile_rejects_host_management_routes(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "REMOTE_WORKSPACE_CONFIG", None)

    with TestClient(server.app) as client:
        response = client.get("/projects")

    assert response.status_code == 403
    assert response.json()["detail"] == "this endpoint is unavailable in the web deployment profile"


def test_web_profile_serves_the_client_before_login(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    (tmp_path / "index.html").write_text("<main>Triton</main>")
    monkeypatch.setattr(server, "WEB_FRONTEND_DIR", tmp_path)

    with TestClient(server.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_web_profile_serves_frontend_images_after_login(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    (tmp_path / "anthropic-logo.png").write_bytes(b"logo")
    monkeypatch.setattr(server, "WEB_FRONTEND_DIR", tmp_path)

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.get("/anthropic-logo.png")

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.content == b"logo"


def test_web_profile_rejects_project_scoped_chat(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(server, "REMOTE_WORKSPACE_CONFIG", None)

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.post(
            "/chat",
            json={"message": "read this project", "project_id": "project-1"},
        )

    assert login.status_code == 200
    assert response.status_code == 403
    assert response.json()["detail"] == "projects are unavailable in the web deployment profile"


def test_web_profile_creates_projects_in_the_remote_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    created_workspaces: list[str] = []
    monkeypatch.setattr(
        server,
        "create_remote_workspace",
        lambda config, workspace_id: created_workspaces.append(workspace_id),
    )

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.post("/projects", json={"name": "Mon projet"})

    assert login.status_code == 200
    assert response.status_code == 200
    project = response.json()[0]
    assert project["folder_path"] == f"workspace://{project['id']}"
    assert created_workspaces == [project["id"]]


def test_web_profile_reads_remote_project_files(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    projects.create_project("Mon projet", "workspace://project-a", "project-a")
    monkeypatch.setattr(
        server,
        "remote_workspace_tree",
        lambda config, workspace_id: {"tree": [{"name": "readme.md"}], "truncated": False},
    )
    monkeypatch.setattr(
        server,
        "remote_workspace_file",
        lambda config, workspace_id, path: (b"# Triton", "text/markdown"),
    )

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        tree = client.get("/projects/project-a/tree")
        file = client.get("/projects/project-a/file", params={"path": "readme.md"})
        capabilities = client.get("/deployment/capabilities")

    assert login.status_code == 200
    assert tree.json() == {"tree": [{"name": "readme.md"}], "truncated": False}
    assert file.content == b"# Triton"
    assert file.headers["content-type"] == "text/markdown; charset=utf-8"
    assert capabilities.json() == {
        "remote_workspaces": True,
        "projects": True,
        "background_tasks": True,
        "subagents": True,
        "snapshots": True,
        "orchestrator": True,
    }


def test_web_profile_deletes_the_remote_workspace_with_its_project(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    projects.create_project("Mon projet", "workspace://project-a", "project-a")
    deleted_workspaces: list[str] = []
    monkeypatch.setattr(
        server,
        "delete_remote_workspace",
        lambda config, workspace_id: deleted_workspaces.append(workspace_id),
    )

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.delete("/projects/project-a")

    assert login.status_code == 200
    assert response.json() == []
    assert deleted_workspaces == ["project-a"]


def test_server_logs_remote_project_creation_and_deletion(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(server, "create_remote_workspace", lambda config, workspace_id: None)
    monkeypatch.setattr(server, "delete_remote_workspace", lambda config, workspace_id: None)
    events: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(
        server,
        "log_event",
        lambda **kwargs: events.append((kwargs["type"], kwargs["project_id"], kwargs["remote"])),
    )

    with TestClient(server.app) as client:
        client.post("/auth/login", json={"username": "admin", "password": "password"})
        created = client.post("/projects", json={"name": "Mon projet"})
        project_id = created.json()[0]["id"]
        client.delete(f"/projects/{project_id}")

    assert events == [
        ("project_created", project_id, True),
        ("project_deleted", project_id, True),
    ]


def test_web_profile_sweeps_orphaned_workspaces_at_startup(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path / "sessions")
    projects.create_project("Mon projet", "workspace://project-a", "project-a")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        server,
        "purge_remote_maintenance",
        lambda config, keep_workspace_ids: (
            calls.append(keep_workspace_ids)
            or {
                "orphaned_workspaces_removed": 0,
                "expired_snapshots_removed": 0,
            }
        ),
    )

    with TestClient(server.app):
        pass

    assert calls == [["project-a"]]


def test_web_profile_preserves_mcp_workspaces_for_existing_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "session-a.json").write_text("[]")
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        server,
        "purge_remote_maintenance",
        lambda config, keep_workspace_ids: (
            calls.append(keep_workspace_ids)
            or {"orphaned_workspaces_removed": 0, "expired_snapshots_removed": 0}
        ),
    )

    with TestClient(server.app):
        pass

    assert calls == [[mcp_session_workspace_id("session-a")]]


def _workspace_session(monkeypatch, tmp_path, workspace_id: str = "project-a") -> str:
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    projects.create_project("Mon projet", f"workspace://{workspace_id}", workspace_id)
    session_path = sessions.new_session_path()
    sessions.save_session(session_path, [])
    session_id = session_path.stem
    sessions.save_session_project(session_id, workspace_id)
    return session_id


def test_web_profile_lists_background_tasks_from_the_workspace_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    session_id = _workspace_session(monkeypatch, tmp_path)
    monkeypatch.setattr(
        server,
        "list_remote_tasks",
        lambda config, workspace_id, session_id: [
            {
                "id": "task-1",
                "session_id": session_id,
                "name": "dev server",
                "command": "pnpm dev",
                "directory": ".",
                "status": "running",
                "created_at": "2026-01-01T00:00:00",
            }
        ],
    )

    with TestClient(server.app) as client:
        client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.get("/background_tasks", params={"session_id": session_id})

    assert response.status_code == 200
    [task] = response.json()
    assert task["id"] == "project-a:task-1"
    assert task["exit_code"] is None


def test_web_profile_reads_stops_and_deletes_a_remote_background_task(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    _workspace_session(monkeypatch, tmp_path)
    task = {
        "id": "task-1",
        "session_id": "session-a",
        "name": "dev server",
        "command": "pnpm dev",
        "directory": ".",
        "status": "running",
        "created_at": "2026-01-01T00:00:00",
        "logs": "starting up",
    }
    monkeypatch.setattr(server, "get_remote_task", lambda config, workspace_id, task_id: task)
    stopped: list[str] = []
    monkeypatch.setattr(
        server,
        "stop_remote_task",
        lambda config, workspace_id, task_id: stopped.append(task_id),
    )
    deleted: list[str] = []
    monkeypatch.setattr(
        server,
        "delete_remote_task",
        lambda config, workspace_id, task_id: deleted.append(task_id),
    )

    with TestClient(server.app) as client:
        client.post("/auth/login", json={"username": "admin", "password": "password"})
        detail = client.get("/background_tasks/project-a:task-1")
        stop_response = client.post("/background_tasks/project-a:task-1/stop")
        delete_response = client.delete("/background_tasks/project-a:task-1")

    assert detail.json()["logs"] == "starting up"
    assert stop_response.status_code == 200
    assert stopped == ["task-1"]
    assert delete_response.json() == {"deleted": True}
    assert deleted == ["task-1"]


def test_web_profile_lists_snapshots_from_the_workspace_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    session_id = _workspace_session(monkeypatch, tmp_path)
    monkeypatch.setattr(
        server,
        "list_remote_snapshots",
        lambda config, workspace_id, session_id: [
            {"turn_index": 1, "created_at": "2026-01-01T00:00:00"}
        ],
    )

    with TestClient(server.app) as client:
        client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.get(f"/sessions/{session_id}/snapshots")

    assert response.status_code == 200
    [point] = response.json()
    assert point["turn_index"] == 1
    assert point["kind"] == "remote"
    assert point["has_final_state"] is False


def test_web_profile_restores_a_snapshot_through_the_workspace_runner(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "REMOTE_WORKSPACE_CONFIG",
        RemoteWorkspaceConfig(base_url="http://workspace:8001", token="workspace-token"),
    )
    session_id = _workspace_session(monkeypatch, tmp_path)
    calls: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        server,
        "restore_remote_snapshot",
        lambda config, workspace_id, session_id, turn_index: calls.append(
            (workspace_id, session_id, turn_index)
        ),
    )

    with TestClient(server.app) as client:
        client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.post(f"/sessions/{session_id}/snapshot/restore", json={"turn_index": 1})

    assert response.json() == {"restored": True}
    assert calls == [("project-a", session_id, 1)]


def test_web_profile_allows_image_generation_in_a_conversation(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    monkeypatch.setattr(
        server,
        "generate_image",
        lambda prompt, model, references: type(
            "ImageResult", (), {"images": ["data:image/png;base64,aGVsbG8="], "model": "test/image"}
        )(),
    )

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.post("/images/generate", json={"prompt": "un chat"})

    assert login.status_code == 200
    assert response.status_code == 200
    assert response.json()["images"] == ["data:image/png;base64,aGVsbG8="]


def test_web_profile_requires_a_configured_authenticated_session(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())

    with TestClient(server.app) as client:
        denied = client.get("/sessions")
        rejected_login = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
        accepted_login = client.post(
            "/auth/login", json={"username": "admin", "password": "password"}
        )
        session = client.get("/auth/session")
        accepted = client.get("/sessions")

    assert denied.status_code == 401
    assert rejected_login.status_code == 401
    assert accepted_login.status_code == 200
    assert session.json() == {"authenticated": True}
    assert accepted.status_code == 200


def test_web_profile_rejects_an_oversized_request(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(server, "WEB_RUNTIME_CONFIG", WebRuntimeConfig(max_request_bytes=1))

    with TestClient(server.app) as client:
        response = client.post("/auth/login", content=b"{}")

    assert response.status_code == 413


def test_web_profile_logs_request_metadata(monkeypatch, caplog):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    with TestClient(server.app) as client:
        response = client.get("/health")

    events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "uvicorn.error" and record.message.startswith("{")
    ]
    assert response.status_code == 200
    event = events[-1]
    assert event["type"] == "web_request"
    assert event["method"] == "GET"
    assert event["path"] == "/health"
    assert event["status_code"] == 200
    assert isinstance(event["duration_ms"], int)
