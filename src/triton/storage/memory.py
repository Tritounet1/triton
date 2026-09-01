"""Global memory: the third tier alongside per-session memory
(storage/sessions.py) and per-project memory (storage/projects.py) -
shared across every conversation regardless of project or session scope.

Scaffolding only for now: always loaded into the system prompt (see
llm/chat_loop.py's build_system_message), but nothing writes to it yet -
no tool exposes it, and the file doesn't need to exist (an absent file
just means an empty global memory, same as the other two tiers). What
populates it and how is deliberately deferred."""

from triton.paths import ROOT_DIR

GLOBAL_MEMORY_FILE = ROOT_DIR / "memory_global.md"


def load_global_memory() -> str:
    if not GLOBAL_MEMORY_FILE.exists():
        return ""
    return GLOBAL_MEMORY_FILE.read_text().strip()
