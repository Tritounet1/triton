import contextlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from triton import mcp_client
from triton.tools import TOOLS_REGISTRY, invoke_tool

WORKSPACE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
MCP_SERVER_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
_SNAPSHOT_SESSION_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_SKIP_DIR_NAMES = {".git", "node_modules", ".venv"}
WORKSPACES_DIR = Path(os.getenv("TRITON_WORKSPACES_DIR", "/workspaces"))
WORKSPACE_TOKEN = os.getenv("TRITON_WORKSPACE_TOKEN", "")
TASKS_DIR = WORKSPACES_DIR / ".tasks"
SNAPSHOTS_DIR = WORKSPACES_DIR / ".snapshots"
MAX_CONCURRENT_TASKS = 5
MAX_CONCURRENT_TASKS_PER_WORKSPACE = 3
MAX_WORKSPACE_BYTES = int(os.getenv("TRITON_WORKSPACE_MAX_BYTES", str(2 * 1024**3)))
SNAPSHOT_MAX_AGE_DAYS = int(os.getenv("TRITON_SNAPSHOT_MAX_AGE_DAYS", "30"))


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


class WorkspaceSnapshotRequest(BaseModel):
    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=1)


class MCPServerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=MCP_SERVER_NAME_PATTERN)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPServerToggleRequest(BaseModel):
    enabled: bool


@asynccontextmanager
async def lifespan(_: FastAPI):
    mcp_client.manager.connect_all_enabled()
    try:
        yield
    finally:
        mcp_client.manager.disconnect_all()


app = FastAPI(title="Triton Workspace Runner", docs_url=None, redoc_url=None, lifespan=lifespan)


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


