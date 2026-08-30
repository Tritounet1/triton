"""Infrastructure shared by every tool category in this package: the Tool
type itself, invoking one safely, and the project-folder sandbox. Kept
separate from tools/__init__.py (rather than defined there directly) so
category modules (filesystem.py, search.py, ...) can import from here
without depending on __init__.py, which itself imports every category
module to assemble TOOLS_REGISTRY - a category module importing back from
__init__ would be circular."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai.types.chat import ChatCompletionToolParam

from triton.storage.projects import Project


@dataclass
class Tool:
    schema: ChatCompletionToolParam
    fn: Callable[..., str]
    read_only: bool


# tools whose implementation needs to know which conversation called them
# (e.g. to scope a background task to the session that started it), beyond
# the plain model-provided arguments. server.py/main.py inject session_id
# through invoke_tool() instead of the generic tool.fn(**args) call.
SESSION_AWARE_TOOLS = {"start_background_task", "list_background_tasks"}


def invoke_tool(tool: Tool, name: str, args: dict[str, object], session_id: str) -> str:
    """Calls a tool's implementation, translating any exception into an
    error string instead of letting it propagate. The model isn't actually
    bound by the JSON schema it's given - it can (and does) hallucinate an
    argument a tool doesn't accept, e.g. calling run_shell with a
    `directory` kwarg it only has because other tools have one. Without
    this, that raises an uncaught TypeError deep inside run_chat_stream's
    generator and crashes the whole SSE response, not just that one call."""
    try:
        if name in SESSION_AWARE_TOOLS:
            return tool.fn(session_id=session_id, **args)
        return tool.fn(**args)
    except TypeError as e:
        return f"error: invalid arguments for {name} ({e})"
    except Exception as e:
        # broad on purpose: a tool's own bug must not crash the conversation
        return f"error: {name} failed unexpectedly ({type(e).__name__}: {e})"


# path/directory arguments to confine to the active project's folder when
# a conversation (server.py) or a multi-agent subtask (orchestrator.py) is
# scoped to one. run_shell (arbitrary command, no single path argument to
# check) and MCP-sourced tools (unknown schemas) are deliberately not
# covered here. Lives here rather than in server.py so orchestrator.py can
# import it too without an import cycle (server.py already imports
# orchestrator.py).
SANDBOXED_PATH_ARGS: dict[str, list[str]] = {
    "read_file": ["path"],
    "list_files": ["directory"],
    "write_file": ["path"],
    "edit_file": ["path"],
    "delete_file": ["path"],
    "move_file": ["source", "destination"],
    "grep": ["directory"],
    "glob": ["directory"],
    "git_status": ["directory"],
    "git_diff": ["directory", "path"],
    "git_commit": ["directory", "paths"],
    "run_tests": ["path"],
    "start_background_task": ["directory"],
}

# for these, an omitted argument otherwise defaults to "." (the caller's
# own working directory, not the project folder) - when scoped to a
# project, default it to the project folder instead, so a call that omits
# the argument stays inside the project rather than leaking the harness's
# own source tree
DEFAULTABLE_PATH_ARGS = {
    "list_files",
    "grep",
    "glob",
    "git_status",
    "git_diff",
    "git_commit",
    "start_background_task",
}


def enforce_project_sandbox(
    name: str, args: dict[str, object], project: Project | None
) -> str | None:
    """Returns an error message if a file tool call would touch a path
    outside the active project's folder, or None if the call is allowed
    (no project scoped, or this tool isn't in SANDBOXED_PATH_ARGS). Mutates
    `args` in place to default an omitted directory argument to the
    project folder for tools in DEFAULTABLE_PATH_ARGS."""
    if project is None:
        return None

    arg_names = SANDBOXED_PATH_ARGS.get(name)
    if arg_names is None:
        return None

    root = Path(project.folder_path).resolve()

    for arg_name in arg_names:
        value = args.get(arg_name)

        if not value:
            if name in DEFAULTABLE_PATH_ARGS and arg_name == "directory":
                args[arg_name] = str(root)
            continue

        for raw_path in value if isinstance(value, list) else [value]:
            if not isinstance(raw_path, str) or not raw_path:
                continue
            candidate = Path(raw_path)
            resolved = (
                candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            )
            if not resolved.is_relative_to(root):
                return (
                    f"error: this conversation is scoped to the project folder {root}, "
                    f"'{raw_path}' resolves outside of it. Use a path within the project."
                )

    return None


SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


def is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)
