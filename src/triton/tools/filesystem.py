"""Reading, writing, and editing files - the tools an agent reaches for
most, and the ones enforce_project_sandbox (_shared.py) confines to a
project's folder when one is scoped."""

from pathlib import Path

from triton.tools._shared import Tool


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


REGISTRY: dict[str, Tool] = {
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
}
