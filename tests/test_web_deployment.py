import json
import logging

from fastapi.testclient import TestClient

import server
from triton.deployment import DeploymentProfile, WebAuthConfig
from triton.remote_workspaces import RemoteWorkspaceConfig, normalize_remote_workspace_args
from triton.storage import projects, sessions
from triton.web_runtime import SlidingWindowRateLimiter, WebRuntimeConfig


def _web_auth_config() -> WebAuthConfig:
    return WebAuthConfig(username="admin", password="password", session_secret="test-secret")


def _tool_names() -> set[str]:
    return {schema["function"]["name"] for schema in server._active_tool_schemas()}


def test_web_profile_only_advertises_safe_remote_tools(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "REMOTE_WORKSPACE_CONFIG", None)

    names = _tool_names()

    assert names == {"fetch_url", "show_link_preview", "show_map", "web_search"}


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
    assert capabilities.json() == {"remote_workspaces": True}


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


def test_web_profile_limits_request_rate(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "WEB_RATE_LIMITER",
        SlidingWindowRateLimiter(
            WebRuntimeConfig(
                max_request_bytes=1024, rate_limit_requests=1, rate_limit_window_seconds=60
            )
        ),
    )

    with TestClient(server.app) as client:
        accepted = client.get("/health")
        limited = client.get("/health")

    assert accepted.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "59"


def test_web_profile_rejects_an_oversized_request(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "WEB_RUNTIME_CONFIG",
        WebRuntimeConfig(
            max_request_bytes=1, rate_limit_requests=120, rate_limit_window_seconds=60
        ),
    )

    with TestClient(server.app) as client:
        response = client.post("/auth/login", content=b"{}")

    assert response.status_code == 413


def test_web_profile_logs_request_metadata(monkeypatch, caplog):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(
        server,
        "WEB_RATE_LIMITER",
        SlidingWindowRateLimiter(
            WebRuntimeConfig(
                max_request_bytes=1024, rate_limit_requests=120, rate_limit_window_seconds=60
            )
        ),
    )
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
