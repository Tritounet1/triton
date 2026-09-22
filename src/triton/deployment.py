from dataclasses import dataclass
from enum import StrEnum
from os import getenv

from triton.mcp_client import MCP_PREFIX


class DeploymentProfile(StrEnum):
    DESKTOP = "desktop"
    WEB = "web"


WEB_TOOL_NAMES = frozenset({"fetch_url", "show_link_preview", "show_map", "web_search"})
REMOTE_WORKSPACE_TOOL_NAMES = frozenset(
    {
        "read_file",
        "list_files",
        "write_file",
        "edit_file",
        "delete_file",
        "move_file",
        "run_shell",
        "start_background_task",
        "stop_background_task",
        "list_background_tasks",
        "grep",
        "glob",
        "git_status",
        "git_diff",
        "git_commit",
        "git_log",
        "git_branch",
        "git_checkout",
        "git_push",
        "run_tests",
        "run_code",
        "dispatch_subagent",
        "check_subagent",
    }
)

WEB_DENIED_PATH_PREFIXES = (
    "/backup",
    "/background_tasks",
    "/logs",
    "/orchestrator",
    "/projects",
    "/scheduled_tasks",
    "/subagents",
)

WEB_DENIED_PATHS = {
    "/memory/global",
    "/settings/api_key",
    "/settings/budget",
    "/settings/budget/status",
    "/settings/max_subtasks",
    "/settings/tavily_key",
}

# meaningless without a remote workspace to actually run subtasks in -
# same override pattern as WEB_DENIED_PATH_PREFIXES below, just against
# an exact settings path rather than a whole route tree
WEB_REMOTE_WORKSPACE_SETTINGS_PATHS = ("/settings/multi_agent_roles", "/settings/role_models")


def load_deployment_profile(value: str | None = None) -> DeploymentProfile:
    raw = value if value is not None else getenv("TRITON_DEPLOYMENT_PROFILE", "desktop")
    try:
        return DeploymentProfile(raw.lower())
    except ValueError as exc:
        choices = ", ".join(profile.value for profile in DeploymentProfile)
        raise ValueError(
            f"invalid Triton deployment profile '{raw}'; expected one of: {choices}"
        ) from exc


def tool_is_allowed(
    profile: DeploymentProfile, tool_name: str, remote_workspaces_enabled: bool = False
) -> bool:
    return (
        profile is DeploymentProfile.DESKTOP
        or tool_name in WEB_TOOL_NAMES
        or tool_name.startswith(MCP_PREFIX)
        or (remote_workspaces_enabled and tool_name in REMOTE_WORKSPACE_TOOL_NAMES)
    )


def path_is_allowed(
    profile: DeploymentProfile, path: str, remote_workspaces_enabled: bool = False
) -> bool:
    if profile is DeploymentProfile.DESKTOP:
        return True
    if path.startswith(WEB_REMOTE_WORKSPACE_SETTINGS_PATHS) or (
        path.startswith("/sessions/") and "/snapshot" in path
    ):
        return remote_workspaces_enabled
    if path in WEB_DENIED_PATHS:
        return False
    if (
        path.startswith(("/projects", "/background_tasks", "/subagents", "/orchestrator"))
        and remote_workspaces_enabled
    ):
        return True
    return not path.startswith(WEB_DENIED_PATH_PREFIXES)


def project_is_allowed(
    profile: DeploymentProfile, project_id: str | None, remote_workspaces_enabled: bool = False
) -> bool:
    return profile is DeploymentProfile.DESKTOP or project_id is None or remote_workspaces_enabled


@dataclass(frozen=True)
class WebAuthConfig:
    username: str
    password: str
    session_secret: str
    secure_cookies: bool = True


def load_web_auth_config() -> WebAuthConfig | None:
    username = getenv("TRITON_WEB_USERNAME")
    password = getenv("TRITON_WEB_PASSWORD")
    session_secret = getenv("TRITON_WEB_SESSION_SECRET")
    if not any((username, password, session_secret)):
        return None
    if not username or not password or not session_secret:
        raise ValueError(
            "TRITON_WEB_USERNAME, TRITON_WEB_PASSWORD, and "
            "TRITON_WEB_SESSION_SECRET must all be configured"
        )
    secure_cookies = getenv("TRITON_WEB_SECURE_COOKIES", "true").lower()
    if secure_cookies not in {"true", "false"}:
        raise ValueError("TRITON_WEB_SECURE_COOKIES must be true or false")
    return WebAuthConfig(
        username=username,
        password=password,
        session_secret=session_secret,
        secure_cookies=secure_cookies == "true",
    )
