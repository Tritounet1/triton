from dataclasses import dataclass
from hashlib import sha256
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


def mcp_session_workspace_id(session_id: str) -> str:
    return f"mcp-session-{sha256(session_id.encode()).hexdigest()[:24]}"


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
        "start_background_task": ("directory",),
        "grep": ("directory",),
        "glob": ("directory",),
        "git_status": ("directory",),
        "git_diff": ("directory",),
        "git_commit": ("directory",),
        "git_log": ("directory",),
        "git_branch": ("directory",),
        "git_checkout": ("directory",),
        "git_push": ("directory",),
        "run_tests": ("directory",),
        "run_code": ("directory",),
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


def ensure_remote_mcp_session_workspace(config: RemoteWorkspaceConfig, session_id: str) -> str:
    workspace_id = mcp_session_workspace_id(session_id)
    try:
        create_remote_workspace(config, workspace_id)
    except RemoteWorkspaceError as exc:
        if str(exc) != "workspace already exists":
            raise
    return workspace_id


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


def list_remote_mcp_servers(config: RemoteWorkspaceConfig) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], _request(config, "/mcp/servers").json())


def add_remote_mcp_server(
    config: RemoteWorkspaceConfig, server: dict[str, object]
) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], _post(config, "/mcp/servers", server).json())


def toggle_remote_mcp_server(
    config: RemoteWorkspaceConfig, name: str, enabled: bool
) -> list[dict[str, object]]:
    try:
        response = requests.put(
            f"{config.base_url}/mcp/servers/{name}",
            headers={"X-Triton-Workspace-Token": config.token},
            json={"enabled": enabled},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    return cast(list[dict[str, object]], response.json())


def update_remote_mcp_server(
    config: RemoteWorkspaceConfig, name: str, server: dict[str, object]
) -> list[dict[str, object]]:
    try:
        response = requests.patch(
            f"{config.base_url}/mcp/servers/{name}",
            headers={"X-Triton-Workspace-Token": config.token},
            json=cast(dict[str, Any], server),
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    return cast(list[dict[str, object]], response.json())


def delete_remote_mcp_server(config: RemoteWorkspaceConfig, name: str) -> list[dict[str, object]]:
    try:
        response = requests.delete(
            f"{config.base_url}/mcp/servers/{name}",
            headers={"X-Triton-Workspace-Token": config.token},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    return cast(list[dict[str, object]], response.json())


def list_remote_mcp_tools(config: RemoteWorkspaceConfig) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], _request(config, "/mcp/tools").json())


def invoke_remote_mcp_tool(
    config: RemoteWorkspaceConfig,
    workspace_id: str,
    name: str,
    args: dict[str, object],
) -> str:
    try:
        response = requests.post(
            f"{config.base_url}/workspaces/{workspace_id}/mcp/{name}",
            headers={"X-Triton-Workspace-Token": config.token},
            json=cast(dict[str, Any], {"name": name, "args": args}),
            timeout=70,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    result = response.json().get("result")
    if not isinstance(result, str):
        raise RemoteWorkspaceError("workspace runner returned an invalid response")
    return result


def _post(
    config: RemoteWorkspaceConfig, path: str, json_body: dict[str, object] | None = None
) -> requests.Response:
    try:
        response = requests.post(
            f"{config.base_url}{path}",
            headers={"X-Triton-Workspace-Token": config.token},
            json=cast(dict[str, Any], json_body),
            timeout=15,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")
    return response


def start_remote_task(
    config: RemoteWorkspaceConfig,
    workspace_id: str,
    session_id: str,
    command: str,
    name: str = "",
    directory: str = "",
) -> dict[str, object]:
    response = _post(
        config,
        f"/workspaces/{workspace_id}/tasks",
        {
            "session_id": session_id,
            "command": command,
            "name": name,
            "directory": directory or ".",
        },
    )
    return cast(dict[str, object], response.json())


def list_remote_tasks(
    config: RemoteWorkspaceConfig, workspace_id: str, session_id: str | None = None
) -> list[dict[str, object]]:
    params = {"session_id": session_id} if session_id else None
    response = _request(config, f"/workspaces/{workspace_id}/tasks", params)
    return cast(list[dict[str, object]], response.json())


def get_remote_task(
    config: RemoteWorkspaceConfig, workspace_id: str, task_id: str
) -> dict[str, object]:
    response = _request(config, f"/workspaces/{workspace_id}/tasks/{task_id}")
    return cast(dict[str, object], response.json())


def stop_remote_task(
    config: RemoteWorkspaceConfig, workspace_id: str, task_id: str
) -> dict[str, object]:
    response = _post(config, f"/workspaces/{workspace_id}/tasks/{task_id}/stop")
    return cast(dict[str, object], response.json())


def delete_remote_task(config: RemoteWorkspaceConfig, workspace_id: str, task_id: str) -> None:
    try:
        response = requests.delete(
            f"{config.base_url}/workspaces/{workspace_id}/tasks/{task_id}",
            headers={"X-Triton-Workspace-Token": config.token},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RemoteWorkspaceError("workspace runner is unavailable") from exc
    if not response.ok:
        raise RemoteWorkspaceError("workspace runner rejected the request")


def list_remote_snapshots(
    config: RemoteWorkspaceConfig, workspace_id: str, session_id: str
) -> list[dict[str, object]]:
    response = _request(config, f"/workspaces/{workspace_id}/snapshots", {"session_id": session_id})
    return cast(list[dict[str, object]], response.json())


def ensure_remote_snapshot(
    config: RemoteWorkspaceConfig, workspace_id: str, session_id: str, turn_index: int
) -> bool:
    response = _post(
        config,
        f"/workspaces/{workspace_id}/snapshots",
        {"session_id": session_id, "turn_index": turn_index},
    )
    return bool(cast(dict[str, object], response.json()).get("taken"))


def restore_remote_snapshot(
    config: RemoteWorkspaceConfig, workspace_id: str, session_id: str, turn_index: int
) -> None:
    _post(
        config,
        f"/workspaces/{workspace_id}/snapshots/restore",
        {"session_id": session_id, "turn_index": turn_index},
    )


def purge_remote_maintenance(
    config: RemoteWorkspaceConfig, keep_workspace_ids: list[str]
) -> dict[str, int]:
    response = _post(config, "/maintenance/purge", {"keep_workspace_ids": keep_workspace_ids})
    return cast(dict[str, int], response.json())
