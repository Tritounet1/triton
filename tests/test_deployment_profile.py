import pytest

from triton.deployment import (
    DeploymentProfile,
    load_deployment_profile,
    load_web_auth_config,
    path_is_allowed,
    project_is_allowed,
    tool_is_allowed,
)


def test_desktop_profile_keeps_existing_capabilities():
    assert tool_is_allowed(DeploymentProfile.DESKTOP, "run_shell")
    assert path_is_allowed(DeploymentProfile.DESKTOP, "/projects/project-1/file")
    assert project_is_allowed(DeploymentProfile.DESKTOP, "project-1")


def test_web_profile_allows_only_remote_safe_tools():
    assert tool_is_allowed(DeploymentProfile.WEB, "web_search")
    assert not tool_is_allowed(DeploymentProfile.WEB, "read_file")
    assert not tool_is_allowed(DeploymentProfile.WEB, "run_shell")


def test_web_profile_always_allows_mcp_tools():
    assert tool_is_allowed(DeploymentProfile.WEB, "mcp__local__tool")
    assert path_is_allowed(DeploymentProfile.WEB, "/mcp/servers")


def test_web_profile_allows_remote_workspace_tools_only_when_enabled():
    assert not tool_is_allowed(DeploymentProfile.WEB, "read_file")
    assert not tool_is_allowed(DeploymentProfile.WEB, "start_background_task")
    assert tool_is_allowed(DeploymentProfile.WEB, "read_file", remote_workspaces_enabled=True)
    assert tool_is_allowed(
        DeploymentProfile.WEB, "start_background_task", remote_workspaces_enabled=True
    )
    assert tool_is_allowed(
        DeploymentProfile.WEB, "stop_background_task", remote_workspaces_enabled=True
    )
    assert tool_is_allowed(
        DeploymentProfile.WEB, "list_background_tasks", remote_workspaces_enabled=True
    )
    assert tool_is_allowed(DeploymentProfile.WEB, "grep", remote_workspaces_enabled=True)
    assert tool_is_allowed(DeploymentProfile.WEB, "git_status", remote_workspaces_enabled=True)
    assert tool_is_allowed(DeploymentProfile.WEB, "run_tests", remote_workspaces_enabled=True)
    assert not tool_is_allowed(DeploymentProfile.WEB, "grep")


def test_web_profile_allows_background_tasks_route_only_when_remote_workspaces_enabled():
    assert not path_is_allowed(DeploymentProfile.WEB, "/background_tasks")
    assert not path_is_allowed(DeploymentProfile.WEB, "/background_tasks/task-1/stop")
    assert path_is_allowed(
        DeploymentProfile.WEB, "/background_tasks", remote_workspaces_enabled=True
    )
    assert path_is_allowed(
        DeploymentProfile.WEB, "/background_tasks/task-1/stop", remote_workspaces_enabled=True
    )


def test_web_profile_denies_host_and_operator_routes():
    assert path_is_allowed(DeploymentProfile.WEB, "/chat")
    assert path_is_allowed(DeploymentProfile.WEB, "/images/generate")
    assert path_is_allowed(DeploymentProfile.WEB, "/settings/image_model")
    assert path_is_allowed(DeploymentProfile.WEB, "/sessions/session-1")
    assert not path_is_allowed(DeploymentProfile.WEB, "/projects/project-1/file")
    assert not path_is_allowed(DeploymentProfile.WEB, "/sessions/session-1/snapshots")
    assert not path_is_allowed(DeploymentProfile.WEB, "/settings/api_key")
    assert not project_is_allowed(DeploymentProfile.WEB, "project-1")


def test_invalid_profile_has_an_actionable_error():
    with pytest.raises(ValueError, match="invalid Triton deployment profile 'vps'"):
        load_deployment_profile("vps")


def test_web_auth_uses_secure_cookies_by_default(monkeypatch):
    monkeypatch.delenv("TRITON_WEB_SECURE_COOKIES", raising=False)
    monkeypatch.setenv("TRITON_WEB_USERNAME", "admin")
    monkeypatch.setenv("TRITON_WEB_PASSWORD", "password")
    monkeypatch.setenv("TRITON_WEB_SESSION_SECRET", "secret")

    config = load_web_auth_config()

    assert config is not None
    assert config.secure_cookies


def test_web_auth_allows_insecure_cookies_only_when_explicit(monkeypatch):
    monkeypatch.setenv("TRITON_WEB_USERNAME", "admin")
    monkeypatch.setenv("TRITON_WEB_PASSWORD", "password")
    monkeypatch.setenv("TRITON_WEB_SESSION_SECRET", "secret")
    monkeypatch.setenv("TRITON_WEB_SECURE_COOKIES", "false")

    config = load_web_auth_config()

    assert config is not None
    assert not config.secure_cookies
