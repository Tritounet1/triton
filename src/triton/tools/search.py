"""Searching within a directory tree: grep (content) and glob (filenames).
Both skip the same noisy directories (SKIP_DIR_NAMES in _shared.py) so a
search over a real project doesn't wade through node_modules/.venv/etc."""

import re
from pathlib import Path

from triton.tools._shared import Tool, is_skipped


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


REGISTRY: dict[str, Tool] = {
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
}
