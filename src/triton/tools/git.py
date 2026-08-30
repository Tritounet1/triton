"""git status/diff/commit, shelling out to the real git binary rather than
a Python git library - the harness's own sandboxing/confirmation flow is
what keeps this safe, not the tool implementation itself."""

import subprocess

from triton.tools._shared import Tool


def _run_git(args: list[str], directory: str = ".") -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=directory, capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired:
        return "error: git command took too long (15s timeout)"
    except OSError as e:
        return f"error: could not run git ({e})"
    output = (result.stdout + result.stderr).strip()
    return output or "(no output)"


def git_status(directory: str = ".") -> str:
    return _run_git(["status", "--short", "--branch"], directory)


def git_diff(path: str = "", directory: str = ".") -> str:
    args = ["diff"]
    if path:
        args.append(path)
    return _run_git(args, directory)


def git_commit(message: str, paths: list[str] | None = None, directory: str = ".") -> str:
    add_result = _run_git(["add", *paths] if paths else ["add", "-A"], directory)
    if add_result.startswith("error:"):
        return add_result
    return _run_git(["commit", "-m", message], directory)


REGISTRY: dict[str, Tool] = {
    "git_status": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_status",
                "description": "Shows the working tree status (short format) of a git repo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Repository directory (default: current directory).",
                        },
                    },
                    "required": [],
                },
            },
        },
        fn=git_status,
        read_only=True,
    ),
    "git_diff": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": "Shows the unstaged changes of a git repo, "
                "optionally restricted to one path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Restrict the diff to this file or directory.",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Repository directory (default: current directory).",
                        },
                    },
                    "required": [],
                },
            },
        },
        fn=git_diff,
        read_only=True,
    ),
    "git_commit": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_commit",
                "description": "Stages changes and creates a git commit. Stages the given "
                "paths, or all changes if none are given.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Commit message.",
                        },
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific paths to stage before committing "
                            "(default: all changes).",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Repository directory (default: current directory).",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        fn=git_commit,
        read_only=False,
    ),
}
