import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
from openai.types.chat import ChatCompletionToolParam

import subagents


@dataclass
class Tool:
    schema: ChatCompletionToolParam
    fn: Callable[..., str]
    read_only: bool


def read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError as e:
        return f"error: could not read {path} ({e})"


def list_files(directory: str = ".") -> str:
    try:
        entries = sorted(Path(directory).iterdir())
    except OSError as e:
        return f"error: could not list {directory} ({e})"
    if not entries:
        return "(empty directory)"
    return "\n".join(f"{'d' if p.is_dir() else 'f'} {p.name}" for p in entries)


def write_file(path: str, content: str) -> str:
    try:
        Path(path).write_text(content)
    except OSError as e:
        return f"error: could not write {path} ({e})"
    return f"file {path} written ({len(content)} characters)"


def run_shell(command: str) -> str:
    # no confirmation before execution here, that comes at step 7
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "error: command took too long (10s timeout)"
    output = (result.stdout + result.stderr).strip()
    return output or f"(no output, exit code {result.returncode})"


def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    try:
        content = Path(path).read_text()
    except OSError as e:
        return f"error: could not read {path} ({e})"

    count = content.count(old_string)
    if count == 0:
        return f"error: old_string not found in {path}"
    if count > 1 and not replace_all:
        return (
            f"error: old_string matches {count} times in {path}, "
            "use replace_all=true or a more specific old_string"
        )

    new_content = content.replace(old_string, new_string, -1 if replace_all else 1)
    try:
        Path(path).write_text(new_content)
    except OSError as e:
        return f"error: could not write {path} ({e})"
    return f"file {path} edited ({count if replace_all else 1} replacement(s))"


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


def grep(pattern: str, directory: str = ".", file_glob: str = "**/*") -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"error: invalid regex ({e})"

    root = Path(directory)
    if not root.exists():
        return f"error: directory not found: {directory}"

    matches: list[str] = []
    for path in sorted(root.glob(file_glob)):
        if not path.is_file() or is_skipped(path):
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{path}:{lineno}:{line.strip()}")
                if len(matches) >= 200:
                    return "\n".join(matches) + "\n(truncated at 200 matches)"

    return "\n".join(matches) if matches else "(no matches)"


def find_files(pattern: str, directory: str = ".") -> str:
    root = Path(directory)
    if not root.exists():
        return f"error: directory not found: {directory}"

    results = sorted(str(p) for p in root.glob(pattern) if not is_skipped(p))
    if not results:
        return "(no matches)"
    if len(results) > 500:
        return "\n".join(results[:500]) + "\n(truncated at 500 results)"
    return "\n".join(results)


def delete_file(path: str) -> str:
    target = Path(path)
    if not target.exists():
        return f"error: file not found: {path}"
    if target.is_dir():
        return f"error: {path} is a directory, not a file"
    try:
        target.unlink()
    except OSError as e:
        return f"error: could not delete {path} ({e})"
    return f"file {path} deleted"


def move_file(source: str, destination: str) -> str:
    src = Path(source)
    if not src.exists():
        return f"error: source not found: {source}"
    dst = Path(destination)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    except OSError as e:
        return f"error: could not move {source} to {destination} ({e})"
    return f"moved {source} to {destination}"


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


def fetch_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://"
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Triton/1.0"})
        response.raise_for_status()
    except requests.RequestException as e:
        return f"error: could not fetch {url} ({e})"

    text = response.text
    if "html" in response.headers.get("content-type", ""):
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    if len(text) > 5000:
        text = text[:5000] + "\n(truncated)"
    return text


def web_search(query: str) -> str:
    # scrapes DuckDuckGo's no-JS HTML endpoint (no API key required); the
    # regex parsing is brittle to markup changes but keeps this dependency-free
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Triton/1.0)"},
        )
        response.raise_for_status()
    except requests.RequestException as e:
        return f"error: web search failed ({e})"

    if "anomaly-modal" in response.text:
        return "error: DuckDuckGo returned a bot-detection challenge, try again later"

    raw_results = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        response.text,
        flags=re.DOTALL,
    )
    if not raw_results:
        return "(no results)"

    lines: list[str] = []
    for href, title in raw_results[:8]:
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        target_url = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        lines.append(f"{clean_title}\n{unquote(target_url)}")
    return "\n\n".join(lines)


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


_TODOS: list[dict[str, str]] = []


def todo_write(todos: list[dict[str, str]]) -> str:
    global _TODOS
    _TODOS = todos
    if not _TODOS:
        return "(todo list cleared)"
    markers = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    lines = [
        f"{markers.get(t.get('status', 'pending'), '[ ]')} {t.get('content', '')}" for t in _TODOS
    ]
    return "\n".join(lines)


MEMORY_FILE = Path(__file__).parent / "memory.md"


def remember(note: str) -> str:
    try:
        with MEMORY_FILE.open("a", encoding="utf-8") as f:
            f.write(f"- {note.strip()}\n")
    except OSError as e:
        return f"error: could not write to memory ({e})"
    return f"remembered: {note.strip()}"


