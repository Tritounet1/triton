"""Background tasks: long-running processes (dev servers, watchers, ...)
started by the model via start_background_task, tracked here so the desktop
app can list them, tail their output, and stop them. Unlike subagents.py
this runs a real subprocess with real stdout, not another agentic loop.

Unlike subagents.py, this DOES survive a harness restart (manual or
uvicorn --reload): a spawned process outlives its parent once
start_new_session detaches it into its own session, so without this the
harness would simply lose track of it - the process keeps running, but the
app can no longer see it, read its output, or stop it. To make that
survivable:

- stdout/stderr are redirected straight to a log FILE on disk (never a pipe
  read by this process), so the child keeps writing normally regardless of
  whether the harness process that spawned it is still alive.
- Task metadata (id, command, pid, status, ...) is persisted to STATE_FILE
  on every change and reloaded at import time: a "running" task whose pid
  is still alive gets a watcher thread (polling os.kill(pid, 0), since it's
  no longer a child of this process and process.wait() wouldn't work), a
  "running" task whose pid is gone gets marked "exited" (its real exit code
  was lost along with the harness process that would have read it).
"""

import contextlib
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

# strips ANSI escape sequences (color codes, cursor movement) that most CLI
# tools (vite, pnpm, ...) emit even when stdout is piped rather than a real
# TTY: harmless in a real terminal, but rendered as raw garbled bytes in the
# plain <div> the desktop app uses to display logs. Applied when reading the
# log back (not when writing it), since output goes straight from the child
# process to the file with no line-by-line processing on our side.
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

STATE_DIR = Path(__file__).parent / "background_tasks_state"
STATE_FILE = STATE_DIR / "tasks.json"

TaskStatus = Literal["running", "exited", "error", "stopped"]

STOP_TIMEOUT_SECONDS = 5.0
# a task's log file is left to grow for as long as it runs (dev servers can
# run for hours); only the tail is ever read back for display, so this
# bounds response size/memory rather than disk usage.
MAX_DISPLAY_LOG_BYTES = 512 * 1024


@dataclass
class BackgroundTask:
    id: str
    session_id: str
    name: str
    command: str
    directory: str
    status: TaskStatus = "running"
    exit_code: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    pid: int | None = None
    # only set for a task spawned in this process's lifetime - None for one
    # reconstructed from disk after a restart, since it's no longer a child
    # of this process (see _watch_orphan vs _watch_child below).
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False, compare=False)


def _log_path(task_id: str) -> Path:
    return STATE_DIR / f"{task_id}.log"


def _persist_state() -> None:
    STATE_DIR.mkdir(exist_ok=True)
    entries = [
        {
            "id": t.id,
            "session_id": t.session_id,
            "name": t.name,
            "command": t.command,
            "directory": t.directory,
            "status": t.status,
            "exit_code": t.exit_code,
            "created_at": t.created_at,
            "pid": t.pid,
        }
        for t in TASKS.values()
    ]
    STATE_FILE.write_text(json.dumps(entries, indent=2))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # exists, just not ours to signal - still "alive" for our purposes
        return True
    return True


def _watch_child(task: BackgroundTask) -> None:
    """Waits on a process this run of the harness actually spawned."""
    assert task.process is not None
    task.process.wait()
    if task.status == "running":
        task.exit_code = task.process.returncode
        task.status = "exited" if task.exit_code == 0 else "error"
        _persist_state()


def _watch_orphan(task: BackgroundTask) -> None:
    """Waits on a process reconstructed from disk after a restart: it's no
    longer a child of this process (re-parented to init once its original
    parent exited), so process.wait() isn't available - poll for it to
    disappear instead."""
    assert task.pid is not None
    while _pid_alive(task.pid):
        time.sleep(2)
    if task.status == "running":
        # the process is gone, but since we didn't spawn it this time we
        # have no real exit code to report.
        task.status = "exited"
        _persist_state()


