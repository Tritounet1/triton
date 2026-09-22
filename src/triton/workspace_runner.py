import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

WORKSPACE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
WORKSPACES_DIR = Path(os.getenv("TRITON_WORKSPACES_DIR", "/workspaces"))
WORKSPACE_TOKEN = os.getenv("TRITON_WORKSPACE_TOKEN", "")
TASKS_DIR = WORKSPACES_DIR / ".tasks"
MAX_CONCURRENT_TASKS = 5

app = FastAPI(title="Triton Workspace Runner", docs_url=None, redoc_url=None)


class WorkspaceCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=64)


class WorkspaceToolRequest(BaseModel):
    name: str
    args: dict[str, object]


class WorkspaceTaskRequest(BaseModel):
    session_id: str
    command: str = Field(min_length=1)
    name: str = ""
    directory: str = "."


def _require_token(token: str | None) -> None:
    if not WORKSPACE_TOKEN or token != WORKSPACE_TOKEN:
        raise HTTPException(401, "workspace authentication failed")


def _workspace_path(workspace_id: str) -> Path:
    if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise HTTPException(400, "invalid workspace id")
    return WORKSPACES_DIR / workspace_id


def _workspace_file(workspace_id: str, raw_path: str) -> Path:
    workspace = _workspace_path(workspace_id).resolve()
    target = (workspace / raw_path).resolve()
    if not target.is_relative_to(workspace):
        raise HTTPException(403, "path resolves outside the workspace")
    return target


