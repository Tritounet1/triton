from collections.abc import Callable
from dataclasses import dataclass

from triton import mcp_client
from triton.deployment import WEB_TOOL_NAMES
from triton.remote_workspaces import RemoteWorkspaceConfig, RemoteWorkspaceError
from triton.tools import Tool

BACKGROUND_TASK_TOOL_NAMES = frozenset(
    {"start_background_task", "stop_background_task", "list_background_tasks"}
)
SUBAGENT_DISPATCH_TOOL_NAMES = frozenset({"dispatch_subagent", "check_subagent"})

LocalInvoker = Callable[[Tool, str, dict[str, object], str], str]
RemoteInvoker = Callable[[RemoteWorkspaceConfig, str, str, dict[str, object]], str]
StartTask = Callable[[RemoteWorkspaceConfig, str, str, str, str, str], dict[str, object]]
StopTask = Callable[[RemoteWorkspaceConfig, str, str], dict[str, object]]
ListTasks = Callable[[RemoteWorkspaceConfig, str, str], list[dict[str, object]]]


@dataclass(frozen=True)
class ToolExecutor:
    config: RemoteWorkspaceConfig | None
    local_invoke: LocalInvoker
    remote_invoke: RemoteInvoker
    remote_mcp_invoke: RemoteInvoker
    start_task: StartTask
    stop_task: StopTask
    list_tasks: ListTasks

    def invoke(
        self,
        tool: Tool,
        name: str,
        args: dict[str, object],
        session_id: str,
        workspace_id: str | None,
    ) -> str:
        if workspace_id is None or name in SUBAGENT_DISPATCH_TOOL_NAMES or name in WEB_TOOL_NAMES:
            return self.local_invoke(tool, name, args, session_id)
        if self.config is None:
            return "error: remote workspaces are not configured"
        try:
            if name.startswith(mcp_client.MCP_PREFIX):
                return self.remote_mcp_invoke(self.config, workspace_id, name, args)
            if name in BACKGROUND_TASK_TOOL_NAMES:
                return self._background_task_result(workspace_id, session_id, name, args)
            return self.remote_invoke(self.config, workspace_id, name, args)
        except RemoteWorkspaceError as exc:
            return f"error: {exc}"

    def _background_task_result(
        self, workspace_id: str, session_id: str, name: str, args: dict[str, object]
    ) -> str:
        assert self.config is not None
        if name == "start_background_task":
            command = args.get("command")
            if not isinstance(command, str) or not command:
                return "error: start_background_task needs a command"
            task_name = args.get("name")
            directory = args.get("directory")
            task = self.start_task(
                self.config,
                workspace_id,
                session_id,
                command,
                task_name if isinstance(task_name, str) else "",
                directory if isinstance(directory, str) else "",
            )
            return (
                f"Background task started (id={task['id']}, name={task['name']!r}) in "
                f"{task['directory']}. It keeps running after this call returns - it doesn't "
                "block the conversation. Check its status with list_background_tasks, and stop "
                "it with stop_background_task when you're done with it. The user can also see "
                "it, read its live output, and stop it from the app."
            )
        if name == "stop_background_task":
            task_id = args.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                return "error: stop_background_task needs a task_id"
            task = self.stop_task(self.config, workspace_id, task_id)
            if task["status"] == "stopped":
                return f"task {task_id} stopped"
            return f"{task['status']}: task is not running"
        tasks = self.list_tasks(self.config, workspace_id, session_id)
        if not tasks:
            return "(no background tasks in this conversation)"
        return "\n".join(
            f"{task['id']} [{task['status']}] {task['name']} (directory={task['directory']})"
            for task in tasks
        )