def _load_persisted_tasks() -> dict[str, BackgroundTask]:
    if not STATE_FILE.exists():
        return {}
    try:
        entries = json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}

    tasks: dict[str, BackgroundTask] = {}
    for e in entries:
        task = BackgroundTask(
            id=e["id"],
            session_id=e["session_id"],
            name=e["name"],
            command=e["command"],
            directory=e["directory"],
            status=e["status"],
            exit_code=e.get("exit_code"),
            created_at=e["created_at"],
            pid=e.get("pid"),
        )
        if task.status == "running":
            if task.pid is not None and _pid_alive(task.pid):
                threading.Thread(target=_watch_orphan, args=(task,), daemon=True).start()
            else:
                task.status = "exited"
        tasks[task.id] = task
    return tasks


TASKS: dict[str, BackgroundTask] = _load_persisted_tasks()


def start(session_id: str, command: str, name: str = "", directory: str = ".") -> str:
    """Starts `command` in the background and returns immediately. The
    process runs in its own process group (start_new_session) so stop() can
    kill an entire process tree, e.g. a wrapper script and the server it
    spawns, not just the immediate child - and so it survives this harness
    process exiting rather than being torn down with it."""
    label = name.strip() or command
    task_id = uuid.uuid4().hex[:8]
    STATE_DIR.mkdir(exist_ok=True)

    with _log_path(task_id).open("wb") as log_file:
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=directory,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as e:
            return f"error: could not start command ({e})"

    task = BackgroundTask(
        id=task_id,
        session_id=session_id,
        name=label,
        command=command,
        directory=directory,
        pid=process.pid,
        process=process,
    )
    TASKS[task.id] = task
    _persist_state()
    threading.Thread(target=_watch_child, args=(task,), daemon=True).start()
    return (
        f"Background task started (id={task.id}, name={label!r}) in {directory}. It keeps "
        "running after this call returns - it doesn't block the conversation. Check its "
        "status with list_background_tasks, and stop it with stop_background_task when "
        "you're done with it. The user can also see it, read its live output, and stop it "
        "from the app."
    )


def stop(task_id: str) -> str:
    task = TASKS.get(task_id)
    if task is None:
        return f"error: no background task with id {task_id}"
    if task.status != "running":
        return f"{task.status}: task is not running"

    if task.pid is not None:
        try:
            os.killpg(task.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            if task.process is not None:
                try:
                    task.process.wait(timeout=STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(task.pid, signal.SIGKILL)
            else:
                # reconstructed after a restart: no Popen handle to wait()
                # on, just give the process group a moment then escalate.
                time.sleep(STOP_TIMEOUT_SECONDS)
                if _pid_alive(task.pid):
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(task.pid, signal.SIGKILL)

    task.status = "stopped"
    _persist_state()
    return f"task {task_id} stopped"


def delete(task_id: str) -> str:
    task = TASKS.get(task_id)
    if task is None:
        return f"error: no background task with id {task_id}"
    if task.status == "running":
        return "error: task is still running, stop it before deleting it"

    del TASKS[task_id]
    _persist_state()
    _log_path(task_id).unlink(missing_ok=True)
    return f"task {task_id} deleted"


def get(task_id: str) -> BackgroundTask | None:
    return TASKS.get(task_id)


def list_tasks(session_id: str | None = None) -> list[BackgroundTask]:
    tasks = TASKS.values()
    if session_id:
        tasks = [t for t in tasks if t.session_id == session_id]
    return sorted(tasks, key=lambda t: t.created_at, reverse=True)


def summary(task: BackgroundTask) -> dict[str, object]:
    return {
        "id": task.id,
        "session_id": task.session_id,
        "name": task.name,
        "command": task.command,
        "directory": task.directory,
        "status": task.status,
        "exit_code": task.exit_code,
        "created_at": task.created_at,
    }


def _read_log(task: BackgroundTask) -> str:
    path = _log_path(task.id)
    if not path.exists():
        return ""
    data = path.read_bytes()
    if len(data) > MAX_DISPLAY_LOG_BYTES:
        data = data[-MAX_DISPLAY_LOG_BYTES:]
    return ANSI_ESCAPE_RE.sub("", data.decode("utf-8", errors="replace"))


def detail(task: BackgroundTask) -> dict[str, object]:
    return {**summary(task), "logs": _read_log(task)}
