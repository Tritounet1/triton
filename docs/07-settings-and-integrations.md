# Settings and integrations

## General settings (`storage/settings.py`, `settings.json`)

| Setting | Endpoint | Notes |
|---|---|---|
| Default model | `GET`/`PUT /settings/model` | Used by any conversation without an override (`/model`, see [Sessions and commands](06-sessions-and-commands.md)) |
| OpenRouter API key | `GET`/`PUT /settings/api_key` | Required for the model to respond at all |
| Monthly budget | `GET`/`PUT /settings/budget` | **Shown but not enforced yet**: nothing blocks or warns today past the threshold - a functional no-op, still to be wired up |
| Multi-agent roles | `GET`/`PUT /settings/role_models` | Overrides the model used for a given role (`code`, `research`, `vision`, `conversational`, `orchestrator`) - see [Multi-agent](05-multi-agent.md) |

The model catalog (`GET /openrouter/models`) is cached server-side with a short TTL, to avoid a network round-trip every time settings are opened.

## MCP servers (Model Context Protocol)

An external MCP server (same format as Claude Desktop: `command`/`args`/`env`) dynamically adds its own tools to the model's registry (`mcp_client.py`), manageable from settings (list, add, enable/disable, remove - `GET`/`POST /mcp/servers`, `PUT`/`DELETE /mcp/servers/{name}`).

A notable implementation detail: the MCP SDK is async, the rest of the harness (tool execution) is synchronous. Rather than rewriting the entire agentic loop as async, a dedicated `asyncio` loop runs in its own thread and hosts every open MCP session; each synchronous tool call submits its coroutine to that loop and waits for the result.

**Known limitation**: only MCP *tools* are used (`list_tools`/`call_tool`) - servers that expose resources or prompts (other primitives of the MCP protocol) aren't leveraged yet.

## Background tasks

A long-running process (dev server, watcher, a build in `--watch` mode...) started by the model via `start_background_task`, distinct from a sub-agent (`background_tasks.py`): a real subprocess with real stdout, not another agentic loop.

Built to survive a harness restart (manual or via `uvicorn --reload`):
- The process's output is redirected straight to a log file on disk (never read through a pipe by the harness), so the child process keeps writing normally even if the harness that spawned it stops.
- Task metadata (id, command, pid, status...) is persisted on every change and reloaded on startup: a "running" task whose pid is still alive gets a watcher thread (polling `os.kill(pid, 0)`, since it's no longer a direct child process); one whose pid is gone gets marked "exited" (its real exit code is lost along with the harness process that would have read it).

The desktop app shows them in a dedicated panel (`BackgroundTasksPanel.tsx`/`BackgroundTasksSection.tsx`), with a full-screen "terminal" view to follow output live (`TaskView.tsx`).

**Known limitations**: no cap on the number of concurrent tasks, no auto-restart on crash, no scheduling (cron-like) - "start now, run until stopped" is the only mode.
