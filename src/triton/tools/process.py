"""Running things: an arbitrary shell command, the project's test suite,
or a standalone Python/JavaScript snippet. The harness's own confirmation
flow (never these functions themselves) is what keeps run_shell/run_code
from being unsupervised - they're withheld from every multi-agent role
regardless of write access (see agents/orchestrator.py's
CODE_WRITE_TOOL_NAMES), same as git_commit.

All three take an (optional) `directory` argument that _shared.py's
DEFAULTABLE_PATH_ARGS defaults to the active project's folder - without
it, subprocess.run's own default cwd is this harness's own process
directory, not the project's. On its own that only confines the
*starting* directory: a command that does `cd .. && rm -rf` (confirmed
live - a real conversation tried exactly this) still reaches outside the
project, same as in a real terminal. _run_confined below closes that gap
on macOS via sandbox-exec (Seatbelt): filesystem *writes* are confined to
the project folder (plus well-known cache/temp dirs real tools
legitimately need, found by testing real commands, not guessed - `git
status`, tempfile, `npm install` each broke until their dir was added)
regardless of what the command/code text does; *reads* stay broadly
allowed, with a short deny-list of credential stores (~/.ssh, ~/.aws,
...) and the harness's own data - see _MACOS_SANDBOX_PROFILE for why a
project-only read sandbox and a whole-ROOT_DIR deny were each tried and
abandoned. No such primitive exists on Linux/Windows, so they keep only
the `directory`-argument confinement above - see PLAN.md for the tracked
gap this leaves there."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO

from triton.paths import ROOT_DIR
from triton.tools._shared import Tool

# devices real commands routinely write to (`> /dev/null`, git's internal
# checks, /dev/tty prompts, /dev/urandom, /dev/dtracehelper - some tools
# probe it even when not tracing) - found the same way as the directories
# below: a command failed until the specific device it needed was added.
_MACOS_SANDBOX_DEVICES = (
    "/dev/null",
    "/dev/zero",
    "/dev/tty",
    "/dev/urandom",
    "/dev/dtracehelper",
)

# well-known credential/secret stores under the user's home directory - a
# shell command has no legitimate reason to read these, denied even
# though reads are otherwise broadly allowed (see _MACOS_SANDBOX_PROFILE
# for why a *full* read sandbox isn't attempted). Not exhaustive -
# .npmrc/.pypirc-style per-tool credential files are deliberately left
# readable since package managers legitimately need them more often than
# this harness needs to worry about a model reading them.
_MACOS_SANDBOX_DENIED_HOME_DIRS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".docker",
    "Library/Keychains",
)
_MACOS_SANDBOX_DENIED_HOME_FILES = (
    ".netrc",
    ".git-credentials",
)

# the harness's own *data*, as opposed to its source code - the same
# paths enforce_project_sandbox already refuses for every path-argument
# tool, but that check never sees run_shell's command text or run_code's
# code, so without this a shell command could read settings.json/
# sessions/API keys straight through. Denying all of ROOT_DIR wholesale
# (with a carve-out allowing .venv back in, since `uv run` puts .venv/bin
# at the front of PATH) was tried first and abandoned: a subpath deny
# covering an ancestor of a subpath allow didn't reliably yield to the
# allow regardless of rule order (confirmed by testing - python3 could
# sometimes launch then crash on its own import machinery, worse than
# just enumerating what's actually sensitive). Listing sensitive paths as
# siblings of .venv sidesteps the overlap, and is arguably more correct
# besides: the harness's own source isn't a secret, only its data is.
_MACOS_SANDBOX_DENIED_HARNESS_DIRS = (
    "sessions",
    "snapshot_backups",
    "project_memory",
    "logs",
    "background_tasks_state",
    "orchestrator_runs",
)
_MACOS_SANDBOX_DENIED_HARNESS_FILES = (
    ".env",
    "settings.json",
    "mcp_servers.json",
    "snapshots.json",
    "projects.json",
    "memory_global.md",
)

_MACOS_SANDBOX_DENIED_DIR_COUNT = len(_MACOS_SANDBOX_DENIED_HOME_DIRS) + len(
    _MACOS_SANDBOX_DENIED_HARNESS_DIRS
)
_MACOS_SANDBOX_DENIED_FILE_COUNT = len(_MACOS_SANDBOX_DENIED_HOME_FILES) + len(
    _MACOS_SANDBOX_DENIED_HARNESS_FILES
)

# a Seatbelt (sandbox-exec) profile confining filesystem *writes* to
# whatever PROJECT_ROOT is bound to via -D, plus well-known cache/temp
# directories real tools legitimately write to outside any project (npm's
# cache, Python's tempfile, ...) - TMP_DIR/NPM_CACHE/GENERIC_CACHE/
# LIBRARY_CACHES are bound the same way, computed fresh per call in
# _macos_sandbox_argv since TMPDIR is session-specific.
#
# Reads are broadly allowed (file-read*), with the deny-lists above as
# the exception. Restricting reads to *only* the project folder was tried
# and rejected too: it broke the dynamic linker, interpreter stdlibs, DNS
# resolution, and ~/.ssh for a real `git clone` over SSH - allow-listing
# everything genuinely needed converges on "most of the filesystem"
# anyway, at which point a deny-list of actually-sensitive locations is
# both more maintainable and closer to the real threat model.
#
# The deny rules are listed before the broad file-read* allow - verified
# empirically: the reverse order let the allow win and the deny had no
# effect at all. Every bound path must already be fully resolved by the
# caller: Seatbelt matches the canonical path, and macOS symlinks /tmp ->
# /private/tmp and /var -> /private/var, so an unresolved "/tmp" silently
# wouldn't match (confirmed - tempfile writes kept failing until fixed).
# Paths go through -D/(param ...) rather than interpolated text, so a
# stray '"' in a path can't affect the profile's own syntax.
_MACOS_SANDBOX_PROFILE = (
    "(version 1)\n"
    "(deny default)\n"
    "(allow process-fork)\n"
    "(allow process-exec)\n"
    "(deny file-read*\n"
    + "\n".join(
        f'  (subpath (param "DENY_DIR_{i}"))' for i in range(_MACOS_SANDBOX_DENIED_DIR_COUNT)
    )
    + "\n"
    + "\n".join(
        f'  (literal (param "DENY_FILE_{i}"))' for i in range(_MACOS_SANDBOX_DENIED_FILE_COUNT)
    )
    + ")\n"
    "(allow file-read*)\n"
    "(allow file-write*\n"
    '  (subpath (param "PROJECT_ROOT"))\n'
    '  (subpath (param "TMP_DIR"))\n'
    '  (subpath (param "NPM_CACHE"))\n'
    '  (subpath (param "GENERIC_CACHE"))\n'
    '  (subpath (param "LIBRARY_CACHES"))\n'
    + "\n".join(f'  (literal "{device}")' for device in _MACOS_SANDBOX_DEVICES)
    + ")\n"
    "(allow network*)\n"
    "(allow mach-lookup)\n"
    "(allow sysctl-read)\n"
    "(allow signal (target self))\n"
)


def _macos_sandbox_argv(directory: Path) -> list[str]:
    home = Path.home()
    harness_root = ROOT_DIR.resolve()
    argv = [
        "/usr/bin/sandbox-exec",
        "-p",
        _MACOS_SANDBOX_PROFILE,
        "-D",
        f"PROJECT_ROOT={directory}",
        "-D",
        f"TMP_DIR={Path(tempfile.gettempdir()).resolve()}",
        "-D",
        f"NPM_CACHE={home / '.npm'}",
        "-D",
        f"GENERIC_CACHE={home / '.cache'}",
        "-D",
        f"LIBRARY_CACHES={home / 'Library' / 'Caches'}",
    ]
    denied_dirs = [home / rel for rel in _MACOS_SANDBOX_DENIED_HOME_DIRS] + [
        harness_root / rel for rel in _MACOS_SANDBOX_DENIED_HARNESS_DIRS
    ]
    denied_files = [home / rel for rel in _MACOS_SANDBOX_DENIED_HOME_FILES] + [
        harness_root / rel for rel in _MACOS_SANDBOX_DENIED_HARNESS_FILES
    ]
    for i, p in enumerate(denied_dirs):
        argv += ["-D", f"DENY_DIR_{i}={p}"]
    for i, p in enumerate(denied_files):
        argv += ["-D", f"DENY_FILE_{i}={p}"]
    return argv


def _run_confined(
    command: str | list[str], directory: str, timeout: float
) -> subprocess.CompletedProcess[str]:
    """subprocess.run, transparently wrapped with sandbox-exec on macOS
    whenever a directory is given - see _MACOS_SANDBOX_PROFILE for what
    that confines and why. `command` is either a shell command string
    (run_shell, via `/bin/sh -c`) or an argv list (run_code/run_tests) -
    both reach this the same way since sandbox-exec has to wrap whichever
    one actually runs. A no-op elsewhere: sandbox-exec doesn't exist
    outside macOS."""
    is_shell_string = isinstance(command, str)
    if sys.platform == "darwin" and directory:
        argv = ["/bin/sh", "-c", command] if is_shell_string else command
        full_argv = [*_macos_sandbox_argv(Path(directory).resolve()), *argv]
        return subprocess.run(
            full_argv, cwd=directory, capture_output=True, text=True, timeout=timeout
        )
    return subprocess.run(
        command,
        shell=is_shell_string,
        cwd=directory or None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def start_confined_process(
    command: str, directory: str, stdout: BinaryIO
) -> subprocess.Popen[bytes]:
    """Start a long-running shell command with the same macOS confinement.

    ``start_background_task`` has no timeout by design, but it must not
    lose the project-write sandbox :func:`run_shell` gets just because it
    outlives the chat turn. The caller validates that ``directory`` is an
    allowed project path before reaching here.
    """
    root = Path(directory).resolve()
    if sys.platform == "darwin":
        argv = [*_macos_sandbox_argv(root), "/bin/sh", "-c", command]
        return subprocess.Popen(
            argv,
            cwd=root,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return subprocess.Popen(
        command,
        shell=True,
        cwd=root,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


# raised from 10: real one-off commands this tool is meant for (package
# installs, scaffolding with create-next-app, git clone...) routinely take
# much longer, especially fetching a registry/package for the first time -
# 10s made an ordinary `npx create-next-app` fail outright. Matches
# run_tests's timeout below: a genuinely long-running process (a dev
# server, a watcher) belongs in start_background_task instead, never here.
RUN_SHELL_TIMEOUT_SECONDS = 120


def run_shell(command: str, directory: str = "") -> str:
    # no confirmation before execution here, that comes at step 7
    try:
        result = _run_confined(command, directory, timeout=RUN_SHELL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"error: command took too long ({RUN_SHELL_TIMEOUT_SECONDS}s timeout)"
    output = (result.stdout + result.stderr).strip()
    return output or f"(no output, exit code {result.returncode})"


def run_tests(path: str = "", directory: str = "") -> str:
    args = ["pytest", "-q"]
    if path:
        args.append(path)
    try:
        result = _run_confined(args, directory, timeout=120)
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
    in a PyInstaller-frozen build (see paths.py's sys.frozen check) it's
    the frozen triton-server binary itself - running that with a script
    path just tries to relaunch the server. Falls back to whatever
    python3/python is on the end user's PATH, best-effort (same
    assumption run_tests makes about pytest)."""
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
    parsing, unlike run_shell) and returns its output. Stateless by
    design - each call is a fresh process, nothing persists between calls
    - meant for one-shot throwaway scripts, not a persistent REPL; that
    would mean keeping a subprocess alive per session, real complexity
    this use case doesn't need."""
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
            result = _run_confined(
                [*interpreter, script_path], directory, timeout=RUN_CODE_TIMEOUT_SECONDS
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
                "or edit_file instead, which don't require shell quoting. Filesystem writes "
                "are confined to the project folder even via `cd ..` or an absolute path - "
                "don't try to work around this, it won't succeed.",
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
                "fresh process, nothing (variables, imports) carries over to the next call. "
                "Filesystem writes are confined to the project folder, whatever the code "
                "itself tries to do.",
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
