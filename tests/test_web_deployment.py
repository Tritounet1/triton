import json
import logging

from fastapi.testclient import TestClient

import server
from triton.deployment import DeploymentProfile, WebAuthConfig
from triton.storage import web_accounts
from triton.web_runtime import SlidingWindowRateLimiter, WebRuntimeConfig


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


def test_web_profile_hides_sessions_owned_by_another_account(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    (tmp_path / "another-session.json").write_text("[]")
    web_accounts.initialize_web_accounts("admin", "password")
    web_accounts.assign_session_owner("another-session", "other-account")

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        listed = client.get("/sessions")
        denied = client.get("/sessions/another-session")

    assert login.status_code == 200
    assert listed.json() == []
    assert denied.status_code == 404


def test_administrator_can_manage_web_accounts(monkeypatch):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        created = client.post(
            "/accounts",
            json={"username": "member", "password": "a-long-enough-password"},
        )
        accounts = client.get("/accounts")
        duplicate = client.post(
            "/accounts",
            json={"username": "member", "password": "a-long-enough-password"},
        )
        client.post("/auth/logout")
        member_login = client.post(
            "/auth/login", json={"username": "member", "password": "a-long-enough-password"}
        )
        denied = client.get("/accounts")

    assert login.status_code == 200
    assert created.status_code == 200
    assert created.json()["role"] == "member"
    assert [account["username"] for account in accounts.json()] == ["admin", "member"]
    assert duplicate.status_code == 409
    assert member_login.status_code == 200
    assert denied.status_code == 403


def test_web_profile_searches_only_owned_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    monkeypatch.setattr(server, "WEB_AUTH_CONFIG", _web_auth_config())
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path)
    (tmp_path / "owned.json").write_text('[{"role": "user", "content": "unique phrase"}]')
    (tmp_path / "other.json").write_text('[{"role": "user", "content": "unique phrase"}]')
    owner = web_accounts.initialize_web_accounts("admin", "password")
    web_accounts.assign_session_owner("owned", owner.id)
    web_accounts.assign_session_owner("other", "another-account")

    with TestClient(server.app) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "password"})
        found = client.get("/sessions/search", params={"q": "unique phrase"})

    assert login.status_code == 200
    assert found.json() == ["owned"]
