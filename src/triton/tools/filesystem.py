"""Reading, writing, and editing files - the tools an agent reaches for
most, and the ones enforce_project_sandbox (_shared.py) confines to a
project's folder when one is scoped."""

from pathlib import Path
from typing import cast

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


def edit_file(edits: list[dict[str, object]]) -> str:
    """Applies one or more {path, old_string, new_string, replace_all?}
    edits, across one or more files, in a single call. Edits for the same
    path are applied in order against that file's running content (each
    one sees the previous one's result) - this is what makes several
    hunks in one file possible, not just several files at once. Each
    file is handled independently and atomically: if any of its hunks
    fails (old_string missing, or ambiguous without replace_all), that
    file is left completely untouched and the failure is reported for
    it, but every other file's edits still apply and get written -
    a model batching several files rarely needs to retry more than the
    one that actually failed."""
    if not edits:
        return "error: no edits provided"

    by_path: dict[str, list[dict[str, object]]] = {}
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            return f"error: edit {i + 1} is not an object with path/old_string/new_string"
        path = e.get("path")
        old_string = e.get("old_string")
        new_string = e.get("new_string")
        if not isinstance(path, str) or not path:
            return f"error: edit {i + 1} is missing 'path'"
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return f"error: edit {i + 1} ({path}) needs 'old_string' and 'new_string'"
        by_path.setdefault(path, []).append(
            {
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": bool(e.get("replace_all")),
            }
        )

    results: list[str] = []
    for path, hunks in by_path.items():
        try:
            content = Path(path).read_text()
        except OSError as e:
            results.append(f"{path}: error: could not read ({e})")
            continue

        working = content
        failed = False
        for i, hunk in enumerate(hunks):
            old_string = cast(str, hunk["old_string"])
            new_string = cast(str, hunk["new_string"])
            replace_all = cast(bool, hunk["replace_all"])
            count = working.count(old_string)
            if count == 0:
                results.append(
                    f"{path}: error: old_string not found (hunk {i + 1}/{len(hunks)}) "
                    "- no changes written to this file"
                )
                failed = True
                break
            if count > 1 and not replace_all:
                results.append(
                    f"{path}: error: old_string matches {count} times "
                    f"(hunk {i + 1}/{len(hunks)}), use replace_all=true or a more specific "
                    "old_string - no changes written to this file"
                )
                failed = True
                break
            working = working.replace(old_string, new_string, -1 if replace_all else 1)

        if failed:
            continue

        try:
            Path(path).write_text(working)
        except OSError as e:
            results.append(f"{path}: error: could not write ({e})")
            continue
        results.append(f"{path}: {len(hunks)} edit(s) applied")

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
                "description": "Applies one or more exact text replacements, across one or "
                "more files, in a single call - without rewriting whole files. Multiple "
                "edits for the same path are applied in order (each sees the previous "
                "one's result), so several hunks in one file, or changes spanning several "
                "files, go in one call instead of one edit_file call per hunk. Each edit "
                "fails independently: a file whose old_string isn't found (or matches more "
                "than once without replace_all) is left untouched, but every other file's "
                "edits still apply.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "edits": {
                            "type": "array",
                            "description": "One or more edits to apply.",
                            "items": {
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
                                        "description": "Replace every occurrence in this "
                                        "file instead of failing on ambiguity "
                                        "(default: false).",
                                    },
                                },
                                "required": ["path", "old_string", "new_string"],
                            },
                        },
                    },
                    "required": ["edits"],
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
