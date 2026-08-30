"""Running things: an arbitrary shell command, or the project's test suite.
The harness's own confirmation flow (never these functions themselves) is
what keeps run_shell from being unsupervised - it's the one tool withheld
from every multi-agent role regardless of write access (see
agents/orchestrator.py's CODE_WRITE_TOOL_NAMES)."""

import subprocess

from triton.tools._shared import Tool


def run_shell(command: str) -> str:
    # no confirmation before execution here, that comes at step 7
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "error: command took too long (10s timeout)"
    output = (result.stdout + result.stderr).strip()
    return output or f"(no output, exit code {result.returncode})"


def run_tests(path: str = "") -> str:
    args = ["pytest", "-q"]
    if path:
        args.append(path)
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
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
                    },
                    "required": [],
                },
            },
        },
        fn=run_tests,
        read_only=False,
    ),
}
