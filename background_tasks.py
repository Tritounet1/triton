"""Background tasks: long-running processes (dev servers, watchers, ...)
started by the model via start_background_task, tracked here so the desktop
app can list them, tail their output, and stop them. Unlike subagents.py
this runs a real subprocess with real stdout, not another agentic loop.

Ephemeral like subagents.py: nothing here survives a server restart, and a
task isn't automatically killed when its conversation is deleted.
"""

import contextlib
import os
import signal
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

TaskStatus = Literal["running", "exited", "error", "stopped"]

MAX_LOG_LINES = 2000
STOP_TIMEOUT_SECONDS = 5.0


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
    process: subprocess.Popen[str] | None = field(default=None, repr=False, compare=False)
    log_lines: deque[str] = field(
        default_factory=lambda: deque(maxlen=MAX_LOG_LINES), repr=False, compare=False
    )


TASKS: dict[str, BackgroundTask] = {}
_log_lock = threading.Lock()


def _pump_output(task: BackgroundTask) -> None:
    assert task.process is not None and task.process.stdout is not None
    for line in task.process.stdout:
        with _log_lock:
            task.log_lines.append(line.rstrip("\n"))
    task.process.wait()
    if task.status == "running":
        task.exit_code = task.process.returncode
        task.status = "exited" if task.exit_code == 0 else "error"


def start(session_id: str, command: str, name: str = "", directory: str = ".") -> str:
    """Starts `command` in the background and returns immediately. The
    process runs in its own process group (start_new_session) so stop() can
    kill an entire process tree, e.g. a wrapper script and the server it
    spawns, not just the immediate child."""
    label = name.strip() or command
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except OSError as e:
        return f"error: could not start command ({e})"

    task = BackgroundTask(
        id=uuid.uuid4().hex[:8],
        session_id=session_id,
        name=label,
        command=command,
        directory=directory,
        process=process,
    )
    TASKS[task.id] = task
    threading.Thread(target=_pump_output, args=(task,), daemon=True).start()
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

    assert task.process is not None
    try:
        os.killpg(task.process.pid, signal.SIGTERM)
        task.process.wait(timeout=STOP_TIMEOUT_SECONDS)
    except ProcessLookupError:
        pass
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(task.process.pid, signal.SIGKILL)

    task.status = "stopped"
    return f"task {task_id} stopped"


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


def detail(task: BackgroundTask) -> dict[str, object]:
    with _log_lock:
        logs = "\n".join(task.log_lines)
    return {**summary(task), "logs": logs}
