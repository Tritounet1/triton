"""Two kinds of memory: todo_write's task list (in-process only, cleared on
restart - a scratchpad for the current conversation) and remember's
memory.md (persisted to disk, carried into every future conversation's
system prompt via load_memory - see llm/chat_loop.py's
build_system_message)."""

from triton.paths import ROOT_DIR
from triton.tools._shared import Tool

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


MEMORY_FILE = ROOT_DIR / "memory.md"


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


REGISTRY: dict[str, Tool] = {
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
}
