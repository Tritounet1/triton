"""Infrastructure shared by every tool category in this package: the Tool
type itself, invoking one safely, and the project-folder sandbox. Kept
separate from tools/__init__.py (rather than defined there directly) so
category modules (filesystem.py, search.py, ...) can import from here
without depending on __init__.py, which itself imports every category
module to assemble TOOLS_REGISTRY - a category module importing back from
__init__ would be circular."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai.types.chat import ChatCompletionToolParam

from triton.paths import ROOT_DIR
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
SESSION_AWARE_TOOLS = {
    "start_background_task",
    "list_background_tasks",
    "remember",
    "dispatch_subagent",
}


def invoke_tool(tool: Tool, name: str, args: dict[str, object], session_id: str) -> str:
    """Calls a tool's implementation, translating any exception into an
    error string instead of letting it propagate. The model isn't actually
    bound by the JSON schema it's given - it can (and does) hallucinate an
    argument a tool doesn't accept. Without this, that raises an uncaught
    TypeError deep inside run_chat_stream's generator and crashes the
    whole SSE response, not just that one call."""
    try:
        if name in SESSION_AWARE_TOOLS:
            return tool.fn(session_id=session_id, **args)
        return tool.fn(**args)
    except TypeError as e:
        return f"error: invalid arguments for {name} ({e})"
    except Exception as e:
        # broad on purpose: a tool's own bug must not crash the conversation
        return f"error: {name} failed unexpectedly ({type(e).__name__}: {e})"


# every tool that touches the local filesystem or spawns a process -
# path/directory arguments to confine to the active project's folder when
# a conversation, subagent, or multi-agent subtask is scoped to one, and
# the complete set of tools enforce_project_sandbox blocks outright when
# there's no project at all. MCP-sourced tools (unknown schemas) are
# deliberately not covered here and remain unrestricted - a separate,
# pre-existing gap.
#
# run_shell/run_tests/run_code only get a `directory` check here, not a
# command-content one: this confines their *starting* directory to the
# project. A command that does `cd .. && rm -rf` would still reach outside
# on this check alone - on macOS that gap is closed one level down, in
# process.py's _run_confined (a real sandbox-exec/Seatbelt confinement);
# Linux/Windows have no equivalent and keep only this directory check.
SANDBOXED_PATH_ARGS: dict[str, list[str]] = {
    "read_file": ["path"],
    "list_files": ["directory"],
    "write_file": ["path"],
    # edit_file is deliberately absent here: its "edits" argument is a
    # list of {path, old_string, new_string, ...} objects, not a flat
    # string/list-of-strings like every other entry below - it gets its
    # own check, _enforce_edit_file_sandbox, called directly from
    # enforce_project_sandbox before this dict is even consulted.
    "delete_file": ["path"],
    "move_file": ["source", "destination"],
    "grep": ["directory"],
    "glob": ["directory"],
    "git_status": ["directory"],
    "git_diff": ["directory", "path"],
    "git_commit": ["directory", "paths"],
    "git_log": ["directory", "path"],
    "git_branch": ["directory"],
    "git_checkout": ["directory"],
    "git_push": ["directory"],
    "run_shell": ["directory"],
    "run_tests": ["path", "directory"],
    "run_code": ["directory"],
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
    "git_log",
    "git_branch",
    "git_checkout",
    "git_push",
    "run_shell",
    "run_tests",
    "run_code",
    "start_background_task",
}


def _resolve(raw_path: str, root: Path) -> Path:
    candidate = Path(raw_path)
    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()


def _path_error(raw_path: str, resolved: Path, root: Path) -> str | None:
    """None if `resolved` is a legal target: inside the project folder,
    and not inside the harness's own installation directory (ROOT_DIR)
    even when the project happens to be scoped there. The ROOT_DIR check
    is unconditional - a deliberately-scoped project pointed at it would
    otherwise get full read/write access to this harness's own
    settings.json, every conversation's history, and its snapshot
    backups: materially more sensitive than an arbitrary project folder."""
    if resolved.is_relative_to(ROOT_DIR):
        return (
            f"error: '{raw_path}' resolves inside the harness's own installation "
            f"directory ({ROOT_DIR}), which tool calls can never touch - even within "
            "a project scoped there. It holds this harness's own settings, every "
            "conversation's history, and (in a dev checkout) API keys."
        )
    if not resolved.is_relative_to(root):
        return (
            f"error: this conversation is scoped to the project folder {root}, "
            f"'{raw_path}' resolves outside of it. Use a path within the project."
        )
    return None


def _enforce_edit_file_sandbox(args: dict[str, object], root: Path) -> str | None:
    """edit_file's own path check: `args["edits"]` is a list of
    {path, old_string, new_string, ...} objects (see filesystem.py) rather
    than the flat string/list-of-strings shape SANDBOXED_PATH_ARGS assumes
    for every other tool, so it can't reuse the generic loop below."""
    edits = args.get("edits")
    if not isinstance(edits, list):
        return None

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        raw_path = edit.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        error = _path_error(raw_path, _resolve(raw_path, root), root)
        if error is not None:
            return error
    return None


