"""Thin tool-schema wrappers around triton.agents.subagents and
triton.background_tasks - the actual dispatch/tracking logic lives there,
this just exposes it to the model with a JSON schema."""

from triton import background_tasks
from triton.agents import subagents
from triton.tools._shared import Tool


def dispatch_subagent(task: str) -> str:
    return subagents.dispatch(task)


def check_subagent(task_id: str) -> str:
    return subagents.check(task_id)


def start_background_task(
    command: str, session_id: str, name: str = "", directory: str = "."
) -> str:
    return background_tasks.start(session_id, command, name, directory)


def stop_background_task(task_id: str) -> str:
    return background_tasks.stop(task_id)


def list_background_tasks(session_id: str) -> str:
    tasks = background_tasks.list_tasks(session_id=session_id)
    if not tasks:
        return "(no background tasks in this conversation)"
    return "\n".join(f"{t.id} [{t.status}] {t.name} (directory={t.directory})" for t in tasks)


REGISTRY: dict[str, Tool] = {
    "dispatch_subagent": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "dispatch_subagent",
                "description": "Starts a focused, read-only research sub-agent in the "
                "background and returns immediately, without waiting for it to finish "
                "(true parallel execution: keep working while it runs). It can take "
                "anywhere from several seconds to a couple minutes depending on the task "
                "- don't check on it repeatedly, see check_subagent. Its own reasoning "
                "and tool calls stay isolated from this conversation, only its final "
                "result comes back. Give it a self-contained task description, since it "
                "starts with no context beyond what's provided.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Self-contained description of what the "
                            "sub-agent should research or find out.",
                        },
                    },
                    "required": ["task"],
                },
            },
        },
        fn=dispatch_subagent,
        read_only=True,
    ),
    "check_subagent": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "check_subagent",
                "description": "Checks on a sub-agent started with dispatch_subagent: "
                "returns its result if it finished, or that it's still running. Don't "
                "call this repeatedly in a tight loop - if it's still running, respond "
                "to the user or continue other work, and check again in a later "
                "response instead.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Id returned by dispatch_subagent.",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        },
        fn=check_subagent,
        read_only=True,
    ),
    "start_background_task": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "start_background_task",
                "description": "Starts a long-running background process (e.g. a dev server, "
                "a watch/build command) that keeps running after this call returns, without "
                "blocking the conversation. Don't use this for one-off commands that finish "
                "on their own - use run_shell for those. Check on it with "
                "list_background_tasks, and stop it with stop_background_task when done. "
                "The user can also see it, read its live output, and stop it from the app.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run in the background.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Short label to identify the task "
                            "(default: the command itself).",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Working directory to run the command in "
                            "(default: current directory).",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        fn=start_background_task,
        read_only=False,
    ),
    "stop_background_task": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "stop_background_task",
                "description": "Stops a background task started with start_background_task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Id returned by start_background_task.",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        },
        fn=stop_background_task,
        read_only=True,
    ),
    "list_background_tasks": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "list_background_tasks",
                "description": "Lists the background tasks started in this conversation, "
                "with their status.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        fn=list_background_tasks,
        read_only=True,
    ),
}
