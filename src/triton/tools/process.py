"""Running things: an arbitrary shell command, or the project's test suite.
The harness's own confirmation flow (never these functions themselves) is
what keeps run_shell from being unsupervised - it's the one tool withheld
from every multi-agent role regardless of write access (see
agents/orchestrator.py's CODE_WRITE_TOOL_NAMES).

Both take an (optional) `directory` argument that _shared.py's
DEFAULTABLE_PATH_ARGS defaults to the active project's folder - without
it, subprocess.run's own default cwd is this harness's own process
directory, not the project's, so a command like `ls` would list the
wrong folder entirely for a project-scoped conversation. This is a
sandboxing improvement, not a jailbreak-proof sandbox: a command that
deliberately does `cd .. && rm -rf` still escapes, the same way it would
in a real terminal - see enforce_project_sandbox's module docstring."""

import subprocess

from triton.tools._shared import Tool


def run_shell(command: str, directory: str = "") -> str:
    # no confirmation before execution here, that comes at step 7
    try:
        result = subprocess.run(
            command, shell=True, cwd=directory or None, capture_output=True, text=True, timeout=10
        )
    except subprocess.TimeoutExpired:
        return "error: command took too long (10s timeout)"
    output = (result.stdout + result.stderr).strip()
    return output or f"(no output, exit code {result.returncode})"


def run_tests(path: str = "", directory: str = "") -> str:
    args = ["pytest", "-q"]
    if path:
        args.append(path)
    try:
        result = subprocess.run(
            args, cwd=directory or None, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return "error: test run took too long (120s timeout)"
    except OSError as e:
        return f"error: could not run tests ({e})"
    output = (result.stdout + result.stderr).strip()
    return output or f"(no output, exit code {result.returncode})"


REGISTRY: dict[str, Tool] = {
    "run_shell": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "run_shell",
                "description": "Runs a shell command and returns its output. Do not use this "
                "to create or edit files (no echo/cat/heredoc redirection) — use write_file "
                "or edit_file instead, which don't require shell quoting.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run.",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Working directory for the command (default: the "
                            "active project's folder, if one is set for this conversation).",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        fn=run_shell,
        read_only=False,
    ),
    "run_tests": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": "Runs the project's test suite (pytest) and returns the output.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Restrict the run to this test file or "
                            "directory (default: whole suite).",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Working directory to run pytest from (default: the "
                            "active project's folder, if one is set for this conversation).",
                        },
                    },
                    "required": [],
                },
            },
        },
        fn=run_tests,
        read_only=False,
    ),
}
