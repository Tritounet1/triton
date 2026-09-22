from dataclasses import dataclass
from os import getenv
from pathlib import PurePosixPath
from typing import Any, cast

import requests


@dataclass(frozen=True)
class RemoteWorkspaceConfig:
    base_url: str
    token: str


class RemoteWorkspaceError(RuntimeError):
    pass


def _relative_workspace_path(workspace_id: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RemoteWorkspaceError("a workspace path is required")
    prefix = f"workspace://{workspace_id}"
    if value == prefix:
        return "."
    if value.startswith(f"{prefix}/"):
        return value.removeprefix(f"{prefix}/")
    if value.startswith("workspace://") or PurePosixPath(value).is_absolute():
        raise RemoteWorkspaceError("path belongs to a different workspace")
    return value


def normalize_remote_workspace_args(
    workspace_id: str, name: str, args: dict[str, object]
) -> dict[str, object]:
    normalized = dict(args)
    for key in {
        "read_file": ("path",),
        "list_files": ("directory",),
        "write_file": ("path",),
        "delete_file": ("path",),
        "move_file": ("source", "destination"),
        "run_shell": ("directory",),
    }.get(name, ()):
        if key in normalized:
            normalized[key] = _relative_workspace_path(workspace_id, normalized[key])
    if name == "edit_file":
        edits = normalized.get("edits")
        if isinstance(edits, list):
            normalized["edits"] = [
                {**edit, "path": _relative_workspace_path(workspace_id, edit.get("path"))}
                if isinstance(edit, dict)
                else edit
                for edit in edits
            ]
    return normalized


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


def delete_remote_workspace(config: RemoteWorkspaceConfig, workspace_id: str) -> None:
    try:
        response = requests.delete(
            f"{config.base_url}/workspaces/{workspace_id}",
            headers={"X-Triton-Workspace-Token": config.token},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if response.status_code == 404:
        return
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")


def _request(
    config: RemoteWorkspaceConfig,
    path: str,
    params: dict[str, str] | None = None,
) -> requests.Response:
    try:
        response = requests.get(
            f"{config.base_url}{path}",
            headers={"X-Triton-Workspace-Token": config.token},
            params=params,
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    return response


def remote_workspace_tree(config: RemoteWorkspaceConfig, workspace_id: str) -> dict[str, object]:
    return _request(config, f"/workspaces/{workspace_id}/tree").json()


def remote_workspace_file(
    config: RemoteWorkspaceConfig, workspace_id: str, path: str
) -> tuple[bytes, str]:
    response = _request(config, f"/workspaces/{workspace_id}/file", {"path": path})
    return response.content, response.headers.get("content-type", "application/octet-stream")


def invoke_remote_workspace_tool(
    config: RemoteWorkspaceConfig,
    workspace_id: str,
    name: str,
    args: dict[str, object],
) -> str:
    try:
        response = requests.post(
            f"{config.base_url}/workspaces/{workspace_id}/tools",
            headers={"X-Triton-Workspace-Token": config.token},
            json=cast(dict[str, Any], {"name": name, "args": args}),
            timeout=130,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, str):
        raise RemoteWorkspaceError("workspace runner returned an invalid response")
    return result
