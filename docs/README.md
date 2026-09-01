# Triton Documentation

Triton is an AI agent harness built from scratch: a Python backend (FastAPI) running an agentic loop (model + tools), consumed by a desktop app (Tauri + React) and a CLI. The point of the project: understand concretely what happens "under the hood" of a tool like Claude Code, by rebuilding it.

This documentation describes the application's current state, feature by feature, with concrete explanations - not just a feature list.

## Table of contents

1. [Architecture](01-architecture.md) - overview of the code, the three entry points, and the data file layout
2. [Chat and tools](02-chat-and-tools.md) - the agentic loop, action confirmation, and the 22 tools available to the model
3. [Projects and security](03-projects-and-security.md) - per-folder sandboxing, the write-tool safety net (snapshots), `run_shell` isolation
4. [Memory](04-memory.md) - the three memory tiers (global / project / conversation)
5. [Multi-agent](05-multi-agent.md) - the orchestrator (`/multi-agents`) and research sub-agents
6. [Sessions and commands](06-sessions-and-commands.md) - pin/rename/export, model override, cost, and the `/` commands
7. [Settings and integrations](07-settings-and-integrations.md) - model/budget/API key, multi-agent roles, MCP servers, background tasks
8. [Desktop app](08-desktop-app.md) - file panel, PDF/HTML/Markdown viewer, keyboard shortcuts
9. [HTTP API](09-api-reference.md) - using the API directly (curl, scripts), without the app or CLI

## Quick start

```bash
# backend (from the repo root)
uv run python3 server.py          # API on http://127.0.0.1:8000, docs on /docs

# desktop app (from app-desktop/)
pnpm tauri dev

# CLI (alternative to the desktop app, from the repo root)
uv run python3 main.py
```

An OpenRouter API key needs to be configured (Settings in the app, or `PUT /settings/api_key`) before the model can respond - every model goes through OpenRouter (`src/triton/llm/api.py`).

## Where data lives

Everything is stored locally at the repo root (never versioned, see `.gitignore`):

| File / directory | Content |
|---|---|
| `sessions/` | Each conversation's history (`<id>.json`) and its sidecar files (title, pin, permissions, model override, memory) |
| `projects.json` | List of projects (id, name, folder path) |
| `project_memory/` | Memory shared by a project's conversations |
| `memory_global.md` | Global memory (shared by everything, currently empty - see [Memory](04-memory.md)) |
| `settings.json` | Default model, monthly budget, OpenRouter API key, per-role model overrides |
| `logs/events.jsonl` | Raw log of every model call / tool call |
| `snapshots.json`, `snapshot_backups/` | Write-tool safety net (see [Projects and security](03-projects-and-security.md)) |
| `background_tasks_state/` | State of background tasks started by the model |
| `mcp_servers.json` | Configuration of connected MCP servers |