def load_memory() -> str:
    """Returns the saved memory content, or an empty string if none exists.
    Used by main.py/server.py to prime the system prompt with facts learned
    in previous conversations, so the model doesn't need to be told again."""
    if not MEMORY_FILE.exists():
        return ""
    return MEMORY_FILE.read_text().strip()


def dispatch_subagent(task: str) -> str:
    return subagents.dispatch(task)


def check_subagent(task_id: str) -> str:
    return subagents.check(task_id)


TOOLS_REGISTRY: dict[str, Tool] = {
    "read_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Reads and returns the contents of a text file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path of the file to read.",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        fn=read_file,
        read_only=True,
    ),
    "list_files": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Lists the files and directories in a directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Path of the directory to list "
                            "(default: current directory).",
                        },
                    },
                    "required": [],
                },
            },
        },
        fn=list_files,
        read_only=True,
    ),
    "write_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Writes content to a text file (overwrites it if it already "
                "exists). Always use this to create or fully rewrite a file, instead of "
                "run_shell with echo/cat/heredoc redirection.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path of the file to write.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to the file.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        fn=write_file,
        read_only=False,
    ),
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
    "edit_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Replaces an exact piece of text in a file with another, "
                "without rewriting the whole file. Fails if old_string isn't found, or "
                "matches more than once and replace_all isn't set.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path of the file to edit.",
                        },
                        "old_string": {
                            "type": "string",
                            "description": "Exact text to replace.",
                        },
                        "new_string": {
                            "type": "string",
                            "description": "Text to replace it with.",
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "Replace every occurrence instead of failing "
                            "on ambiguity (default: false).",
                        },
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        },
        fn=edit_file,
        read_only=False,
    ),
    "grep": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "grep",
                "description": "Searches for a regular expression pattern across files in a "
                "directory, returning matching lines with file path and line number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regular expression to search for.",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Directory to search in (default: current directory).",
                        },
                        "file_glob": {
                            "type": "string",
                            "description": "Glob pattern restricting which files are searched, "
                            "e.g. **/*.py (default: all files).",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        },
        fn=grep,
        read_only=True,
    ),
    "glob": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "glob",
                "description": "Finds files matching a glob pattern (e.g. **/*.py), "
                "recursively unlike list_files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Glob pattern to match, e.g. **/*.py.",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Directory to search in (default: current directory).",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        },
        fn=find_files,
        read_only=True,
    ),
    "delete_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Deletes a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path of the file to delete.",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        fn=delete_file,
        read_only=False,
    ),
    "move_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "move_file",
                "description": "Moves or renames a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "description": "Current path of the file.",
                        },
                        "destination": {
                            "type": "string",
                            "description": "New path of the file.",
                        },
                    },
                    "required": ["source", "destination"],
                },
            },
        },
        fn=move_file,
        read_only=False,
    ),
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
    "fetch_url": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetches a URL and returns its text content "
                "(HTML tags stripped for web pages).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to fetch (must start with http:// or https://).",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
        fn=fetch_url,
        read_only=True,
    ),
    "web_search": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Searches the web and returns the top result titles and URLs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        fn=web_search,
        read_only=True,
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
    "todo_write": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "todo_write",
                "description": "Replaces the current task list, to track progress on a "
                "multi-step piece of work across a long conversation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed"],
                                    },
                                },
                                "required": ["content", "status"],
                            },
                            "description": "The full task list (replaces the previous one).",
                        },
                    },
                    "required": ["todos"],
                },
            },
        },
        fn=todo_write,
        read_only=True,
    ),
    "remember": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Saves a short fact or note to persistent memory, so it's "
                "available in future conversations without needing to be repeated.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note": {
                            "type": "string",
                            "description": "Fact or note to remember.",
                        },
                    },
                    "required": ["note"],
                },
            },
        },
        fn=remember,
        read_only=False,
    ),
    "dispatch_subagent": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "dispatch_subagent",
                "description": "Starts a focused, read-only research sub-agent in the "
                "background and returns immediately, without waiting for it to finish "
                "(true parallel execution: keep working while it runs). Its own reasoning "
                "and tool calls stay isolated from this conversation, only its final "
                "result comes back, when checked with check_subagent. Give it a "
                "self-contained task description, since it starts with no context "
                "beyond what's provided.",
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
                "returns its result if it finished, or that it's still running.",
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
}

TOOLS: list[ChatCompletionToolParam] = [tool.schema for tool in TOOLS_REGISTRY.values()]


def rebuild_tools_list() -> None:
    """Recomputes TOOLS from TOOLS_REGISTRY, mutating the list in place
    (never reassigning): main.py and server.py did `from tools import
    TOOLS` and therefore hold a reference to this same list object, a
    reassignment wouldn't be seen by those modules. Called by mcp_client.py
    on every MCP server connect/disconnect, so remote tools appear/disappear
    without any change on the main.py/server.py side."""
    TOOLS.clear()
    TOOLS.extend(tool.schema for tool in TOOLS_REGISTRY.values())