# a small, non-bypassable hard denylist of catastrophic run_shell commands -
# inspired by yc-software/qm, whose most permissive ("Dangerous") posture
# still keeps a short hard-deny list that applies regardless of posture.
# The project-folder write confinement above, plus process.py's real
# sandbox-exec confinement on macOS, already stop most damage - but neither
# covers a command's own *text* on Linux/Windows, and a regex hit here
# gives a clear "denied outright" message instead of a silent OS-level
# failure. Deliberately not an attempt at full shell-semantics parsing
# (trivially defeated by obfuscation) - just the handful of commands
# nobody has a legitimate reason to run, checked in
# enforce_project_sandbox so every call site gets it for free, before that
# site's own confirmation/yolo check ever runs.
_HARD_DENYLIST: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\brm\s+(-\w*)?[rR][fF]?\w*\s+(-\w+\s+)*(/|~|\$HOME)(\s|/|$)"),
        "a recursive delete of the home directory or filesystem root",
    ),
    (
        re.compile(r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)"),
        "a force-push",
    ),
    (re.compile(r"\bmkfs(\.\w+)?\b"), "formatting a filesystem"),
    (re.compile(r"\bdd\b[^\n]*\bof=/dev/"), "writing directly to a block device"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "a fork bomb"),
)


def _check_hard_denylist(name: str, args: dict[str, object]) -> str | None:
    if name != "run_shell":
        return None
    command = args.get("command")
    if not isinstance(command, str):
        return None
    for pattern, label in _HARD_DENYLIST:
        if pattern.search(command):
            return (
                f"error: this command looks like {label}, which is denied outright - "
                "this stays blocked even with /yolo active, not just pending confirmation."
            )
    return None


def enforce_project_sandbox(
    name: str, args: dict[str, object], project: Project | None, remote_workspace: bool = False
) -> str | None:
    """Returns an error message if a tool call is disallowed, or None if
    it's allowed. Three things it enforces:

    - _check_hard_denylist's small, non-bypassable set of catastrophic
      run_shell commands, checked first regardless of project state.
    - Every tool that touches the filesystem or spawns a process
      (SANDBOXED_PATH_ARGS's keys, plus edit_file) needs a project: with
      none scoped, the call is blocked outright rather than left free to
      touch anywhere on disk. A tool not in that set is unaffected.
    - Once a project is confirmed, every path argument must resolve
      inside its folder, never inside the harness's own installation
      directory - see _path_error.

    Mutates `args` in place to default an omitted directory argument to
    the project folder for tools in DEFAULTABLE_PATH_ARGS."""
    denylist_error = _check_hard_denylist(name, args)
    if denylist_error is not None:
        return denylist_error

    is_filesystem_tool = name == "edit_file" or name in SANDBOXED_PATH_ARGS
    if not is_filesystem_tool:
        return None

    if project is None:
        return (
            f"error: {name} needs a project to be selected for this conversation - "
            "open or create one first. A conversation with no project can't touch "
            "the local filesystem or run commands at all, to avoid reading or "
            "modifying anything outside whatever a project explicitly scopes it to."
        )

    if remote_workspace:
        return None

    root = Path(project.folder_path).resolve()

    if name == "edit_file":
        return _enforce_edit_file_sandbox(args, root)

    for arg_name in SANDBOXED_PATH_ARGS[name]:
        value = args.get(arg_name)

        if not value:
            if name in DEFAULTABLE_PATH_ARGS and arg_name == "directory":
                args[arg_name] = str(root)
            continue

        for raw_path in value if isinstance(value, list) else [value]:
            if not isinstance(raw_path, str) or not raw_path:
                continue
            error = _path_error(raw_path, _resolve(raw_path, root), root)
            if error is not None:
                return error

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
    # framework build/cache dirs - can hold thousands of generated files,
    # easily exhausting the file panel's MAX_TREE_ENTRIES budget before
    # reaching real source (found via a Next.js project where
    # .next/.pnpm-store alone consumed the whole budget, since _build_tree
    # walks depth-first and dot-prefixed dirs sort first)
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".turbo",
    ".vercel",
    ".cache",
    ".parcel-cache",
    ".pnpm-store",
    "coverage",
}


def is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)
