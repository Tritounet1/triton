import pytest

from triton.deployment import (
    DeploymentProfile,
    load_deployment_profile,
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
    assert not tool_is_allowed(DeploymentProfile.WEB, "mcp__local__tool")


def test_web_profile_denies_host_and_operator_routes():
    assert path_is_allowed(DeploymentProfile.WEB, "/chat")
    assert path_is_allowed(DeploymentProfile.WEB, "/sessions/session-1")
    assert not path_is_allowed(DeploymentProfile.WEB, "/projects/project-1/file")
    assert not path_is_allowed(DeploymentProfile.WEB, "/sessions/session-1/snapshots")
    assert not path_is_allowed(DeploymentProfile.WEB, "/settings/api_key")
    assert not project_is_allowed(DeploymentProfile.WEB, "project-1")


def test_invalid_profile_has_an_actionable_error():
    with pytest.raises(ValueError, match="invalid Triton deployment profile 'vps'"):
        load_deployment_profile("vps")
