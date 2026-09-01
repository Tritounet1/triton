"""Two kinds of memory: todo_write's task list (in-process only, cleared on
restart - a scratchpad for the current conversation) and remember, which
writes to one of two scoped, persisted files depending on the calling
conversation - see storage/sessions.py's per-session memory and
storage/projects.py's per-project memory (a project's conversations share
one file; a project-less conversation's memory is its own). Both, plus a
third global tier (storage/memory.py), are read back into the system
prompt by llm/chat_loop.py's build_system_message - never here, this
module only writes."""

from triton.storage.projects import append_project_memory
from triton.storage.sessions import append_session_memory, load_session_project
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


def remember(note: str, session_id: str) -> str:
    """Writes to the project's shared memory if this conversation belongs
    to one (so every other conversation in that project sees it too, now
    and later), otherwise to this conversation's own memory alone - see
    the module docstring for why there's no single memory.md anymore."""
    project_id = load_session_project(session_id)
    try:
        if project_id:
            append_project_memory(project_id, note)
        else:
            append_session_memory(session_id, note)
    except OSError as e:
        return f"error: could not write to memory ({e})"
    return f"remembered: {note.strip()}"


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
                "available without needing to be repeated - shared with every other "
                "conversation in the same project if this one belongs to one, otherwise "
                "private to this conversation alone.",
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
