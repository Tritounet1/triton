import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai.types.chat import ChatCompletionToolParam


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
                "description": "Writes content to a text file "
                "(overwrites it if it already exists).",
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
                "description": "Runs a shell command and returns its output.",
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
