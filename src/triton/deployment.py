from dataclasses import dataclass
from enum import StrEnum
from os import getenv


class DeploymentProfile(StrEnum):
    DESKTOP = "desktop"
    WEB = "web"


WEB_TOOL_NAMES = frozenset({"fetch_url", "show_link_preview", "show_map", "web_search"})

WEB_DENIED_PATH_PREFIXES = (
    "/backup",
    "/background_tasks",
    "/logs",
    "/mcp",
    "/orchestrator",
    "/projects",
    "/scheduled_tasks",
    "/subagents",
)

WEB_DENIED_PATH_SEGMENTS = ("/snapshot",)

WEB_DENIED_PATHS = {
    "/memory/global",
    "/settings/api_key",
    "/settings/budget",
    "/settings/budget/status",
    "/settings/image_model",
    "/settings/max_subtasks",
    "/settings/multi_agent_roles",
    "/settings/role_models",
    "/settings/tavily_key",
}


def load_deployment_profile(value: str | None = None) -> DeploymentProfile:
    raw = value if value is not None else getenv("TRITON_DEPLOYMENT_PROFILE", "desktop")
    try:
        return DeploymentProfile(raw.lower())
    except ValueError as exc:
        choices = ", ".join(profile.value for profile in DeploymentProfile)
        raise ValueError(
            f"invalid Triton deployment profile '{raw}'; expected one of: {choices}"
        ) from exc


def tool_is_allowed(profile: DeploymentProfile, tool_name: str) -> bool:
    return profile is DeploymentProfile.DESKTOP or tool_name in WEB_TOOL_NAMES


def path_is_allowed(profile: DeploymentProfile, path: str) -> bool:
    if profile is DeploymentProfile.DESKTOP:
        return True
    if path in WEB_DENIED_PATHS or any(segment in path for segment in WEB_DENIED_PATH_SEGMENTS):
        return False
    return not path.startswith(WEB_DENIED_PATH_PREFIXES)


def project_is_allowed(profile: DeploymentProfile, project_id: str | None) -> bool:
    return profile is DeploymentProfile.DESKTOP or project_id is None


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
