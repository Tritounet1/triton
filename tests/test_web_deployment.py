from fastapi.testclient import TestClient

import server
from triton.deployment import DeploymentProfile


def _tool_names() -> set[str]:
    return {schema["function"]["name"] for schema in server._active_tool_schemas()}


def test_web_profile_only_advertises_safe_remote_tools(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)

    names = _tool_names()

    assert names == {"fetch_url", "show_link_preview", "show_map", "web_search"}


def test_desktop_profile_keeps_local_tools(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.DESKTOP)

    assert "run_shell" in _tool_names()
    assert "read_file" in _tool_names()


def test_web_profile_rejects_host_management_routes(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)

    with TestClient(server.app) as client:
        response = client.get("/projects")

    assert response.status_code == 403
    assert response.json()["detail"] == "this endpoint is unavailable in the web deployment profile"


def test_web_profile_rejects_project_scoped_chat(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)

    with TestClient(server.app) as client:
        response = client.post(
            "/chat",
            json={"message": "read this project", "project_id": "project-1"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "projects are unavailable in the web deployment profile"
