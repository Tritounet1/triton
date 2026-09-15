"""Global memory: the third tier alongside per-session memory
(storage/sessions.py) and per-project memory (storage/projects.py) -
shared across every conversation regardless of project or session scope.

Written only through the /remember global command (server.py's POST
/memory/global) for now, not by the model itself: the remember tool only
ever writes to the session/project tier (see tools/memory.py) - a
deliberate choice to keep the model from silently promoting something to
"every conversation forever" on its own judgment."""

from triton.paths import ROOT_DIR

GLOBAL_MEMORY_FILE = ROOT_DIR / "memory_global.md"


def load_global_memory() -> str:
    if not GLOBAL_MEMORY_FILE.exists():
        return ""
    return GLOBAL_MEMORY_FILE.read_text().strip()


def append_global_memory(note: str) -> None:
    with GLOBAL_MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(f"- {note.strip()}\n")


def set_global_memory(content: str) -> None:
    """Overwrites the whole file - the memory browser's save action (see
    server.py's PUT /memory/global), letting the user edit/delete notes
    by hand instead of only ever appending one at a time."""
    GLOBAL_MEMORY_FILE.write_text(content)