def _skipped(path: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def _tool_path(workspace_id: str, value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("a non-empty path is required")
    return _workspace_file(workspace_id, value)


def _snapshot_dir(workspace_id: str, session_id: str, turn_index: int) -> Path:
    if not _SNAPSHOT_SESSION_PATTERN.fullmatch(session_id):
        raise HTTPException(400, "invalid session id")
    return SNAPSHOTS_DIR / workspace_id / f"{session_id}_{turn_index}"


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


def _project_storage_size_bytes(workspace_id: str) -> int:
    locations = (_workspace_path(workspace_id), SNAPSHOTS_DIR / workspace_id)
    return sum(
        path.stat().st_size
        for location in locations
        if location.is_dir()
        for path in location.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _directory_size_bytes(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(
        path.stat().st_size
        for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def _quota_error() -> ValueError:
    return ValueError(f"workspace would exceed its {MAX_WORKSPACE_BYTES} byte quota")


def _ensure_project_capacity(workspace_id: str, additional_bytes: int = 0) -> None:
    if _project_storage_size_bytes(workspace_id) + additional_bytes > MAX_WORKSPACE_BYTES:
        raise _quota_error()


def _subprocess_quota_limit(workspace_id: str) -> int:
    return max(MAX_WORKSPACE_BYTES - _project_storage_size_bytes(workspace_id), 0)


def _apply_subprocess_quota(limit: int) -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def _subprocess_quota_preexec(workspace_id: str) -> Callable[[], object]:
    return lambda: _apply_subprocess_quota(_subprocess_quota_limit(workspace_id))


def _refresh_task(task: dict[str, object]) -> dict[str, object]:
    if task["status"] != "running":
        return task
    workspace_id = task.get("workspace_id")
    exceeds_quota = isinstance(workspace_id, str) and (
        _project_storage_size_bytes(workspace_id) > MAX_WORKSPACE_BYTES
    )
    if exceeds_quota:
        pid = task.get("pid")
        if isinstance(pid, int):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGTERM)
        task["status"] = "stopped"
        task["error"] = f"workspace exceeded its {MAX_WORKSPACE_BYTES} byte quota"
        _save_task(task)
        return task
    pid = task.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            task["status"] = "exited"
            _save_task(task)
    return task


def _run_git(args: list[str], directory: Path, timeout: float = 15) -> str:
    result = subprocess.run(
        ["git", *args], cwd=directory, capture_output=True, text=True, timeout=timeout
    )
    output = (result.stdout + result.stderr).strip()
    return output or "(no output)"


def _python_interpreter() -> list[str]:
    return [sys.executable]


def _language_interpreter(language: str) -> list[str] | None:
    lang = {"py": "python", "js": "javascript", "node": "javascript"}.get(language, language)
    if lang == "python":
        return _python_interpreter()
    if lang == "javascript":
        found = shutil.which("node")
        return [found] if found else None
    return None


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
        existing_size = path.stat().st_size if path.is_file() else 0
        _ensure_project_capacity(workspace_id, len(content.encode()) - existing_size)
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
        updated: dict[Path, tuple[str, int]] = {}
        additional_bytes = 0
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
            updated[path] = (content, len(edits_for_path))
            additional_bytes += len(content.encode()) - path.stat().st_size
        _ensure_project_capacity(workspace_id, additional_bytes)
        results: list[str] = []
        for path, (content, edit_count) in updated.items():
            path.write_text(content)
            results.append(
                f"{path.relative_to(_workspace_path(workspace_id))}: {edit_count} edit(s) applied"
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
            preexec_fn=_subprocess_quota_preexec(workspace_id),
        )
        if _project_storage_size_bytes(workspace_id) > MAX_WORKSPACE_BYTES:
            return f"error: workspace exceeded its {MAX_WORKSPACE_BYTES} byte quota"
        output = (result.stdout + result.stderr).strip()
        if len(output) > 30_000:
            output = f"{output[:30_000]}\n(truncated)"
        return output or f"(no output, exit code {result.returncode})"
    if name == "grep":
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("a pattern is required")
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"error: invalid regex ({e})"
        directory = _tool_path(workspace_id, args.get("directory", "."))
        file_glob = args.get("file_glob") or "**/*"
        workspace = _workspace_path(workspace_id)
        matches: list[str] = []
        for path in sorted(directory.glob(cast(str, file_glob))):
            if not path.is_file() or _skipped(path):
                continue
            try:
                text = path.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(workspace)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{relative}:{lineno}:{line.strip()}")
                    if len(matches) >= 200:
                        return "\n".join(matches) + "\n(truncated at 200 matches)"
        return "\n".join(matches) if matches else "(no matches)"
    if name == "glob":
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("a pattern is required")
        directory = _tool_path(workspace_id, args.get("directory", "."))
        workspace = _workspace_path(workspace_id)
        results = sorted(
            str(p.relative_to(workspace)) for p in directory.glob(pattern) if not _skipped(p)
        )
        if not results:
            return "(no matches)"
        if len(results) > 500:
            return "\n".join(results[:500]) + "\n(truncated at 500 results)"
        return "\n".join(results)
    if name in {
        "git_status",
        "git_diff",
        "git_commit",
        "git_log",
        "git_branch",
        "git_checkout",
        "git_push",
    }:
        directory = _tool_path(workspace_id, args.get("directory", "."))
        if name == "git_status":
            return _run_git(["status", "--short", "--branch"], directory)
        if name == "git_diff":
            path = args.get("path")
            return _run_git(["diff", *([cast(str, path)] if path else [])], directory)
        if name == "git_commit":
            message = args.get("message")
            if not isinstance(message, str) or not message:
                raise ValueError("a commit message is required")
            paths = args.get("paths")
            add_args = paths if isinstance(paths, list) and paths else ["-A"]
            add_result = _run_git(["add", *cast("list[str]", add_args)], directory)
            if add_result.startswith("error:"):
                return add_result
            return _run_git(["commit", "-m", message], directory)
        if name == "git_log":
            max_count = args.get("max_count", 20)
            path = args.get("path")
            log_args = ["log", "--oneline", f"-n{int(cast(int, max_count))}"]
            if path:
                log_args += ["--", cast(str, path)]
            return _run_git(log_args, directory)
        if name == "git_branch":
            return _run_git(["branch", "--list"], directory)
        if name == "git_checkout":
            branch = args.get("branch")
            if not isinstance(branch, str) or not branch:
                raise ValueError("a branch is required")
            checkout_args = (
                ["checkout", "-b", branch] if args.get("create") else ["checkout", branch]
            )
            return _run_git(checkout_args, directory)
        remote = cast(str, args.get("remote") or "origin")
        branch = args.get("branch")
        push_args = ["push"]
        if args.get("set_upstream"):
            push_args.append("-u")
        push_args.append(remote)
        if branch:
            push_args.append(cast(str, branch))
        elif args.get("set_upstream"):
            push_args.append("HEAD")
        return _run_git(push_args, directory, timeout=60)
    if name in {"run_tests", "run_code"}:
        directory = _tool_path(workspace_id, args.get("directory", "."))
        if name == "run_tests":
            path = args.get("path")
            test_args = ["pytest", "-q", *([path] if path else [])]
            try:
                result = subprocess.run(
                    test_args,
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    preexec_fn=_subprocess_quota_preexec(workspace_id),
                )
            except OSError as e:
                return f"error: could not run tests ({e})"
            if _project_storage_size_bytes(workspace_id) > MAX_WORKSPACE_BYTES:
                return f"error: workspace exceeded its {MAX_WORKSPACE_BYTES} byte quota"
            output = (result.stdout + result.stderr).strip()
            return output or f"(no output, exit code {result.returncode})"
        code = args.get("code")
        if not isinstance(code, str) or not code:
            raise ValueError("code is required")
        language = cast(str, args.get("language") or "python")
        interpreter = _language_interpreter(language)
        if interpreter is None:
            return f"error: no {language} interpreter found on this system"
        suffix = {"python": ".py", "javascript": ".js"}.get(
            {"py": "python", "js": "javascript", "node": "javascript"}.get(language, language),
            "",
        )
        if not suffix:
            return f"error: unsupported language '{language}' - use 'python' or 'javascript'"
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(code)
            script_path = f.name
        try:
            try:
                result = subprocess.run(
                    [*interpreter, script_path],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    preexec_fn=_subprocess_quota_preexec(workspace_id),
                )
            except OSError as e:
                return f"error: could not run {language} code ({e})"
        finally:
            Path(script_path).unlink(missing_ok=True)
        if _project_storage_size_bytes(workspace_id) > MAX_WORKSPACE_BYTES:
            return f"error: workspace exceeded its {MAX_WORKSPACE_BYTES} byte quota"
        output = (result.stdout + result.stderr).strip()
        if len(output) > 8000:
            output = output[:8000] + "\n(truncated)"
        return output or f"(no output, exit code {result.returncode})"
    raise ValueError("unsupported workspace tool")


def _tree(directory: Path, workspace: Path, budget: list[int]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for child in sorted(directory.iterdir(), key=lambda path: (path.is_file(), path.name.lower())):
        if budget[0] <= 0:
            break
        if child.is_symlink() or child.name in _SKIP_DIR_NAMES:
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
    shutil.rmtree(SNAPSHOTS_DIR / workspace_id, ignore_errors=True)
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


@app.get("/mcp/servers")
def list_mcp_servers(
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[mcp_client.ServerStatus]:
    _require_token(x_triton_workspace_token)
    return mcp_client.manager.status()


@app.post("/mcp/servers")
def add_mcp_server(
    body: MCPServerCreateRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[mcp_client.ServerStatus]:
    _require_token(x_triton_workspace_token)
    config = mcp_client.MCPServerConfig(
        name=body.name,
        command=body.command,
        args=body.args,
        env=body.env,
        enabled=body.enabled,
    )
    try:
        mcp_client.manager.add_server(config)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return mcp_client.manager.status()


@app.put("/mcp/servers/{name}")
def toggle_mcp_server(
    name: str,
    body: MCPServerToggleRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[mcp_client.ServerStatus]:
    _require_token(x_triton_workspace_token)
    try:
        mcp_client.manager.set_enabled(name, body.enabled)
    except KeyError as exc:
        raise HTTPException(404, "MCP server not found") from exc
    return mcp_client.manager.status()


@app.delete("/mcp/servers/{name}")
def remove_mcp_server(
    name: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[mcp_client.ServerStatus]:
    _require_token(x_triton_workspace_token)
    mcp_client.manager.remove_server(name)
    return mcp_client.manager.status()


@app.get("/mcp/tools")
def list_mcp_tools(
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[dict[str, object]]:
    _require_token(x_triton_workspace_token)
    return [
        cast(dict[str, object], tool.schema)
        for name, tool in TOOLS_REGISTRY.items()
        if name.startswith(mcp_client.MCP_PREFIX)
    ]


@app.post("/workspaces/{workspace_id}/mcp/{tool_name}")
def invoke_workspace_mcp_tool(
    workspace_id: str,
    tool_name: str,
    body: WorkspaceToolRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, str]:
    _require_token(x_triton_workspace_token)
    if not _workspace_path(workspace_id).is_dir():
        raise HTTPException(404, "workspace not found")
    if tool_name != body.name or not tool_name.startswith(mcp_client.MCP_PREFIX):
        raise HTTPException(400, "invalid MCP tool")
    tool = TOOLS_REGISTRY.get(tool_name)
    if tool is None:
        raise HTTPException(404, "MCP tool not found")
    return {"result": invoke_tool(tool, tool_name, body.args, session_id="remote-workspace")}


def _running_task_count(workspace_id: str | None = None) -> int:
    return sum(
        1
        for path in TASKS_DIR.glob("*.json")
        if (task := _load_task(path.stem))
        and (workspace_id is None or task.get("workspace_id") == workspace_id)
        and _refresh_task(task)["status"] == "running"
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
    if _running_task_count(workspace_id) >= MAX_CONCURRENT_TASKS_PER_WORKSPACE:
        raise HTTPException(
            429,
            f"{MAX_CONCURRENT_TASKS_PER_WORKSPACE} background tasks are already running "
            "in this project",
        )
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
            preexec_fn=_subprocess_quota_preexec(workspace_id),
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


@app.get("/workspaces/{workspace_id}/snapshots")
def list_workspace_snapshots(
    workspace_id: str,
    session_id: str,
    x_triton_workspace_token: str | None = Header(default=None),
) -> list[dict[str, object]]:
    _require_token(x_triton_workspace_token)
    if not _SNAPSHOT_SESSION_PATTERN.fullmatch(session_id):
        raise HTTPException(400, "invalid session id")
    base = SNAPSHOTS_DIR / workspace_id
    prefix = f"{session_id}_"
    points: list[dict[str, object]] = []
    if base.is_dir():
        for entry in base.iterdir():
            if not entry.is_dir() or not entry.name.startswith(prefix):
                continue
            raw_turn_index = entry.name.removeprefix(prefix)
            if not raw_turn_index.isdigit():
                continue
            meta_path = entry / "meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            points.append(
                {"turn_index": int(raw_turn_index), "created_at": meta.get("created_at", "")}
            )
    points.sort(key=lambda p: cast(int, p["turn_index"]))
    return points


@app.post("/workspaces/{workspace_id}/snapshots")
def ensure_workspace_snapshot(
    workspace_id: str,
    body: WorkspaceSnapshotRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _require_token(x_triton_workspace_token)
    workspace = _workspace_path(workspace_id)
    if not workspace.is_dir():
        raise HTTPException(404, "workspace not found")
    target = _snapshot_dir(workspace_id, body.session_id, body.turn_index)
    if target.exists():
        return {"taken": False}
    snapshot_source_size = sum(
        path.stat().st_size
        for path in workspace.rglob("*")
        if path.is_file() and not path.is_symlink() and ".git" not in path.parts
    )
    if _project_storage_size_bytes(workspace_id) + snapshot_source_size > MAX_WORKSPACE_BYTES:
        raise HTTPException(413, f"workspace would exceed its {MAX_WORKSPACE_BYTES} byte quota")
    target.mkdir(parents=True)
    shutil.copytree(workspace, target / "files", ignore=shutil.ignore_patterns(".git"))
    (target / "meta.json").write_text(
        json.dumps({"created_at": datetime.now(UTC).isoformat(timespec="seconds")})
    )
    return {"taken": True}


@app.post("/workspaces/{workspace_id}/snapshots/restore")
def restore_workspace_snapshot(
    workspace_id: str,
    body: WorkspaceSnapshotRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _require_token(x_triton_workspace_token)
    workspace = _workspace_path(workspace_id)
    if not workspace.is_dir():
        raise HTTPException(404, "workspace not found")
    source = _snapshot_dir(workspace_id, body.session_id, body.turn_index) / "files"
    if not source.is_dir():
        raise HTTPException(404, "no snapshot for this session at that turn")
    source_size = _directory_size_bytes(source)
    current_size = _project_storage_size_bytes(workspace_id)
    workspace_size = _directory_size_bytes(workspace)
    if current_size - workspace_size + source_size > MAX_WORKSPACE_BYTES:
        raise HTTPException(413, f"workspace would exceed its {MAX_WORKSPACE_BYTES} byte quota")
    for child in workspace.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source.iterdir():
        destination = workspace / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)
    return {"restored": True}


class MaintenancePurgeRequest(BaseModel):
    keep_workspace_ids: list[str] = Field(default_factory=list)


def _purge_expired_snapshots() -> int:
    if not SNAPSHOTS_DIR.is_dir():
        return 0
    cutoff = datetime.now(UTC).timestamp() - SNAPSHOT_MAX_AGE_DAYS * 86400
    removed = 0
    for workspace_snapshots in SNAPSHOTS_DIR.iterdir():
        if not workspace_snapshots.is_dir():
            continue
        for entry in workspace_snapshots.iterdir():
            if not entry.is_dir():
                continue
            try:
                created_at = json.loads((entry / "meta.json").read_text())["created_at"]
                age_ok = datetime.fromisoformat(created_at).timestamp() >= cutoff
            except (OSError, ValueError, KeyError):
                age_ok = entry.stat().st_mtime >= cutoff
            if not age_ok:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
    return removed


@app.post("/maintenance/purge")
def purge_maintenance(
    body: MaintenancePurgeRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, int]:
    _require_token(x_triton_workspace_token)
    keep = set(body.keep_workspace_ids)
    orphaned_workspaces = 0
    if WORKSPACES_DIR.is_dir():
        for entry in WORKSPACES_DIR.iterdir():
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in keep:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            shutil.rmtree(SNAPSHOTS_DIR / entry.name, ignore_errors=True)
            orphaned_workspaces += 1
    return {
        "orphaned_workspaces_removed": orphaned_workspaces,
        "expired_snapshots_removed": _purge_expired_snapshots(),
    }
