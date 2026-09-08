"""git status/diff/commit, shelling out to the real git binary rather than
a Python git library - the harness's own sandboxing/confirmation flow is
what keeps this safe, not the tool implementation itself."""

import subprocess

from triton.tools._shared import Tool

GIT_TIMEOUT_SECONDS = 15
# network-bound, not just local disk - a slow connection or a big push
# routinely needs more than a local status/diff/commit ever would (see
# PLAN.md's own note on run_shell's timeout having been too tight for the
# same reason).
GIT_PUSH_TIMEOUT_SECONDS = 60


def _run_git(args: list[str], directory: str = ".", timeout: float = GIT_TIMEOUT_SECONDS) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=directory, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return f"error: git command took too long ({timeout:g}s timeout)"
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


def git_log(directory: str = ".", max_count: int = 20, path: str = "") -> str:
    args = ["log", "--oneline", f"-n{max_count}"]
    if path:
        args += ["--", path]
    return _run_git(args, directory)


def git_branch(directory: str = ".") -> str:
    return _run_git(["branch", "--list"], directory)


def git_checkout(branch: str, create: bool = False, directory: str = ".") -> str:
    args = ["checkout", "-b", branch] if create else ["checkout", branch]
    return _run_git(args, directory)


def git_push(
    directory: str = ".", remote: str = "origin", branch: str = "", set_upstream: bool = False
) -> str:
    # no --force/--force-with-lease exposed here, deliberately - a
    # destructive remote rewrite is exactly the kind of action that
    # shouldn't be one model-invented argument away, confirmation prompt
    # or not (see PLAN.md's own note when this tool was proposed).
    args = ["push"]
    if set_upstream:
        args.append("-u")
    args.append(remote)
    if branch:
        args.append(branch)
    elif set_upstream:
        # `git push -u origin` alone still fails asking for an explicit
        # refspec (-u/--set-upstream needs one, unlike a plain push) -
        # HEAD sidesteps needing to already know the current branch's name
        args.append("HEAD")
    return _run_git(args, directory, timeout=GIT_PUSH_TIMEOUT_SECONDS)


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
    "git_log": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_log",
                "description": "Shows recent commit history (one line per commit: short "
                "hash + subject), optionally restricted to one path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "max_count": {
                            "type": "integer",
                            "description": "Maximum number of commits to show (default: 20).",
                        },
                        "path": {
                            "type": "string",
                            "description": "Restrict the history to this file or directory.",
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
        fn=git_log,
        read_only=True,
    ),
    "git_branch": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_branch",
                "description": "Lists local branches (the current one marked with '*').",
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
        fn=git_branch,
        read_only=True,
    ),
    "git_checkout": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_checkout",
                "description": "Switches to an existing branch, or creates a new one and "
                "switches to it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "branch": {
                            "type": "string",
                            "description": "Branch to switch to.",
                        },
                        "create": {
                            "type": "boolean",
                            "description": "Create the branch instead of switching to an "
                            "existing one. Default: false.",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Repository directory (default: current directory).",
                        },
                    },
                    "required": ["branch"],
                },
            },
        },
        fn=git_checkout,
        read_only=False,
    ),
    "git_push": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "git_push",
                "description": "Pushes committed changes to a remote. Never force-pushes - "
                "there's no argument for it, on purpose. If the branch has no upstream set "
                "yet, either pass set_upstream=true or push will fail asking for one.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "remote": {
                            "type": "string",
                            "description": "Remote to push to (default: origin).",
                        },
                        "branch": {
                            "type": "string",
                            "description": "Branch to push (default: the current branch's "
                            "configured upstream).",
                        },
                        "set_upstream": {
                            "type": "boolean",
                            "description": "Set the pushed branch's upstream (git push -u) - "
                            "needed the first time a new branch is pushed. Default: false.",
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
        fn=git_push,
        read_only=False,
    ),
}