def _tool_path(workspace_id: str, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("a non-empty path is required")
    return _workspace_file(workspace_id, value)


def _task_file(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _load_task(task_id: str) -> dict[str, object] | None:
    try:
        return json.loads(_task_file(task_id).read_text())
    except (OSError, ValueError):
        return None


def _save_task(task: dict[str, object]) -> None:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    _task_file(str(task["id"])).write_text(json.dumps(task))


def _refresh_task(task: dict[str, object]) -> dict[str, object]:
    if task["status"] != "running":
        return task
    pid = task.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            task["status"] = "exited"
            _save_task(task)
    return task


def _run_tool(workspace_id: str, name: str, args: dict[str, object]) -> str:
    if name == "read_file":
        return _tool_path(workspace_id, args.get("path")).read_text()
    if name == "list_files":
        directory = _tool_path(workspace_id, args.get("directory", "."))
        entries = sorted(directory.iterdir())
        result = "\n".join(f"{'d' if entry.is_dir() else 'f'} {entry.name}" for entry in entries)
        return result or "(empty directory)"
    if name == "write_file":
        path = _tool_path(workspace_id, args.get("path"))
        content = args.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"file {args['path']} written ({len(content)} characters)"
    if name == "delete_file":
        path = _tool_path(workspace_id, args.get("path"))
        if path.is_dir():
            raise ValueError("path is a directory, not a file")
        path.unlink()
        return f"file {args['path']} deleted"
    if name == "move_file":
        source = _tool_path(workspace_id, args.get("source"))
        destination = _tool_path(workspace_id, args.get("destination"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        return f"moved {args['source']} to {args['destination']}"
    if name == "edit_file":
        edits = args.get("edits")
        if not isinstance(edits, list) or not edits:
            raise ValueError("no edits provided")
        prepared: dict[Path, list[dict[str, object]]] = {}
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError("each edit must be an object")
            path = _tool_path(workspace_id, edit.get("path"))
            old_string = edit.get("old_string")
            new_string = edit.get("new_string")
            if not isinstance(old_string, str) or not isinstance(new_string, str):
                raise ValueError("each edit needs old_string and new_string")
            prepared.setdefault(path, []).append(edit)
        results: list[str] = []
        for path, edits_for_path in prepared.items():
            content = path.read_text()
            for edit in edits_for_path:
                old_string = cast(str, edit["old_string"])
                new_string = cast(str, edit["new_string"])
                count = content.count(old_string)
                if count == 0:
                    raise ValueError(f"old_string not found in {edit['path']}")
                if count > 1 and not bool(edit.get("replace_all")):
                    raise ValueError(f"old_string matches {count} times in {edit['path']}")
                content = content.replace(
                    old_string, new_string, -1 if edit.get("replace_all") else 1
                )
            path.write_text(content)
            results.append(
                f"{path.relative_to(_workspace_path(workspace_id))}: "
                f"{len(edits_for_path)} edit(s) applied"
            )
        return "\n".join(results)
    if name == "run_shell":
        command = args.get("command")
        if not isinstance(command, str) or not command:
            raise ValueError("a command is required")
        directory = _tool_path(workspace_id, args.get("directory", "."))
        result = subprocess.run(
            command,
            shell=True,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 30_000:
            output = f"{output[:30_000]}\n(truncated)"
        return output or f"(no output, exit code {result.returncode})"
    raise ValueError("unsupported workspace tool")


def _tree(directory: Path, workspace: Path, budget: list[int]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for child in sorted(directory.iterdir(), key=lambda path: (path.is_file(), path.name.lower())):
        if budget[0] <= 0:
            break
        if child.is_symlink() or child.name in {".git", "node_modules", ".venv"}:
            continue
        budget[0] -= 1
        relative_path = str(child.relative_to(workspace))
        if child.is_dir():
            entries.append(
                {
                    "name": child.name,
                    "path": relative_path,
                    "is_dir": True,
                    "children": _tree(child, workspace, budget),
                }
            )
        else:
            entries.append({"name": child.name, "path": relative_path, "is_dir": False})
    return entries


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/workspaces")
def create_workspace(
    body: WorkspaceCreateRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, str]:
    _require_token(x_triton_workspace_token)
    workspace = _workspace_path(body.workspace_id)
    if workspace.exists():
        raise HTTPException(409, "workspace already exists")
    workspace.mkdir(parents=True)
    return {"id": body.workspace_id}


@app.delete("/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _require_token(x_triton_workspace_token)
    workspace = _workspace_path(workspace_id)
    if not workspace.is_dir():
        raise HTTPException(404, "workspace not found")
    shutil.rmtree(workspace)
    return {"ok": True}


@app.get("/workspaces/{workspace_id}/tree")
def workspace_tree(
    workspace_id: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, object]:
    _require_token(x_triton_workspace_token)
    workspace = _workspace_path(workspace_id)
    if not workspace.is_dir():
        raise HTTPException(404, "workspace not found")
    budget = [2000]
    return {"tree": _tree(workspace, workspace, budget), "truncated": budget[0] <= 0}


@app.get("/workspaces/{workspace_id}/file")
def workspace_file(
    workspace_id: str,
    path: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> FileResponse:
    _require_token(x_triton_workspace_token)
    target = _workspace_file(workspace_id, path)
    if not target.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(target)


@app.post("/workspaces/{workspace_id}/tools")
def workspace_tool(
    workspace_id: str,
    body: WorkspaceToolRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, str]:
    _require_token(x_triton_workspace_token)
    if not _workspace_path(workspace_id).is_dir():
        raise HTTPException(404, "workspace not found")
    try:
        return {"result": _run_tool(workspace_id, body.name, body.args)}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"result": f"error: {exc}"}


def _running_task_count() -> int:
    return sum(
        1
        for path in TASKS_DIR.glob("*.json")
        if (task := _load_task(path.stem)) and _refresh_task(task)["status"] == "running"
    )


@app.post("/workspaces/{workspace_id}/tasks")
def start_task(
    workspace_id: str,
    body: WorkspaceTaskRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, object]:
    _require_token(x_triton_workspace_token)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    if _running_task_count() >= MAX_CONCURRENT_TASKS:
        raise HTTPException(429, f"{MAX_CONCURRENT_TASKS} background tasks are already running")
    directory = _tool_path(workspace_id, body.directory)
    task_id = uuid.uuid4().hex[:12]
    log_path = TASKS_DIR / f"{task_id}.log"
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            body.command,
            shell=True,
            cwd=directory,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    task: dict[str, object] = {
        "id": task_id,
        "workspace_id": workspace_id,
        "session_id": body.session_id,
        "name": body.name or body.command,
        "command": body.command,
        "directory": str(directory.relative_to(_workspace_path(workspace_id))),
        "status": "running",
        "pid": process.pid,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _save_task(task)
    return task


@app.get("/workspaces/{workspace_id}/tasks")
def list_tasks(
    workspace_id: str,
    session_id: str | None = None,
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[dict[str, object]]:
    _require_token(x_triton_workspace_token)
    tasks = [
        _refresh_task(task) for path in TASKS_DIR.glob("*.json") if (task := _load_task(path.stem))
    ]
    return [
        task
        for task in tasks
        if task["workspace_id"] == workspace_id
        and (not session_id or task["session_id"] == session_id)
    ]


def _resolve_task(workspace_id: str, task_id: str) -> dict[str, object]:
    task = _load_task(task_id)
    if task is None or task.get("workspace_id") != workspace_id:
        raise HTTPException(404, "task not found")
    return _refresh_task(task)


@app.get("/workspaces/{workspace_id}/tasks/{task_id}")
def get_task(
    workspace_id: str,
    task_id: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, object]:
    _require_token(x_triton_workspace_token)
    task = _resolve_task(workspace_id, task_id)
    log_path = TASKS_DIR / f"{task_id}.log"
    return {
        **task,
        "logs": log_path.read_text(errors="replace")[-524288:] if log_path.exists() else "",
    }


@app.post("/workspaces/{workspace_id}/tasks/{task_id}/stop")
def stop_task(
    workspace_id: str,
    task_id: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, object]:
    _require_token(x_triton_workspace_token)
    task = _resolve_task(workspace_id, task_id)
    pid = task.get("pid")
    if task["status"] == "running" and isinstance(pid, int):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
        task["status"] = "stopped"
        _save_task(task)
    return task


@app.delete("/workspaces/{workspace_id}/tasks/{task_id}")
def delete_task(
    workspace_id: str,
    task_id: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _require_token(x_triton_workspace_token)
    task = _resolve_task(workspace_id, task_id)
    if task["status"] == "running":
        raise HTTPException(409, "task is still running, stop it before deleting it")
    _task_file(task_id).unlink(missing_ok=True)
    (TASKS_DIR / f"{task_id}.log").unlink(missing_ok=True)
    return {"deleted": True}
