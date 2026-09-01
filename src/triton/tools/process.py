"""Running things: an arbitrary shell command, the project's test suite,
or a standalone Python/JavaScript snippet. The harness's own confirmation
flow (never these functions themselves) is what keeps run_shell/run_code
from being unsupervised - they're withheld from every multi-agent role
regardless of write access (see agents/orchestrator.py's
CODE_WRITE_TOOL_NAMES), same as git_commit.

All three take an (optional) `directory` argument that _shared.py's
DEFAULTABLE_PATH_ARGS defaults to the active project's folder - without
it, subprocess.run's own default cwd is this harness's own process
directory, not the project's, so a command like `ls` would list the
wrong folder entirely for a project-scoped conversation. This is a
sandboxing improvement, not a jailbreak-proof sandbox: a command that
deliberately does `cd .. && rm -rf` still escapes, the same way it would
in a real terminal - see enforce_project_sandbox's module docstring."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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


# stdout+stderr past this length is cut off - a runaway print loop
# shouldn't blow up the conversation's context the way an uncapped
# fetch_url used to (see tools/web.py's own truncation for the same
# reason).
RUN_CODE_TIMEOUT_SECONDS = 15
RUN_CODE_MAX_OUTPUT_CHARS = 8000

_LANGUAGE_ALIASES = {"py": "python", "js": "javascript", "node": "javascript"}
_SUFFIXES = {"python": ".py", "javascript": ".js"}


def _python_interpreter() -> list[str] | None:
    """sys.executable is a real Python interpreter in dev (uv run ...), but
    in a PyInstaller-frozen build (see paths.py's own sys.frozen check)
    it's the path to the frozen triton-server binary itself - running that
    with a script path as an argument doesn't execute the script, it just
    tries to relaunch the server. Falls back to whatever python3/python
    the end user's own system has on PATH, best-effort (same category of
    external-dependency assumption run_tests already makes about pytest
    being on PATH)."""
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    for candidate in ("python3", "python"):
        found = shutil.which(candidate)
        if found:
            return [found]
    return None


def _interpreter(language: str) -> list[str] | None:
    if language == "python":
        return _python_interpreter()
    if language == "javascript":
        found = shutil.which("node")
        return [found] if found else None
    return None


def run_code(code: str, language: str = "python", directory: str = "") -> str:
    """Runs a standalone snippet through a real interpreter (no shell
    parsing involved, unlike run_shell) and returns its output. Stateless
    by design - each call is a fresh process, nothing (variables, imports)
    persists between calls - this is meant for one-shot throwaway
    calculations/scripts, not a persistent REPL; a stateful version would
    mean keeping a subprocess alive per session and cleaning it up, real
    complexity for a use case ("quick calc/script") that doesn't need it."""
    lang = _LANGUAGE_ALIASES.get(language, language)
    if lang not in _SUFFIXES:
        return f"error: unsupported language '{language}' - use 'python' or 'javascript'"

    interpreter = _interpreter(lang)
    if interpreter is None:
        return f"error: no {lang} interpreter found on this system"

    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=_SUFFIXES[lang], delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            script_path = f.name
        try:
            result = subprocess.run(
                [*interpreter, script_path],
                cwd=directory or None,
                capture_output=True,
                text=True,
                timeout=RUN_CODE_TIMEOUT_SECONDS,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        return f"error: code took too long ({RUN_CODE_TIMEOUT_SECONDS}s timeout)"
    except OSError as e:
        return f"error: could not run {lang} code ({e})"

    output = (result.stdout + result.stderr).strip()
    if len(output) > RUN_CODE_MAX_OUTPUT_CHARS:
        output = output[:RUN_CODE_MAX_OUTPUT_CHARS] + "\n(truncated)"
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
    "run_code": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "run_code",
                "description": "Runs a standalone Python or JavaScript (Node) snippet through "
                "a real interpreter and returns its output (stdout+stderr) - for one-shot "
                "calculations or scripts, not for creating/editing project files (use "
                "write_file/edit_file for that) and not a persistent REPL: each call is a "
                "fresh process, nothing (variables, imports) carries over to the next call.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The full source code to run.",
                        },
                        "language": {
                            "type": "string",
                            "enum": ["python", "javascript"],
                            "description": "Language to run the code as. Default: python.",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Working directory for the code (default: the "
                            "active project's folder, if one is set for this conversation).",
                        },
                    },
                    "required": ["code"],
                },
            },
        },
        fn=run_code,
        read_only=False,
    ),
}
