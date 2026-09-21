from fastapi.testclient import TestClient

import server
from triton.deployment import DeploymentProfile, WebAuthConfig


def _web_auth_config() -> WebAuthConfig:
    return WebAuthConfig(username="admin", password="password", session_secret="test-secret")


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

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        response = client.post(
            "/chat",
            json={"message": "read this project", "project_id": "project-1"},
        )

    assert login.status_code == 200
    assert response.status_code == 403
    assert response.json()["detail"] == "projects are unavailable in the web deployment profile"


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
