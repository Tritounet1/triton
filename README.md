# Triton

A small AI agent harness built from scratch in Python, as a learning project to understand how tools like Claude Code work under the hood: the loop that turns a plain LLM into an agent capable of using tools, keeping memory, and acting safely.

## What's a harness?

An LLM on its own only does one thing: take text in, give text out. It can't read a file, run a command, remember yesterday, or decide on its own when to stop.

The **harness** is all the code around the model that turns it into an agent capable of acting: the loop that calls the API, gives the model a list of tools it can ask to use, actually executes those tools, feeds the result back to the model, repeats until a final answer, and handles memory, permissions, and errors around all of that.

The model is the "brain" (it decides what to do), the harness is the "body" (it's what actually lets it happen, within a safe boundary). Claude Code, Cursor, Aider, or LangChain's `AgentExecutor` are all harnesses: same underlying model, but a different harness makes for a completely different tool in practice.

### The base loop

```
1. The user writes a message
2. The harness sends the full history + available tools to the model
3. The model replies either:
   a. with final text -> display it, go back to step 1
   b. with a tool request ("call read_file with path=main.py")
4. On a tool request: the harness actually runs the tool, appends the result
   to the history, and goes back to step 2 (without asking the user again)
5. Repeat until a final answer, with a max iteration limit
```

This loop (called "ReAct" in the literature: Reason + Act) is the core of any harness, from the simplest to the most complex. Everything else (memory, permissions, observability) is built around it.

## Features

- Multi-turn chat with streaming responses
- Tool calling in a ReAct-style loop: read files, list directories, write files, run shell commands
- Permission prompt before any action that modifies something (writing a file, running a command)
- Automatic context compression once the conversation history grows too large
- Persistent sessions: conversations are saved to disk and resumed automatically on the next run
- Structured JSONL logs, plus a small script to summarize them

## Stack

- Python 3.13, managed with [uv](https://docs.astral.sh/uv/)
- OpenAI-compatible SDK, calling models through [OpenRouter](https://openrouter.ai)
- [rich](https://github.com/Textualize/rich) for the terminal UI, [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) for input

## Running it

```
uv sync
cp .env.template .env   # fill in your OpenRouter API key
uv run main.py
```

To inspect the logs afterward:

```
uv run logs_summary.py
```

## Desktop app

`app-desktop/` is a [Tauri](https://tauri.app) + React app that talks to `server.py`, a small FastAPI server exposing the same agentic loop over HTTP (streaming via Server-Sent Events, with tool confirmations paused mid-stream until the client approves or denies them).

Its interface is built with [Astryx](https://astryx.atmeta.com/docs/getting-started), Meta's open-source React design system: components (`AppShell`, `SideNav`, the `Chat*` family) plus a Tailwind v4 token bridge, no separate build step required.

Run the API first, then the app:

```
uv run server.py
```

```
cd app-desktop
pnpm install
pnpm tauri dev
```

## Harness architecture

```
harness/
├── api.py                 model calls: call_chat() / stream_chat(), the ChatResult type
├── tools.py                tools exposed to the model: read_file, list_files, write_file, run_shell
├── sessions.py              conversation persistence (JSON) and their titles
├── logs.py                  structured logs, one JSON event per line (logs/events.jsonl)
├── logs_summary.py          CLI summary of the logs (uv run logs_summary.py)
│
├── main.py                 ── ENTRY POINT #1 : interactive CLI (rich + prompt_toolkit)
├── server.py                ── ENTRY POINT #2 : the same loop over HTTP/SSE, for the desktop app
│
└── app-desktop/             Tauri + React GUI, talks to server.py
    └── src/
        ├── App.tsx            chat view: sidebar, streaming, tool confirmations
        ├── SettingsPage.tsx   settings, links to the log viewer
        └── LogsPage.tsx       reads logs.py's events through GET /logs
```

**Two entry points, one loop.** `main.py` and `server.py` both drive the exact same agentic loop, built from the same pieces above (`api.py`, `tools.py`, `sessions.py`, `logs.py`), just through different interfaces:

- `main.py` talks to a human directly in a terminal: synchronous, renders with `rich`, confirms risky tools with a blocking `Confirm.ask()`.
- `server.py` drives the same loop for the desktop app over HTTP: streams events as Server-Sent Events, and pauses on a tool confirmation with a `threading.Event` instead of blocking on terminal input, since there is no terminal to block on.

To avoid duplicating the loop itself, `server.py` imports directly from `main.py` (`compress_history_if_needed`, `timed_stream_chat`, `to_tool_call_params`). Only the tool-confirmation flow is genuinely rewritten in `server.py`, because a terminal prompt and an HTTP request/response are fundamentally different I/O models, everything else is shared code.
