"""Tools exposed to the model, split by category (this used to be one
~1000-line file). Every submodule builds its own REGISTRY of {name: Tool};
this file merges them into TOOLS_REGISTRY and TOOLS, so nothing outside
this package needs to know it's split up at all - `from triton.tools
import TOOLS_REGISTRY` (and everything else re-exported below) works
exactly as it did before.

- _shared.py    the Tool type, invoke_tool, and the project-folder sandbox
- filesystem.py read/write/edit/delete/move a file, list a directory
- search.py     grep, glob
- git.py        status/diff/commit
- process.py    run_shell, run_tests, run_code
- web.py        fetch_url, web_search
- memory.py     todo_write (in-process), remember (writes only - see
                 storage/sessions.py, storage/projects.py, storage/memory.py
                 for the three memory tiers it writes to and
                 llm/chat_loop.py's build_system_message for reading them back)
- background.py dispatch_subagent/check_subagent, start/stop/list
                 background tasks - thin wrappers, the real logic lives in
                 triton.agents.subagents / triton.background_tasks
- snapshot.py   the write-tool safety net (ensure_snapshot/restore_snapshot) -
                 not a tool category itself (registers nothing in
                 TOOLS_REGISTRY), called around write_file/edit_file/
                 delete_file/move_file from server.py and orchestrator.py
"""

from openai.types.chat import ChatCompletionToolParam

from triton.tools import background, filesystem, git, memory, process, search, web
from triton.tools._shared import (
    DEFAULTABLE_PATH_ARGS,
    SANDBOXED_PATH_ARGS,
    SESSION_AWARE_TOOLS,
    SKIP_DIR_NAMES,
    Tool,
    enforce_project_sandbox,
    invoke_tool,
    is_skipped,
)
from triton.tools.snapshot import (
    WRITE_TOOL_NAMES,
    RestoreError,
    SnapshotDiff,
    diff_snapshot,
    discard_snapshot,
    ensure_snapshot,
    restore_snapshot,
)
from triton.tools.web import is_tavily_configured

__all__ = [
    "DEFAULTABLE_PATH_ARGS",
    "SANDBOXED_PATH_ARGS",
    "SESSION_AWARE_TOOLS",
    "SKIP_DIR_NAMES",
    "TOOLS",
    "TOOLS_REGISTRY",
    "WRITE_TOOL_NAMES",
    "RestoreError",
    "SnapshotDiff",
    "Tool",
    "diff_snapshot",
    "discard_snapshot",
    "enforce_project_sandbox",
    "ensure_snapshot",
    "invoke_tool",
    "is_skipped",
    "is_tavily_configured",
    "rebuild_tools_list",
    "restore_snapshot",
]

TOOLS_REGISTRY: dict[str, Tool] = {
    **filesystem.REGISTRY,
    **search.REGISTRY,
    **git.REGISTRY,
    **process.REGISTRY,
    **web.REGISTRY,
    **memory.REGISTRY,
    **background.REGISTRY,
}

TOOLS: list[ChatCompletionToolParam] = [tool.schema for tool in TOOLS_REGISTRY.values()]


def rebuild_tools_list() -> None:
    """Recomputes TOOLS from TOOLS_REGISTRY, mutating the list in place
    (never reassigning): main.py and server.py did `from triton.tools
    import TOOLS` and therefore hold a reference to this same list object,
    a reassignment wouldn't be seen by those modules. Called by
    mcp_client.py on every MCP server connect/disconnect, so remote tools
    appear/disappear without any change on the main.py/server.py side."""
    TOOLS.clear()
    TOOLS.extend(tool.schema for tool in TOOLS_REGISTRY.values())
