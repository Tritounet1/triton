# Architecture

## Three entry points, one shared core

```
main.py            server.py                app-desktop/
(CLI, terminal)     (HTTP/SSE API)            (Tauri + React)
      \                  |                        |
       \                 |                        |
        \-------- src/triton/ ----------- talks to server.py over HTTP
             (shared logic)
```

- **`main.py`** - interactive CLI (`prompt_toolkit` + `rich`). Runs the agentic loop directly, no network involved. No project concept - a conversation is just a history file under `sessions/`.
- **`server.py`** - FastAPI/SSE API (~1200 lines). This is the real application core: everything the desktop app does goes through here. `POST /chat` streams its response (Server-Sent Events), everything else is plain JSON. Interactive docs at `/docs` (see [HTTP API](09-api-reference.md)).
- **`app-desktop/`** - Tauri app (a light native shell + webview) with a React UI. Talks exclusively to `server.py` over HTTP (`http://127.0.0.1:8000`), never directly to the model.

Both clients (CLI and desktop) share all business logic through `src/triton/`, avoiding duplication of the agentic loop, sandboxing, or cost calculation.

## `src/triton/` layout

```
src/triton/
├── llm/            # model calls, streaming loop, history compression, cost
│   ├── api.py          call_chat / stream_chat (OpenRouter calls, with/without streaming)
│   ├── chat_loop.py     build_system_message, timed_stream_chat, compress_history_if_needed
│   ├── model_roles.py   which model handles which multi-agent role
│   └── pricing.py       estimate_cost (cost computed from the OpenRouter catalog)
├── agents/         # multi-agent
│   ├── orchestrator.py  planning + dispatch + synthesis (/multi-agents)
│   └── subagents.py     background research sub-agents (dispatch_subagent)
├── tools/          # everything the model can call - see 02-chat-and-tools.md
├── storage/        # persistence: sessions, projects, settings, logs, memory, snapshots
├── mcp_client.py   # connection to external MCP servers
├── background_tasks.py  # long-running processes started by the model
├── logs_summary.py # command-line summary of the logs (standalone script, not the API)
└── paths.py        # computes ROOT_DIR (repo root in dev, an app-data folder in a frozen build)
```

A dependency rule worth keeping in mind (and one that was an actual source of friction in this project - see `agents/subagents.py`'s history): `storage/` never depends on `tools/` or `agents/`, and `llm/` no longer depends on `tools/` since memory moved to a three-tier system. This avoids an import cycle between `tools/background.py` (which imports `agents/subagents.py` to register its tools) and everything else.

## The agentic loop (the harness's core)

Whether in `main.py` or `server.py`, the principle is the same (`run_chat_stream` in `server.py`):

1. The user's message is appended to the history.
2. The model is called with the full history plus the list of available tools (`TOOLS`, built dynamically in `src/triton/tools/__init__.py`).
3. If the model replies with plain text: it's streamed to the client, the turn ends.
4. If the model replies with one or more tool calls:
   - Each call is validated (`enforce_project_sandbox` if the conversation is scoped to a project).
   - If the tool mutates something (`read_only=False`) and hasn't already been approved for this conversation, the client receives a `confirmation_required` event and the loop **waits** (up to 5 minutes) for the user's response.
   - The tool runs (`invoke_tool`), its result is appended to the history as a `tool` message.
   - Back to step 2 (the model sees the result and continues), up to `MAX_ITERATIONS` (25) or until it replies with plain text.

This loop - "the model can ask to act, it gets handed back control with the result" - does all the work. Nothing more sophisticated happens "under the hood".

## Automatic history compression

A long conversation eventually outgrows a useful context window. `compress_history_if_needed` (`chat_loop.py`) tracks the history's size (a rough approximation: 1 token ≈ 4 characters) and, past `MAX_CONTEXT_CHARS`, summarizes the oldest turns into a single system message via a dedicated model call - always keeping the last `KEEP_RECENT_TURNS` turns intact. Attachments (images/PDFs) in summarized turns are replaced with just a filename in the summary, never resent as base64 (this was a real bug fixed along the way: a summarization call that was resending ~900k tokens of encoded images).
