from dataclasses import dataclass
from os import getenv

import requests


@dataclass(frozen=True)
class RemoteWorkspaceConfig:
    base_url: str
    token: str


class RemoteWorkspaceError(RuntimeError):
    pass


def load_remote_workspace_config() -> RemoteWorkspaceConfig | None:
    token = getenv("TRITON_WORKSPACE_TOKEN", "")
    if not token:
        return None
    return RemoteWorkspaceConfig(
        base_url=getenv("TRITON_WORKSPACE_BASE_URL", "http://workspace:8001").rstrip("/"),
        token=token,
    )


def create_remote_workspace(config: RemoteWorkspaceConfig, workspace_id: str) -> None:
    try:
        response = requests.post(
            f"{config.base_url}/workspaces",
            headers={"X-Triton-Workspace-Token": config.token},
            json={"workspace_id": workspace_id},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if response.status_code == 409:
        raise RemoteWorkspaceError("workspace already exists")
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
